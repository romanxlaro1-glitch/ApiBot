#!/usr/bin/env python3
"""
AI tool / model registries scraped straight from the sites.

rewind.ai  - https://rewind.ai/tools/  -> 866 tool entries in 21 categories,
             of which 437 are AI models with a provider slug.  Next.js RSC
             page, but the grid is plain server-rendered HTML
             (`div.tool-item[data-name][data-cat] > a.tool-link`), so we parse
             the markup and ignore the RSC payload entirely.  One request
             gets the whole catalogue.  robots.txt is `Allow: /` and even
             names GPTBot/ClaudeBot/PerplexityBot as allowed.

chatbotchatapp.com - https://chatbotchatapp.com/  ->  a free chat UI, not a
             registry: the only structured-ish data is the model picker
             rendered as plain text next to its one-line description
             ("GPT-5  Smart and fast for everyday tasks").  We harvest that
             pair list - it is genuinely the site's model catalogue - and the
             declared capabilities/limits.  No Cloudflare, 48 sitemap URLs,
             one request.  Its robots.txt disallows /auth, /login and most
             locale prefixes; we only ever touch the root.

Neither site needs an account, a key, or a paid plan, and neither is
Cloudflare-walled for plain GETs.  rewind.ai sits behind Cloudflare (Server:
cloudflare) but serves the browser-UA request 200 with `Allow: /`; if a shared
Vercel IP ever gets challenged the endpoints surface a 502 rather than
silently returning junk.
"""

import html as _html
import re
from urllib.parse import urljoin

REWIND = "https://rewind.ai"
REWIND_TOOLS = REWIND + "/tools/"
REWIND_COMPARE = REWIND + "/compare/"
REWIND_SITEMAP = REWIND + "/sitemap.xml"
CBB = "https://chatbotchatapp.com"
CBB_ROOT = CBB + "/"

# `data-cat` values on the tools grid, mapped to a readable label.
CAT_TITLES = {
    "chat": "AI Chat", "models": "AI Models", "image": "Image",
    "write": "Writing", "code": "Code", "video": "Video", "music": "Music",
    "design": "Design", "business": "Business", "social": "Social",
    "text": "Text", "pdf": "PDF", "youtube": "YouTube", "study": "Study",
    "health": "Health", "voice": "Voice", "builder": "Builder",
    "transcribe": "Transcription", "translate": "Translation",
    "gaming": "Gaming", "search": "Search",
}

# The grid is the authoritative category list; this only labels the handful
# of slugs that do not read as a category on their own.
_PROVIDER_HINTS = (
    ("Anthropic", ("claude",)),
    ("OpenAI", ("gpt", "dall-e", "sora", "o1-", "o3-")),
    ("Google", ("gemini", "gemma", "imagen", "veo")),
    ("Meta", ("llama",)),
    ("DeepSeek", ("deepseek",)),
    ("Alibaba", ("qwen", "wan ")),
    ("Mistral", ("mistral", "magistral", "ministral", "codestral", "devstral",
                 "pixtral", "large", "small")),
    ("xAI", ("grok",)),
    ("Moonshot", ("kimi", "moonshot")),
    ("AI21", ("jamba", "ai21")),
    ("Amazon", ("nova",)),
    ("AllenAI", ("olmo",)),
    ("Cohere", ("command", "aya", "cohere")),
    ("NVIDIA", ("nemotron", "nvidia")),
    ("01.AI", ("yi-",)),
    ("TII", ("falcon",)),
    ("Baidu", ("ernie",)),
    ("ByteDance", ("doubao", "seed-", "skylark")),
    ("Reka", ("reka",)),
    ("Nomic", ("nomic",)),
    ("Upstage", ("solar",)),
    ("Writer", ("palmyra",)),
    ("Kwai", ("kwai", "kling")),
    ("Vidu", ("vidu",)),
    ("Hailuo", ("hailuo",)),
    ("Kwai Kling", ("kling",)),
    ("Sora", ("sora",)),
    ("Runway", ("runway",)),
    ("Pika", ("pika",)),
    ("Luma", ("luma",)),
    ("ElevenLabs", ("eleven",)),
    ("Cartesia", ("cartesia",)),
    ("PlayHT", ("playht",)),
    ("TTS-1", ("tts-1",)),
)


def _txt(s):
    """Collapse an HTML fragment to plain text."""
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def _provider(slug, name):
    """Best-effort provider for a model entry.

    The grid slug is authoritative when it carries a vendor prefix
    (``anthropic-claude-opus-latest``); otherwise fall back to keyword
    matching on the display name.  Returns None for tools that are not
    models at all.
    """
    s = (slug or "").lower()
    if "-" in s:
        head = s.split("-", 1)[0]
        if head in ("openai", "anthropic", "google", "meta", "deepseek",
                    "alibaba", "mistral", "xai", "moonshotai", "moonshot",
                    "ai21", "amazon", "allenai", "cohere", "nvidia",
                    "baidu", "bytedance", "reka", "nomic", "upstage",
                    "writer", "gibsonai", "perplexity", "inception",
                    "stability", "stabilityai", "luma", "elevenlabs",
                    "cartesia", "playht", "lovo", "turboscribe", "deepinfra",
                    "nexa", "arcee", "tngtech", "ibm", "sakanaai", "openglm",
                    "qwen", "zhipuai", "zlai", "stepfun", "tencent", "huawei",
                    "canopusai", "inclusionai", "ontix", "latent", "lunary",
                    "mlxai", "mrfakename", "punit", "qifeng", "vitmo",
                    "lxai", "kolors", "kijai", "lightricks", "pikaart",
                    "kwaicgi", "hume", "sarvam", "sarvamai", "kyutai",
                    "kyut", "unsloth", "sns-sam", "smolai", "inclusionai",
                    "nvidia-nim", "siliconflow", "liquid", "tngtech", "jamba",
                    "kilo", "moonshot", "nousresearch", "internlm", "qwen"):
            return head.capitalize() if head != "moonshotai" else "Moonshot"
    low = (name or "").lower()
    for prov, keys in _PROVIDER_HINTS:
        if any(k in low for k in keys):
            return prov
    return None


def parse_tools_grid(html):
    """Every ``div.tool-item`` on /tools/, grouped by its cat-section.

    Markup shape (server-rendered, stable across the site):
        <div class="cat-section mb-5" id="cat-image">
          <div ...><h2 ...>Image</h2><span class="badge ...">72</span></div>
          <div class="row g-2">
            <div class="col-6 col-md-4 col-lg-3 tool-item"
                 data-name="upscaler" data-cat="image">
              <a href="/image/upscaler/" class="tool-link">Image Upscaler</a>
    """
    out = []
    for sec in re.finditer(
            r'<div class="cat-section[^"]*"\s+id="cat-([a-z0-9\-]+)">(.*?)'
            r'(?=<div class="cat-section|\Z)', html, re.S):
        cat = sec.group(1)
        body = sec.group(2)
        tm = re.search(r"<h2[^>]*>(.*?)</h2>", body, re.S)
        title = _txt(tm.group(1)) if tm else CAT_TITLES.get(cat, cat)
        for it in re.finditer(
                r'<div class="col-6 col-md-4 col-lg-3 tool-item"\s+'
                r'data-name="([^"]*)"\s+data-cat="([^"]*)">\s*'
                r'<a href="([^"]+)"\s+class="tool-link">(.*?)</a>', body, re.S):
            slug, dcat, href, label = it.groups()
            is_model = dcat == "models" or cat == "models"
            out.append({
                "name": _txt(label),
                "url": urljoin(REWIND, href),
                "category": dcat or cat,
                "category_title": title,
                "slug": slug,
                "kind": "model" if is_model else "tool",
            })
    return out


def filter_tools(rows, category=None, kind=None, q_=None):
    """Apply the optional query-string filters to a parsed tool grid."""
    out = rows
    if category:
        c = category.lower()
        out = [r for r in out if r["category"] == c
               or r["category_title"].lower() == c]
    if kind:
        k = kind.lower()
        out = [r for r in out if r["kind"] == k]
    if q_:
        needle = q_.lower()
        out = [r for r in out
               if needle in r["name"].lower()
               or needle in r["slug"].lower()
               or needle in r["category"].lower()]
    return out


def parse_models(rows):
    """Split the grid into the model half, with provider attribution."""
    models, seen = [], set()
    for r in rows:
        if r["kind"] != "model":
            continue
        url = r["url"]
        if url in seen:
            continue
        seen.add(url)
        models.append({
            "name": r["name"],
            "provider": _provider(r["slug"], r["name"]),
            "url": url,
            "slug": r["slug"],
        })
    return models


def parse_compare_specs(html):
    """The spec table on a /compare/<a>-vs-<b>/ page.

    Real markup is a two-model table: thead carries the two model names, and
    each body row is ``<td class="text-muted">Label</td>`` followed by one
    ``<td>`` per model.  Returns ``{label, left, right}`` triples.
    """
    m = re.search(r"Specs compared(.*?)(?:Which one fits|<h2|</table>)", html,
                  re.S)
    seg = m.group(1) if m else html
    names = [_txt(x) for x in re.findall(
        r'<th[^>]*class="fw-semibold"[^>]*>(.*?)</th>', seg, re.S)]
    specs, seen = [], set()
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", seg, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 2:
            continue
        # A spec label can carry a <small> footnote ("Cost per message" +
        # "Rewind.ai tokens (estimate)"). Drop it - keep the label clean.
        label = _txt(re.sub(r"<small.*?</small>", " ", tds[0], flags=re.S))
        vals = [_txt(x) for x in tds[1:]]
        vals = (vals + [None, None])[:2]
        key = label.lower()
        if not label or key in seen:
            continue
        seen.add(key)
        specs.append({"spec": label, "left": vals[0] or None,
                      "right": vals[1] or None})
    return {"models": names[:2], "specs": specs}


def parse_compare_page(html):
    """Title, the two model names, and the spec rows of a compare page."""
    tm = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    title = _txt(tm.group(1)) if tm else None
    table = parse_compare_specs(html)
    left = right = None
    if title and " vs " in title:
        left, right = [p.strip() for p in title.split(" vs ", 1)]
    if not left and len(table["models"]) == 2:
        left, right = table["models"]
    return {"title": title, "left": left, "right": right,
            "models": table["models"], "specs": table["specs"]}


def compare_pairs(sitemap_xml, limit=0):
    """Model-vs-model compare pages listed in the sitemap."""
    out = []
    for m in re.finditer(
            r"<loc>https://rewind\.ai/compare/([a-z0-9\-]+)"
            r"-vs-([a-z0-9\-]+)/?</loc>", sitemap_xml):
        left_slug, right_slug = m.group(1), m.group(2)
        # The site also lists "X vs anti-bot" style junk pages; skip those.
        if "anti-" in left_slug or "bot-" in left_slug:
            continue
        out.append({"url": REWIND_COMPARE + left_slug + "-vs-" + right_slug + "/",
                    "left_slug": left_slug, "right_slug": right_slug})
        if limit and len(out) >= limit:
            break
    return out


def sitemap_counts(sitemap_xml):
    """How many URLs the sitemap claims, and how many per top segment."""
    import collections
    locs = re.findall(r"<loc>(https://rewind\.ai/[^<]+)</loc>", sitemap_xml)
    seg = collections.Counter()
    for l in locs:
        p = l.replace(REWIND, "").strip("/").split("/")
        seg[p[0] if len(p) > 1 else "(root)"] += 1
    return {"total": len(locs), "by_segment": dict(seg.most_common())}


# --------------------------------------------------------------------------
# chatbotchatapp.com
# --------------------------------------------------------------------------

# The model picker is plain text: "GPT-5  Smart and fast for everyday tasks",
# two spaces or a <span> between the model name and its blurb.
# The model picker is a real dropdown, not prose:
#   <li class="dropdown-item-model" id="model-gpt-5">
#     <div class="info-model">
#       <h2 class="info-model--title">GPT-5</h2>
#       <p>Smart and fast for everyday tasks</p>
# A closed lock icon means the model is gated behind the paid plan.
_CBB_ITEM = re.compile(
    r'<li class="dropdown-item-model"[^>]*id="model-([^"]+)"[^>]*>(.*?)</li>',
    re.S)
_CBB_LOCK = re.compile(r"lock-icon--(?:closed|open)")


def parse_cbb_models(html):
    """Model picker entries from the chatbotchatapp chat UI.

    One entry per ``li.dropdown-item-model``: id, display name, capability
    blurb, and whether a lock icon marks it as paid-only.  Ordered as the
    dropdown lists them.
    """
    out = []
    for m in _CBB_ITEM.finditer(html):
        body = m.group(2)
        tm = re.search(r'class="info-model--title"[^>]*>(.*?)</h2>', body, re.S)
        pm = re.search(r"<p[^>]*>(.*?)</p>", body, re.S)
        name = _txt(tm.group(1)) if tm else m.group(1).replace("-", " ")
        if not name:
            continue
        out.append({
            "name": name,
            "id": m.group(1),
            "blurb": _txt(pm.group(1)) if pm else None,
            "locked": bool(_CBB_LOCK.search(body)),
            "provider": _provider("", name),
        })
    return out


def parse_cbb_features(html):
    """Capability bullets and the free-tier limits from the chat panel."""
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.S | re.I)
    text = _txt(text)

    feats = []
    m = re.search(r"WHAT I CAN DO(.*?)(?:All Messages|Ask me something)", text,
                  re.S | re.I)
    if m:
        seg = m.group(1)
        # bullets are separated by a capital letter starting a new line
        for fm in re.finditer(
                r"(?:^|(?<=\s))([A-Z][a-z]+\s+[a-z][^.!?]{10,140}[.!?])", seg):
            feats.append(fm.group(1).strip()[:180])
    if not feats:
        for fm in re.finditer(r"(?:Explain|Generate|Analyze|Suggest|Answer)"
                              r"\s+([a-z][^.\n]{8,120})", text):
            feats.append(fm.group(1).strip()[:180])
    feats = list(dict.fromkeys(feats))

    lim = {}
    lm = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if lm:
        lim["used"], lim["limit"] = int(lm.group(1)), int(lm.group(2))
    tm = re.search(r"(\d+)\s*/\s*day", text)
    if tm:
        lim["daily"] = int(tm.group(1))
    return {"features": feats[:20], "limits": lim or None}
