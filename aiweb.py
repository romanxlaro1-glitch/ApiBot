#!/usr/bin/env python3
"""
Pure-HTML AI scrapers - no JSON API, no key, no Cloudflare.

These exist because the user wants a scrape-first API. Where a JSON endpoint is
available (see ai.py) it is cheaper and more precise, so those stay the default;
this module covers the sites that only publish real data in server-rendered
HTML, which is exactly what a scraper should be reading anyway.

Verified shapes:
  * huggingface.co/models      - model cards as <a href="/owner/name">, likes in
                                 the card footer, task as a tag
  * huggingface.co/papers     - paper rows with arXiv id, title, upvote count
  * ollama.com/library       - 240+ model links, download count per card
  * anthropic.com/news       - article cards, plain <a> with a heading
"""

import re

HF_WEB = "https://huggingface.co"
OLLAMA = "https://ollama.com"

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _txt(s):
    if not s:
        return ""
    s = _TAG.sub(" ", s).replace("&amp;", "&").replace("&#39;", "'") \
        .replace("&quot;", '"').replace("&nbsp;", " ").replace("&#x27;", "'")
    return _WS.sub(" ", s).strip()


# --------------------------------------------------------------------------
# Hugging Face
# --------------------------------------------------------------------------
def _num(raw):
    """'4.53k' -> 4530, '99.2M' -> 99200000, '12' -> 12."""
    try:
        return int(float(raw.rstrip("kKmM")) *
                   {"k": 1e3, "m": 1e6}.get(raw[-1].lower(), 1))
    except (ValueError, AttributeError):
        return None


# The last number token inside a card footer is the like count; everything
# before it is params (0.4B) / updated-ago text.
_TASKS = {
    "text generation", "text-to-image", "image-to-text", "question answering",
    "question-answering", "summarization", "translation", "text classification",
    "text-classification", "fill-mask", "feature extraction", "feature-extraction",
    "text-to-speech", "automatic speech recognition",
    "automatic-speech-recognition", "zero-shot classification",
    "zero-shot-classification", "image classification",
    "image-classification", "text-to-video", "image-to-video", "image segmentation",
    "reinforcement learning", "reinforcement-learning", "tabular classification",
}


def parse_hf_cards(html, limit=30):
    """Model cards from the /models listing.

    Each card is <article class="overview-card-wrapper"> containing an <a> to
    /owner/model, the task label, the param count, the "updated N ago" text and
    the like count as the final bare number.
    """
    out, seen = [], set()
    for block in re.split(r'(?=<article class="overview-card-wrapper)', html)[1:]:
        m = re.search(r'href="/([A-Za-z0-9\-_.]+/[A-Za-z0-9\-_.]+)"', block)
        if not m:
            continue
        model_id = m.group(1)
        if model_id in seen:
            continue
        text = _txt(re.sub(r"<svg.*?</svg>", " ", block, flags=re.S))
        task = next((t for t in _TASKS if t in text.lower()), None)
        params = None
        pm = re.search(r"\b(\d+(?:\.\d+)?[BM])\b", text)
        if pm:
            params = pm.group(1)
        updated = None
        um = re.search(r"Updated\s+([^|•]+)", text)
        if um:
            updated = um.group(1).strip()
        # likes = last number that is not the param count / avatar digits
        likes = None
        for tok in re.findall(r"\b(\d+(?:\.\d+)?[kKmM]?)\b", text):
            if tok == params:
                continue
            v = _num(tok)
            if v is not None and v >= 10:
                likes = v
        seen.add(model_id)
        out.append({
            "id": model_id,
            "task": task,
            "params": params,
            "likes": likes,
            "updated": updated,
            "url": HF_WEB + "/" + model_id,
        })
        if len(out) >= limit:
            break
    return out


def parse_hf_papers_html(html, limit=20):
    """Daily papers from /papers.

    SvelteKit hydrates the list into a `data-props` attribute on
    <div class="SVELTE_HYDRATER" data-target="DailyPapers">. That JSON is the
    real payload - the rendered cards are mostly placeholders - so read it.
    """
    import html as _h
    import json as _j
    m = re.search(r'data-target="DailyPapers"\s+data-props="([^"]+)"', html)
    if m:
        try:
            props = _j.loads(_h.unescape(m.group(1)))
        except ValueError:
            props = {}
        rows = []
        for entry in (props.get("dailyPapers") or [])[:limit]:
            p = entry.get("paper") or {}
            pid = p.get("id") or ""
            if not pid:
                continue
            rows.append({
                "id": pid,
                "title": _txt(p.get("title") or entry.get("title") or "")[:220] or None,
                "authors": [a.get("name") for a in (p.get("authors") or [])
                            if a.get("name")][:8],
                "summary": _txt(p.get("summary") or entry.get("summary") or "")[:600] or None,
                "upvotes": p.get("upvotes"),
                "comments": entry.get("numComments"),
                "github_stars": p.get("githubStars"),
                "published": p.get("publishedAt") or entry.get("publishedAt"),
                "url": HF_WEB + "/papers/" + pid,
            })
        if rows:
            return rows
    # fallback for a markup change: id + first heading after it
    out, seen = [], set()
    for hm in re.finditer(r'href="/papers/(\d{4}\.\d{4,5})"', html):
        pid = hm.group(1)
        if pid in seen:
            continue
        seg = html[hm.start():hm.start() + 2000]
        title = None
        for x in re.finditer(r'<h[1-6][^>]*>(.*?)</h[1-6]>', seg, re.S):
            t = _txt(x.group(1))
            if len(t) > 12:
                title = t[:220]
                break
        seen.add(pid)
        out.append({"id": pid, "title": title, "authors": [],
                    "summary": None, "upvotes": None, "comments": None,
                    "github_stars": None, "published": None,
                    "url": HF_WEB + "/papers/" + pid})
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------
# Ollama
# --------------------------------------------------------------------------
def parse_ollama(html, limit=60):
    """Model cards from ollama.com/library."""
    out, seen = [], set()
    for m in re.finditer(
            r'href="/library/([a-z0-9][a-z0-9\-:._]*)"(.*?)(?=<li|</ul>)', html, re.S):
        slug, block = m.group(1), m.group(2)
        if slug in seen:
            continue
        # strip tags
        text = _txt(block)
        if not text:
            continue
        pulls = None
        pm = re.search(r'([\d.]+[kKmM]?)\s*(?:Pulls|pulls)', text)
        if pm:
            raw = pm.group(1)
            mult = {"k": 1e3, "m": 1e6}.get(raw[-1].lower(), 1)
            try:
                pulls = int(float(raw.rstrip("kKmM")) * mult)
            except ValueError:
                pulls = None
        tags = re.findall(r'>\s*([a-z0-9\-]{2,20})\s*<', block)
        seen.add(slug)
        out.append({
            "model": slug,
            "pulls": pulls,
            "tags": [t for t in tags if t not in ("llm", "")][:8],
            "summary": text[:200],
            "url": OLLAMA + "/library/" + slug,
        })
        if len(out) >= limit:
            break
    return out
