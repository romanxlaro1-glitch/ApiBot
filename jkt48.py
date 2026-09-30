#!/usr/bin/env python3
"""
JKT48 data from the Fandom wiki's MediaWiki API, plus Indonesian Wikipedia.

Why this exists: www.jkt48.com is behind Cloudflare and answers 403 to anything
that is not a real browser, and the wiki's HTML pages are blocked the same way.
Its ``api.php`` endpoint is not, so the whole member roster is reachable as
JSON - birth name, nickname, blood type, zodiac, height, generation, team, join
dates and social links, none of which the Wikipedia fallback carries.

Indonesian Wikipedia is queried alongside for prose context (the fandom
description is one sentence; the wiki article is a few).

Everything here is a read-only query against a public MediaWiki API.
"""

import re
import urllib.parse

FANDOM = "https://jkt48.fandom.com/api.php"
WIKI_ID = "https://id.wikipedia.org/w/api.php"

UA = "ApiBot/1.0 (public data; contact via repository)"

BOLD = "'''"          # MediaWiki bold marker
ITALIC = "''"         # MediaWiki italic marker

# The wiki spells the member template two different ways and the two versions
# do not always carry the same fields, so both are accepted.
INFOBOX_NAMES = ("Member_Infobox", "Member Infobox", "Memberinfobox")


def api_url(host, params):
    return host + "?" + urllib.parse.urlencode(params)


def category_members(fetch_json, category="Members", limit=200, offset=0,
                     host=FANDOM):
    """Every page title in a wiki category.

    ``limit`` and ``offset`` are handed to the MediaWiki API, which wants them
    as strings, so they are coerced here and callers may pass ints.
    """
    data = fetch_json(api_url(host, {
        "action": "query", "list": "categorymembers",
        "cmtitle": "Category:" + category, "cmlimit": str(limit),
        "cmoffset": str(offset), "format": "json", "formatversion": 2,
    }))
    return [p["title"] for p in data.get("query", {}).get("categorymembers", [])]


def _clean(text):
    """Strip wiki markup: links, bold, italic, refs, comments, HTML, <br>.

    <br> becomes a newline rather than a space, because the infobox uses it to
    stack multi-valued fields like the join date (trainee / member / team).
    """
    if not text:
        return ""
    s = text
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<ref[^>]*?/>", "", s)
    s = re.sub(r"<ref[^>]*?>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]+)\]\]", r"\1", s)   # internal link
    s = re.sub(r"\[https?://\S+\s+([^\]]+)\]", r"\1", s)      # labelled link
    s = re.sub(r"\[https?://\S+\]", "", s)
    s = s.replace(BOLD, "").replace(ITALIC, "")
    s = re.sub(r"\{\{[^{}]*\}\}", "", s)                       # leftover tmpl
    s = re.sub(r"\|", "\n", s)                                # leftover pipes
    s = re.sub(r"&nbsp;?", " ", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{2,}", "\n", s)
    return s.strip()


def find_template(wikitext, names):
    """Return the full ``{{Name ...}}`` block for the first name that matches.

    Brace depth is counted, so a nested template or a ``}}`` inside a link
    label does not end the match early.
    """
    for name in names:
        m = re.search(r"\{\{\s*" + re.escape(name) + r"\b", wikitext,
                      re.IGNORECASE)
        if not m:
            continue
        i = m.start()
        depth = 0
        for j in range(i, len(wikitext)):
            two = wikitext[j:j + 2]
            if two == "{{":
                depth += 1
            elif two == "}}":
                depth -= 1
                if depth == 0:
                    return wikitext[i:j + 2]
    return ""


def parse_infobox(wikitext):
    """Flatten the member infobox into a dict keyed by lowercase field.

    The ``_raw`` entry keeps the pre-clean text for every field, because link
    fields lose their URL once ``_clean`` reduces ``[url label]`` to the label.
    """
    raw = find_template(wikitext, INFOBOX_NAMES)
    if not raw:
        return {}
    body = raw[raw.index("\n") + 1:raw.rindex("}}")]
    out = {}
    original = {}
    for key, val in re.findall(
            r"(?m)^\s*\|\s*([a-zA-Z0-9 _'/-]+?)\s*=\s*(.*?)\s*$", body):
        key = key.strip().lower()
        cleaned = _clean(val)
        if cleaned and cleaned.lower() not in ("none", "n/a", "-", "unknown"):
            out[key] = cleaned
            original[key] = val.strip()
    out["_raw"] = original
    return out


def first_url(wikitext_value):
    """Recover a real URL from a wiki field that may still be raw.

    ``_clean`` has already been applied to the infobox values, which turns
    ``[https://x.com/Aralie_JKT48 @Aralie_JKT48]`` into the bare label. So this
    is a last-resort normaliser for the cases where the label itself is the
    only thing left - and for fields that kept a URL.
    """
    if not wikitext_value:
        return ""
    m = re.search(r"https?://[^\s\]\|<>]+", wikitext_value)
    return m.group(0) if m else ""


def parse_member(wikitext, title="", description=""):
    """wikitext -> a tidy member record."""
    box = parse_infobox(wikitext)
    rawbox = box.pop("_raw", {})
    # Lead paragraph, minus the infobox and any trailing section header.
    body = re.sub(r"\{\{.*?\}\}", "", wikitext, flags=re.S)
    lead = ""
    for para in body.split("\n"):
        p = _clean(para)
        if len(p) > 40 and not p.startswith("="):
            lead = p
            break
    rec = {
        "name": title or box.get("name") or box.get("stagename", ""),
        "nickname": box.get("nickname", ""),
        "birth_name": box.get("birthname", ""),
        "former_names": box.get("formername", ""),
        "born": box.get("birthdate", ""),
        "origin": box.get("origin") or box.get("birthplace", ""),
        "blood_type": box.get("bloodtype", ""),
        "zodiac": box.get("zodiac", ""),
        "height_cm": box.get("height", ""),
        "generation": box.get("generation", ""),
        "team": box.get("acts", ""),
        "joined": box.get("join", ""),
        "years_active": box.get("active", ""),
        "links": {
            "website": first_url(rawbox.get("website", "")),
            "twitter": first_url(rawbox.get("twitter", "")),
            "instagram": first_url(rawbox.get("instagram", "")),
            "threads": first_url(rawbox.get("sns", "")),
        },
        "handles": {
            "twitter": box.get("twitter", ""),
            "instagram": box.get("instagram", ""),
        },
        "description": _clean(description),
        "summary": lead,
    }
    return rec


def member_record(fetch_json, title):
    """One member, combining the wiki infobox with its one-line description."""
    data = fetch_json(api_url(FANDOM, {
        "action": "query", "titles": title, "prop": "pageprops|revisions",
        "rvprop": "content", "rvslots": "main", "format": "json",
        "formatversion": 2,
    }))
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        return None
    page = pages[0]
    rev = (page.get("revisions") or [{}])[0]
    wikitext = (rev.get("slots", {}).get("main", {}) or {}).get("content", "")
    desc = (page.get("pageprops", {}) or {}).get("fandomdescription", "")
    return parse_member(wikitext, title=page.get("title", title),
                        description=desc)


def member_batch(fetch_json, titles):
    """Several members in ONE request - the API allows 50 titles per call.

    Returns {title: record}. Much better than looping: 167 members is 4 calls
    instead of 167.
    """
    out = {}
    titles = [t for t in titles if t]
    for i in range(0, len(titles), 50):
        chunk = titles[i:i + 50]
        data = fetch_json(api_url(FANDOM, {
            "action": "query", "titles": "|".join(chunk),
            "prop": "pageprops|revisions", "rvprop": "content",
            "rvslots": "main", "format": "json", "formatversion": 2,
        }))
        for page in data.get("query", {}).get("pages", []):
            if page.get("missing"):
                continue
            rev = (page.get("revisions") or [{}])[0]
            wt = (rev.get("slots", {}).get("main", {}) or {}).get("content", "")
            desc = (page.get("pageprops", {}) or {}).get("fandomdescription", "")
            out[page.get("title", "")] = parse_member(
                wt, title=page.get("title", ""), description=desc)
    return out


def id_wikipedia_summary(fetch_json, title):
    """Indonesian Wikipedia extract, for prose the fandom one-liner lacks."""
    try:
        data = fetch_json(api_url(WIKI_ID, {
            "action": "query", "titles": title, "prop": "extracts",
            "exintro": 1, "explaintext": 1, "format": "json",
            "formatversion": 2, "redirects": 1,
        }))
    except Exception:
        return ""
    pages = data.get("query", {}).get("pages", [])
    if not pages:
        return ""
    return (pages[0].get("extract") or "").strip()


def id_wikipedia_search(fetch_json, term, limit=8):
    data = fetch_json(api_url(WIKI_ID, {
        "action": "query", "list": "search", "srsearch": term,
        "srlimit": limit, "format": "json", "formatversion": 2,
    }))
    return [{"title": h["title"], "pageid": h.get("pageid"),
             "snippet": re.sub(r"<[^>]+>", "", h.get("snippet", "")),
             "words": h.get("wordcount")}
            for h in data.get("query", {}).get("search", [])]


def roster(fetch_json, category="Members", limit=200):
    """Names only, cheap: one category query, no per-member content."""
    return category_members(fetch_json, category, limit)


def wiki_status(fetch_json):
    """Is the wiki reachable, and how big is the roster right now."""
    data = fetch_json(api_url(FANDOM, {
        "action": "query", "meta": "siteinfo", "format": "json",
        "formatversion": 2,
    }))
    gen = data.get("query", {}).get("general", {})
    return {"sitename": gen.get("sitename"), "base": gen.get("base"),
            "wikiid": gen.get("wikiid")}
