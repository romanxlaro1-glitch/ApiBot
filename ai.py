#!/usr/bin/env python3
"""
AI endpoints: models, papers, news.

Every upstream here is a plain public JSON or RSS endpoint - no Cloudflare, no
API key, no signup:
  * Hugging Face  - /api/models (trending + search), /api/daily_papers
  * OpenRouter    - /api/v1/models, the widest public model catalogue
  * Hacker News   - Algolia API, keyword search (no rate limit worth worrying
                    about, and it stays up when bigger sites block you)
  * Google News RSS - same trick already used for the JKT48 endpoint

Sources that looked promising but are unusable from a scraper: openai.com/news
(403), GitHub search API (403 without a token), Reddit .json (403), Perplexity
(403), Replicate/Together/Groq (need a key), arXiv export (times out).
"""

import re

HF = "https://huggingface.co/api"
OPENROUTER = "https://openrouter.ai/api/v1/models"
HN = "https://hn.algolia.com/api/v1/search"
GNEWS = "https://news.google.com/rss/search"

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# OpenRouter ships a very long description per model; the API only needs the
# first line, and returning all of them would blow the response budget.
_DESC_LIMIT = 300


def _txt(s):
    if not s:
        return ""
    return _WS.sub(" ", _TAG.sub(" ", s)).replace("&amp;", "&") \
        .replace("&#39;", "'").replace("&quot;", '"') \
        .replace("&nbsp;", " ").strip()


# --------------------------------------------------------------------------
# Hugging Face
# --------------------------------------------------------------------------
def parse_hf_models(payload, limit=20):
    rows = []
    for m in (payload or [])[:limit]:
        tags = m.get("tags") or []
        rows.append({
            "id": m.get("id") or m.get("modelId"),
            "task": m.get("pipeline_tag"),
            "likes": m.get("likes"),
            "downloads": m.get("downloads"),
            "trending": m.get("trendingScore"),
            "library": m.get("library_name"),
            "created": m.get("createdAt"),
            "tags": [t for t in tags if isinstance(t, str)][:12],
            "url": "https://huggingface.co/" + (m.get("id") or m.get("modelId") or ""),
        })
    return rows


def parse_hf_papers(payload, limit=20):
    rows = []
    for entry in (payload or [])[:limit]:
        p = entry.get("paper") or entry
        pid = p.get("id") or ""
        rows.append({
            "id": pid,
            "title": _txt(p.get("title") or entry.get("title") or ""),
            "authors": [a.get("name") for a in (p.get("authors") or []) if a.get("name")][:8],
            "summary": _txt(p.get("summary") or entry.get("summary") or "")[:600] or None,
            "published": p.get("publishedAt") or entry.get("publishedAt"),
            "upvotes": p.get("upvotes"),
            "comments": entry.get("numComments"),
            "url": "https://huggingface.co/papers/" + pid if pid else None,
        })
    return rows


# --------------------------------------------------------------------------
# OpenRouter
# --------------------------------------------------------------------------
def parse_openrouter(payload, limit=60, provider=None, only_reasoning=None):
    data = (payload or {}).get("data") or []
    rows = []
    for m in data:
        if provider and provider.lower() not in (m.get("id") or "").lower():
            continue
        if only_reasoning is not None and bool(m.get("reasoning")) is not only_reasoning:
            continue
        pricing = m.get("pricing") or {}
        try:
            prompt_price = float(pricing.get("prompt") or 0) * 1_000_000
            completion_price = float(pricing.get("completion") or 0) * 1_000_000
        except (TypeError, ValueError):
            prompt_price = completion_price = None
        rows.append({
            "id": m.get("id"),
            "name": m.get("name"),
            "context_length": m.get("context_length"),
            "architecture": (m.get("architecture") or {}).get("modality"),
            "reasoning": bool(m.get("reasoning")),
            "usd_per_1m_prompt": prompt_price,
            "usd_per_1m_completion": completion_price,
            "usd_per_1m_image": (lambda v: float(v) * 1_000_000
                                 if str(v or "").replace(".", "").isdigit() else None)(
                                     pricing.get("image")),
            "description": _txt(m.get("description") or "")[:_DESC_LIMIT] or None,
            "url": "https://openrouter.ai/" + (m.get("id") or ""),
        })
        if len(rows) >= limit:
            break
    rows.sort(key=lambda r: (r["usd_per_1m_prompt"] is None,
                             r["usd_per_1m_prompt"] or 0))
    return rows


# --------------------------------------------------------------------------
# Hacker News (Algolia)
# --------------------------------------------------------------------------
def parse_hn(payload, limit=20):
    hits = (payload or {}).get("hits") or []
    rows = []
    for h in hits[:limit]:
        rows.append({
            "title": h.get("title"),
            "points": h.get("points"),
            "comments": h.get("num_comments"),
            "author": h.get("author"),
            "created": h.get("created_at"),
            "url": h.get("url") or ("https://news.ycombinator.com/item?id=%s" % h.get("objectID")),
            "discussion": "https://news.ycombinator.com/item?id=%s" % h.get("objectID"),
        })
    return rows


# --------------------------------------------------------------------------
# Google News RSS
# --------------------------------------------------------------------------
def parse_rss(xml, limit=20):
    items = re.findall(r"<item>(.*?)</item>", xml or "", re.S)
    rows = []
    for it in items[:limit]:
        def g(tag):
            m = re.search(r"<%s>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</%s>" % (tag, tag),
                          it, re.S)
            return _txt(m.group(1)) if m else None
        src = re.search(r"<source[^>]*>(.*?)</source>", it, re.S)
        rows.append({
            "title": g("title"),
            "link": g("link"),
            "published": g("pubDate"),
            "source": _txt(src.group(1)) if src else None,
        })
    return rows
