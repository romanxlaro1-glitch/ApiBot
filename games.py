#!/usr/bin/env python3
"""
Gacha-game + RPG wiki endpoints (Fandom MediaWiki API).

Fandom exposes a full MediaWiki api.php on every wiki, so one small client gets
title + lead image + intro for a whole category in a SINGLE request
(generator=categorymembers). That keeps it cheap: one HTTP call per endpoint
instead of one per item.

No game is queried twice and nothing is hard-coded per game beyond the wiki
hostname and which categories are worth listing.
"""

import json
import re
import urllib.parse

# --------------------------------------------------------------------------
# Registry: slug -> (fandom host, human label, categories worth exposing)
# Only wikis verified to answer api.php with populated categories.
# --------------------------------------------------------------------------
# Registry value is (host, label, categories). When a wiki's categories are
# search TERMS instead of category names, it is listed in SEARCH_ONLY.
SEARCH_ONLY = {"fire-emblem"}

WIKIS = {
    "genshin": (
        "genshin-impact.fandom.com", "Genshin Impact",
        ["Playable Characters", "Weapons", "Enemies"]),
    "honkai-starrail": (
        "honkai-star-rail.fandom.com", "Honkai: Star Rail",
        ["Playable Characters", "Items", "Enemies"]),
    "wuthering-waves": (
        "wutheringwaves.fandom.com", "Wuthering Waves",
        ["Bosses", "Weapons", "Items", "Enemies"]),
    "arknights": (
        "arknights.fandom.com", "Arknights", ["Classes", "Items"]),
    "azur-lane": (
        "azur-lane.fandom.com", "Azur Lane", ["Maps"]),
    "blue-archive": (
        "bluearchive.fandom.com", "Blue Archive", ["Students"]),
    "limbus-company": (
        "limbuscompany.fandom.com", "Limbus Company",
        ["Characters", "Items"]),
    "guardian-tales": (
        "guardiantales.fandom.com", "Guardian Tales",
        ["Heroes", "Weapons", "Enemies", "Bosses"]),
    "alchemy-stars": (
        "alchemystars.fandom.com", "Alchemy Stars",
        ["Characters", "Bosses", "Enemies"]),
    "onmyoji": (
        "onmyoji.fandom.com", "Onmyoji",
        ["SSR", "SR", "SP", "R"]),
    "overwatch": (
        "overwatch.fandom.com", "Overwatch",
        ["Heroes", "Weapons", "Maps", "Items"]),
    "warframe": (
        "warframe.fandom.com", "Warframe", ["Weapons", "Enemies"]),
    "monster-hunter": (
        "monster-hunter.fandom.com", "Monster Hunter",
        ["Weapons", "Items", "Monsters"]),
    "elden-ring": (
        "eldenring.fandom.com", "Elden Ring",
        ["Bosses", "Enemies", "Weapons", "Maps"]),
    "terraria": (
        "terraria.fandom.com", "Terraria",
        ["Enemy NPCs", "Critter NPCs", "Items"]),
    "stardew-valley": (
        "stardewvalley.fandom.com", "Stardew Valley",
        ["Characters", "Crops", "Items"]),
    "undertale": (
        "undertale.fandom.com", "Undertale", ["Characters", "Enemies"]),
    "kingdom-hearts": (
        "kingdomhearts.fandom.com", "Kingdom Hearts", ["Bosses", "Enemies"]),
    "final-fantasy": (
        "finalfantasy.fandom.com", "Final Fantasy",
        ["Final bosses", "Locations", "Items"]),
    # Fire Emblem's wiki keeps every entry inside "List of X" index pages
    # instead of filing individual items, so Category: is empty there. Its
    # search index is populated, so this wiki is listed via search.
    "fire-emblem": (
        "fireemblem.fandom.com", "Fire Emblem",
        ["weapon", "class", "character", "item"]),
    "zenless-zone-zero": (
        "zenless-zone-zero.fandom.com", "Zenless Zone Zero",
        ["Enemies", "Items", "Characters"]),
}

# A category page itself is not a data row (e.g. "Heroes" listed inside
# Category:Heroes). These titles are structural, drop them.
_STRUCTURAL = re.compile(
    r"^(character|characters|item|items|weapon|weapons|enemy|enemies|"
    r"hero|heroes|boss|bosses|map|maps|class|classes|playable characters|"
    r"monsters|npcs|crops|ship girls|shikigami|list of .*|category.*)$",
    re.I,
)

# "Something (Disambiguation)", "X/Story", "Y (Key art)" -> keep the base name
_DISAMBIG = re.compile(r"\s*\((disambiguation|alternate|unused|legacy)\)\s*$", re.I)
_SUBSLASH = re.compile(r"/(Story|Gameplay|Traits|Quotes|History|Boss)$", re.I)


def wiki_url(host, **params):
    params.setdefault("format", "json")
    params.setdefault("formatversion", "2")
    params.setdefault("action", "query")
    return "https://%s/api.php?%s" % (host, urllib.parse.urlencode(params))


def _clean_title(title):
    t = _DISAMBIG.sub("", title or "").strip()
    t = _SUBSLASH.sub("", t)
    return t.strip()


def _is_structural(title):
    return bool(_STRUCTURAL.match(_clean_title(title)))


def parse_category_pages(payload, keep_structural=False):
    """Pull [{name, image, url, summary}] out of a generator=categorymembers query."""
    pages = (payload.get("query") or {}).get("pages") or []
    out = []
    for p in pages:
        title = _clean_title(p.get("title") or "")
        if not title or (not keep_structural and _is_structural(p.get("title") or "")):
            continue
        thumb = (p.get("thumbnail") or {}).get("source") or ""
        if thumb:
            # wikia serves 250px-wide thumbs from a deep hash path; keep the URL
            thumb = re.sub(r"/revision/latest/[^/]*", "/revision/latest", thumb)
        summary = re.sub(r"\s+", " ", (p.get("extract") or "")).strip()
        out.append({
            "name": title,
            "summary": summary[:400] or None,
            "image": thumb or None,
            "url": ("https://%s/wiki/%s"
                    % (p.get("__host", ""), urllib.parse.quote(title.replace(" ", "_")))),
        })
    return out


def parse_page(payload, host):
    """Single page: lead image + intro paragraph (first ~1200 chars)."""
    pages = (payload.get("query") or {}).get("pages") or []
    if not pages:
        return None
    p = pages[0]
    if p.get("missing"):
        return None
    summary = re.sub(r"\s+", " ", (p.get("extract") or "")).strip()
    thumb = (p.get("thumbnail") or {}).get("source") or ""
    return {
        "name": _clean_title(p.get("title") or ""),
        "summary": summary[:1200] or None,
        "image": thumb or None,
        "url": "https://%s/wiki/%s" % (host, urllib.parse.quote((p.get("title") or "").replace(" ", "_"))),
    }


def parse_categories(payload, host):
    """categoryinfo -> [{name, count, url}] for a wiki's own category list."""
    rows = []
    for c in (payload.get("query") or {}).get("categories") or []:
        title = c.get("title") or ""
        if not title.startswith("Category:"):
            continue
        rows.append({
            "name": title[len("Category:"):],
            "count": c.get("pagecount", 0),
            "url": "https://%s/wiki/%s" % (host, urllib.parse.quote(title.replace(" ", "_"))),
        })
    rows.sort(key=lambda r: -r["count"])
    return rows

# --- capability cache -------------------------------------------------------
# 19 of the 21 wikis do NOT have the TextExtracts extension. Sending
# prop="extracts|pageimages" to one of those makes MediaWiki reject the WHOLE
# prop set, so titles and thumbnails vanish too. Detect once per host, remember
# the answer, and after that it costs nothing.
_EXTRACTS_OK = {}


def supports_extracts(host, fetch_json):
    """True if this wiki has TextExtracts. Probed once, then cached."""
    if host in _EXTRACTS_OK:
        return _EXTRACTS_OK[host]
    url = wiki_url(host, titles="Main Page", prop="extracts", exintro=1,
                   explaintext=1)
    try:
        payload, _ = fetch_json(url, ttl=86400, rate_per_min=6, burst=1)
    except Exception:
        _EXTRACTS_OK[host] = False
        return False
    warn = json.dumps((payload.get("warnings") or {}))
    ok = "extracts" not in warn
    _EXTRACTS_OK[host] = ok
    return ok


def member_props(host, fetch_json, size=200):
    """prop= value safe for this host (extracts only where supported)."""
    if supports_extracts(host, fetch_json):
        return "extracts|pageimages", {"exintro": 1, "explaintext": 1}
    return "pageimages", {}


def page_props(host, fetch_json, size=400):
    """prop= value for a single-page lookup."""
    if supports_extracts(host, fetch_json):
        return "extracts|pageimages", {"exintro": 1, "explaintext": 1}
    return "pageimages", {}


def reset_capabilities():
    """Test hook: forget every probed host."""
    _EXTRACTS_OK.clear()

def list_url(host, cat, limit, prop, extra, size=200):
    """Category listing, or a search listing for wikis with empty categories."""
    if host == "fireemblem.fandom.com":
        return wiki_url(host, generator="search", gsrsearch=cat,
                        gsrnamespace=0, gsrlimit=limit, prop=prop,
                        piprop="thumbnail", pithumbsize=size, redirects=1,
                        **extra)
    return wiki_url(host, generator="categorymembers", gcmtitle="Category:" + cat,
                    gcmlimit=limit, prop=prop, piprop="thumbnail",
                    pithumbsize=size, redirects=1, **extra)
