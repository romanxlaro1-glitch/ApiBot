#!/usr/bin/env python3
"""
Source modules for ApiBot. Pure stdlib (re / json / urllib).

Each module exposes parse_* functions and register_routes(route, ...) which
registers the endpoints that call them.

Categories
  mpl     - MPL Indonesia (esports, scraped from id-mpl.com)
  mlbb    - Mobile Legends data (rosters, patches)
  jkt48   - JKT48 (news via Google News RSS, members via Wikipedia)
  anime   - anime/manga (Jikan, AniList)
  game    - Steam, Dota 2, Valorant, Pokemon, League of Legends
  misc    - trending, hacker news, cat facts, wikipedia
"""

# ==========================================================================
# shared HTML helpers
# ==========================================================================
import hashlib
import json
import os
import re
import time

import games as games_mod
import liquid as liquid_mod
import ai as ai_mod
import aiweb as aiweb_mod
import aitools as aitools_mod
import aiask as aiask_mod
import countries as country_mod
import phone as phone_mod

# Proxy pools for /ai/ask are read from the process environment only, so
# credentials never land in config.json or in a commit.
_ENV = os.environ

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
DIV_TOK = re.compile(r"<div\b|</div>")
SCRIPT_RE = re.compile(r"<(script|style)\b[\s\S]*?</\1>", re.I)


def txt(s):
    if not s:
        return ""
    return WS_RE.sub(" ", TAG_RE.sub(" ", s)).replace("&amp;", "&") \
        .replace("&nbsp;", " ").replace("&quot;", '"').replace("&#39;", "'") \
        .strip()


def balanced_div(html, start):
    """Return (inner_html, end_index) for the <div> whose open tag starts at `start`."""
    i = html.find(">", start)
    if i < 0:
        return "", len(html)
    depth, pos, inner_start, close = 1, i + 1, i + 1, len(html)
    while pos < len(html):
        m = DIV_TOK.search(html, pos)
        if not m:
            break
        if m.group(0) == "</div>":
            depth -= 1
            if depth == 0:
                close = m.start()
                break
        else:
            depth += 1
        pos = m.end()
    return html[inner_start:close], pos


def clean_html(html):
    return SCRIPT_RE.sub(" ", html)


# ==========================================================================
# MPL INDONESIA  (id-mpl.com)
# ==========================================================================
MPL_BASE = "https://id-mpl.com"
MPL_UA = {"Referer": MPL_BASE + "/"}


def _mpl(path, **kw):
    kw.setdefault("rate_per_min", 20)
    kw.setdefault("headers", MPL_UA)
    return MPL_BASE + path


def parse_mpl_schedule(html):
    """Full regular-season schedule: weeks -> days -> matches."""
    html = clean_html(html)
    weeks = []
    for m in re.finditer(r'<div id="t-week-(\d+)">', html):
        inner, _ = balanced_div(html, m.start())
        weeks.append({
            "week": int(m.group(1)),
            "matches": _mpl_week(inner),
        })
    return weeks


def _mpl_week(body):
    head = re.compile(r'<div class="match (date|position-relative)[^"]*">')
    out, cur_date, pos = [], None, 0
    while pos < len(body):
        m = head.search(body, pos)
        if not m:
            break
        inner, pos = balanced_div(body, m.start())
        if m.group(1) == "date":
            cur_date = txt(inner)
        else:
            mm = _mpl_match(inner)
            if mm:
                mm["date_id"] = cur_date
                out.append(mm)
    return out


ID_MONTHS = {
    "Januari": 1, "Februari": 2, "Maret": 3, "April": 4, "Mei": 5, "Juni": 6,
    "Juli": 7, "Agustus": 8, "September": 9, "Oktober": 10, "November": 11,
    "Desember": 12,
}
ID_DAYS = {"Senin": 0, "Selasa": 1, "Rabu": 2, "Kamis": 3, "Jumat": 4,
           "Sabtu": 5, "Minggu": 6}


def _mpl_date_id(s):
    """'Jumat, 14 Agustus 2026' -> {'date':'2026-08-14','day':'Jumat','text':..}"""
    if not s:
        return None
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", s)
    if not m:
        return {"text": s}
    d, mon, y = int(m.group(1)), m.group(2), int(m.group(3))
    mi = ID_MONTHS.get(mon)
    return {
        "date": "%04d-%02d-%02d" % (y, mi, d) if mi else None,
        "month_id": mon,
        "text": s,
    }


def _mpl_match(b):
    t1 = re.search(r'class="team team1.*?class="name">\s*(.*?)\s*</div>', b, re.S)
    t2 = re.search(r'class="team team2.*?class="name">\s*(.*?)\s*</div>', b, re.S)
    if not (t1 and t2):
        return None
    sc = re.findall(r'class="score font-primary">\s*(\d+)\s*</div>', b)
    tm = re.search(r'letter-spacing: 1px;[^>]*>\s*(\d{1,2}:[0-9]{2})\s*<', b)
    mid = re.search(r'openMatchDetail\((\d+)\)', b)
    rep = re.search(r'class="button-watch replay[^"]*"\s+href="([^"]+)"', b)
    lg1 = re.search(r'class="team team1.*?src="([^"]+)"', b, re.S)
    lg2 = re.search(r'class="team team2.*?src="([^"]+)"', b, re.S)
    cal = re.search(r'google\.com/calendar/render\?action=TEMPLATE&amp;dates=(\d{8})T(\d{6})&amp;ctz=(\w+)&amp;text=([^&]+)', b)
    o = {"home": txt(t1.group(1)), "away": txt(t2.group(1))}
    if len(sc) >= 2:
        o["home_score"] = int(sc[0])
        o["away_score"] = int(sc[1])
    if tm:
        o["time_wib"] = tm.group(1)
    if mid:
        o["match_id"] = int(mid.group(1))
    if rep:
        o["replay_url"] = rep.group(1)
    if lg1:
        o["home_logo"] = lg1.group(1)
    if lg2:
        o["away_logo"] = lg2.group(1)
    if cal:
        o["start_utc"] = cal.group(1) + cal.group(2)
        o["tz"] = cal.group(3)
        o["match_title"] = cal.group(4).replace("+", " ")
    o["played"] = bool(rep)
    return o


def parse_mpl_standings(html, which="regular-season"):
    a = html.find('id="standing-%s"' % which)
    if a < 0:
        return []
    start = html.rfind("<div", 0, a)
    inner, _ = balanced_div(html, start)
    rows = []
    for rm in re.finditer(r"<tr[^>]*>(.*?)</tr>", inner, re.S):
        r = rm.group(1)
        if "team-info" not in r:
            continue
        rank = re.search(r'class="team-rank[^"]*">\s*(\d+)', r)
        nm = re.search(r'class="team-name"[^>]*>(.*?)</div>\s*</div>', r, re.S)
        cells = [txt(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        long = None
        if nm:
            sp = re.findall(r"<span[^>]*>(.*?)</span>", nm.group(1), re.S)
            long = txt(sp[-1]) if sp else None
        code = None
        for c in cells:
            m = re.match(r"^\s*(\d+)\s+([A-Z][A-Z0-9_ ]{1,14})$", c)
            if m:
                code = m.group(2).strip()
                break
        rows.append({
            "rank": int(rank.group(1)) if rank else None,
            "team_code": code,
            "team": long or (cells[0] if cells else None),
            "match_point": _num(cells[1]) if len(cells) > 1 else None,
            "match_wl": cells[2] if len(cells) > 2 else None,
            "game_win_rate": cells[3] if len(cells) > 3 else None,
            "game_wl": cells[5] if len(cells) > 5 else None,
            "raw": cells,
        })
    return rows


def _num(s):
    if not s:
        return None
    try:
        return int(re.sub(r"[^\d-]", "", s))
    except ValueError:
        return None


def parse_mpl_teams(html):
    out = []
    for m in re.finditer(
        r'<a href="[^"]*/team/([a-z0-9\-]+)">\s*<div class="team-card-frame">(.*?)</div>\s*</div>\s*<div class="team-name">(.*?)</div>\s*</div>',
        html, re.S):
        blk = m.group(2)
        logo = re.search(r'<img src="([^"]+)"', blk)
        name = re.search(r'<div class="d-flex[^"]*"[^>]*>\s*([^<]+)', m.group(3))
        inner = re.sub(r"<[^>]+>", " ", m.group(3))
        names = [txt(p) for p in re.split(r"</?div[^>]*>", m.group(3)) if txt(p)]
        out.append({
            "slug": m.group(1),
            "name": (names[0] if names else m.group(1)).upper(),
            "full_name": (names[1] if len(names) > 1 else None),
            "logo": logo.group(1) if logo else None,
        })
    return out


def parse_mpl_team_page(html, slug):
    """Roster + per-team match history from a /team/<slug> page."""
    html = clean_html(html)
    name = None
    mt = re.search(r'<div class="player-name"[^>]*>\s*(.*?)\s*</div>\s*<div class="player-role', html)
    title = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    if title:
        name = txt(title.group(1)).upper()
    # roster
    roster = []
    for m in re.finditer(
        r'<div class="player-image">\s*<div class="player-image-bg[^"]*">\s*<img src="([^"]+)"[^>]*alt="([^"]*)"[^>]*>\s*</div>\s*</div>\s*<div class="player-name">\s*(.*?)\s*</div>\s*<div class="player-role[^"]*">\s*(.*?)\s*</div>',
        html, re.S):
        roster.append({
            "nickname": txt(m.group(3)),
            "role": txt(m.group(4)),
            "img_alt": m.group(2) or None,
        })
    season = re.search(r'ROSTER\s+(SEASON\s+\d+)', html)
    # match history: "AE 0 - 2 ONIC Week 1 16 Agt - 20:00 WIN"
    hist = []
    idm = {"Agt": "Aug"}
    for m in re.finditer(
        r'([A-Z][A-Z0-9_]{1,9})\s+(\d+)\s*-\s*(\d+)\s+([A-Z][A-Z0-9_]{1,9})\s+Week\s+(\d+)\s+(\d{1,2})\s+(\w{3})\s*-\s*([\d:]+)(?:\s+(WIN|LOSE))?',
        html):
        opp, hs, as_, opp2, wk, dd, mon, tm, res = m.groups()
        hist.append({
            "opponent": opp if opp != opp2 else opp2,
            "self_score": int(hs) if opp != opp2 else int(as_),
            "opp_score": int(as_) if opp != opp2 else int(hs),
            "week": int(wk),
            "day": "%d %s" % (int(dd), idm.get(mon, mon)),
            "time_wib": tm,
            "result": res,
        })
    return {
        "team": name or slug.upper(),
        "slug": slug,
        "season": season.group(1) if season else None,
        "roster": roster,
        "matches": hist,
    }


def parse_mpl_detail(html):
    """match-detail/<id>: series score + per-game player stats."""
    html = clean_html(html)
    out = {"games": []}
    # The series score lives in a multi-line style block, so match the whole
    # div and read its text - a strict `style="...;"` regex never matches.
    sc = []
    for m in re.finditer(
            r'<div style="\s*font-size:\s*3rem;\s*font-weight:\s*800;[^"]*">\s*(\d+)\s*</div>',
            html):
        sc.append(int(m.group(1)))
    if len(sc) >= 2:
        out["home_score"] = sc[0]
        out["away_score"] = sc[1]
    tl = re.findall(r'class="team-logo"[^>]*>\s*<img src="([^"]+)"[^>]*alt="([^"]+)"', html)
    if len(tl) >= 2:
        out["home"], out["away"] = tl[0][1], tl[1][1]
        out["home_logo"], out["away_logo"] = tl[0][0], tl[1][0]
    for gid, gnum in re.findall(r'<a href="#(info-\d+)"[^>]*>\s*GAME (\d+)', html):
        a = html.find('id="%s"' % gid)
        if a < 0:
            continue
        s = html.rfind("<div", 0, a)
        inner, _ = balanced_div(html, s)
        out["games"].append(_mpl_game(inner, int(gnum)))
    return out


GAME_HEADER = re.compile(
    r'class="text-center position-relative mb-2 (victory|defeat)')
GAME_ROW = re.compile(
    r'class="d-flex flex-column flex-lg-row justify-content-between'
    r' align-items-center align-items-lg-start my-3"')
HERO_IMG = re.compile(r'<div class="me-1">\s*<img src="([^"]+)"\s*alt="([^"]*)"')
STAT_CELL = re.compile(
    r'<div class="px-0 text-end">\s*([\d.,]+)\s*<img src="[^"]*?icons/([a-z0-9\-]+)')
GAME_SIDE = re.compile(
    r'class="text-center position-relative mb-2\s+(\w+)\s*"\s*>')


def _mpl_game(g, num):
    o = {"game": num, "players": [], "sides": []}
    # Each side of the score header puts its kill count on a different side of
    # the sword icon (left: before, right: after), so read each side block
    # independently instead of assuming a global order.
    sides = [m.start() for m in GAME_SIDE.finditer(g)]
    for i, st in enumerate(sides):
        end = sides[i + 1] if i + 1 < len(sides) else min(st + 2000, len(g))
        blk = g[st:end]
        win = GAME_SIDE.match(g, st)
        team = re.search(r'class="team-logo">\s*<img src="[^"]*"\s*alt="([^"]*)"', blk)
        side = {"result": win.group(1) if win else None,
                "team": team.group(1) if team else None}
        after = re.search(r'icons/swords-64-v2\.png"[^>]*>\s*([\d,]+)', blk)
        before = re.search(r'>\s*([\d,]+)\s*<img src="[^"]*icons/swords-64-v2\.png"', blk)
        kill = after or before
        if kill:
            side["kills"] = int(kill.group(1).replace(",", ""))
        o["sides"].append(side)
    if len(o["sides"]) >= 2:
        o["left"], o["right"] = o["sides"][0], o["sides"][1]
        o["left_kills"] = o["sides"][0].get("kills")
        o["right_kills"] = o["sides"][1].get("kills")
    dur = re.search(r'icons/clock-64\.png"[^>]*>\s*(\d{1,2}:[0-9]{2})', g)
    if dur:
        o["duration"] = dur.group(1)

    # Players live in two col-6 team columns. A row can legitimately have no
    # hero image (the losing side renders KDA 0/0/0), so the row is delimited
    # by the NEXT row start and its side is decided by column position.
    col_starts = [m.start() for m in re.finditer(r'class="col-6 ', g)]
    starts = [m.start() for m in GAME_ROW.finditer(g)]
    for i, st in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(g)
        side = "right" if col_starts and st > col_starts[-1] else "left"
        p = _mpl_player(g[st:end], side)
        if p:
            o["players"].append(p)
    o["player_count"] = len(o["players"])
    return o


NICK_RE = re.compile(r'font-size:\s*1\.1rem;[^>]*>\s*([^<]+?)\s*</div>')


def _mpl_player(blk, side="left"):
    nick = NICK_RE.search(blk)
    if not nick:
        return None
    hero = HERO_IMG.search(blk)
    kda = re.search(r'class="kda-content">\s*([\d/]+)\s*</div>', blk)
    emblem = re.search(r'ember/(\d+)\.png"[^>]*alt="([^"]*)"', blk)
    # stat cells carry their own icon name -> map instead of trusting order
    stats = {}
    for val, icon in STAT_CELL.findall(blk):
        key = ("gold" if icon.startswith("money")
               else "damage" if icon.startswith("sword")
               else "tower_damage" if icon.startswith("tower")
               else "team_gold_diff" if icon.startswith("shield")
               else icon)
        stats[key] = val
    items = re.findall(
        r'<img src="[^"]*?/equipment/(\d+)\.png[^"]*"\s*alt="(\d+)"', blk)
    runes = re.findall(r'<img src="[^"]*?/rune/(\d+)\.png', blk)
    p = {"nickname": txt(nick.group(1)), "side": side,
         "kda": kda.group(1) if kda else None}
    if hero:
        p["hero"] = hero.group(2) or None
        hm = re.search(r"/(\d+)\.png", hero.group(1))
        p["hero_id"] = int(hm.group(1)) if hm else None
    if emblem:
        p["emblem_id"] = int(emblem.group(1))
        p["emblem"] = emblem.group(2) or None
    for k in ("gold", "damage", "tower_damage", "team_gold_diff"):
        if k in stats:
            p[k] = stats[k]
    p["items"] = [{"id": int(i), "name": n} for i, n in items]
    if runes:
        p["runes"] = [int(r) for r in runes]
    return p


# ==========================================================================
# anime  (Jikan = MyAnimeList proxy, AniList = GraphQL)
# ==========================================================================
JIKAN = "https://api.jikan.moe/v4"
ANILIST = "https://graphql.anilist.co"

ANILIST_QUERY = """
query ($search: String, $type: MediaType, $page: Int, $perPage: Int, $id: Int) {
  Page(page: $page, perPage: $perPage) {
    media(search: $search, type: $type, id: $id) {
      id
      idMal
      title { romaji english native }
      description(asHtml: false)
      episodes
      duration
      status
      season
      seasonYear
      format
      genres
      averageScore
      popularity
      coverImage { extraLarge large color }
      bannerImage
      siteUrl
      studios(isMain: true) { nodes { name } }
      startDate { year month day }
    }
  }
}
"""


def _anlist_to_json(data):
    media = (data or {}).get("data", {}).get("Page", {}).get("media")
    if not media:
        return None
    m = media[0] if isinstance(media, list) else media
    return {
        "anilist_id": m.get("id"),
        "mal_id": m.get("idMal"),
        "title": m.get("title"),
        "description": m.get("description"),
        "episodes": m.get("episodes"),
        "duration": m.get("duration"),
        "status": m.get("status"),
        "season": m.get("season"),
        "year": m.get("seasonYear"),
        "format": m.get("format"),
        "genres": m.get("genres") or [],
        "score": m.get("averageScore"),
        "popularity": m.get("popularity"),
        "cover": (m.get("coverImage") or {}).get("extraLarge")
        or (m.get("coverImage") or {}).get("large"),
        "banner": m.get("bannerImage"),
        "url": m.get("siteUrl"),
        "studio": ((m.get("studios") or {}).get("nodes") or [{}])[0].get("name"),
        "start_date": m.get("startDate"),
    }


# ==========================================================================
# JKT48  (official site is Cloudflare-walled -> Google News RSS + Wikipedia)
# ==========================================================================
GNEWS = "https://news.google.com/rss/search"
GNEWS_PARAMS = "&hl=id&gl=ID&ceid=ID:id"


def parse_gnews(xml, limit=50):
    items = re.findall(r"<item>(.*?)</item>", xml, re.S)
    out = []
    for it in items[:limit]:
        def g(tag):
            m = re.search(r"<%s[^>]*>(.*?)</%s>" % (tag, tag), it, re.S)
            return txt(m.group(1)) if m else None
        src = re.search(r"<source[^>]*>(.*?)</source>", it, re.S)
        out.append({
            "title": g("title"),
            "link": g("link"),
            "pub_date": g("pubDate"),
            "description": g("description"),
            "source": txt(src.group(1)) if src else None,
            "guid": g("guid"),
        })
    return out


# ==========================================================================
# wikipedia  (JKT48 members, MLBB, general)
# ==========================================================================
WIKI = "https://id.wikipedia.org/w/api.php"
WIKI_EN = "https://en.wikipedia.org/w/api.php"


def parse_wiki_search(data, limit=10):
    res = (data.get("query") or {}).get("search") or []
    out = []
    for r in res[:limit]:
        out.append({
            "title": r.get("title"),
            "pageid": r.get("pageid"),
            "snippet": re.sub(r"<[^>]+>", "", r.get("snippet") or ""),
            "wordcount": r.get("wordcount"),
        })
    return out


def parse_wiki_summary(data):
    return {
        "title": data.get("title"),
        "description": data.get("description"),
        "extract": data.get("extract"),
        "thumbnail": (data.get("thumbnail") or {}).get("source"),
        "url": (data.get("content_urls") or {}).get("desktop", {}).get("page"),
    }


# ==========================================================================
# misc JSON APIs (already JSON -> passthrough + light shaping)
# ==========================================================================
def _passthrough(obj, keys=None):
    if keys:
        return {k: obj.get(k) for k in keys if k in obj}
    return obj


# ==========================================================================
# route registration
# ==========================================================================
# --- MLBB Fandom helpers ---------------------------------------------------
MLBB_LIST_URL = ("https://mobile-legends.fandom.com/api.php?action=parse"
                 "&page=List_of_heroes&prop=text&format=json")
MLBB_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
MLBB_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)


def _mlbb_hero_table(html):
    """Live hero table -> [{name, title, order, roles, specialties, lanes,
    release_date}]. Columns: [_, icon, "Name, the Title", order, roles,
    specialty, lane, region, price, release]."""
    out = []
    for rm in MLBB_ROW.finditer(html):
        cells = []
        for cm in MLBB_CELL.finditer(rm.group(1)):
            raw = cm.group(1)
            href = re.search(r'href="/wiki/([^"#]+)"', raw)
            cells.append((txt(raw), href.group(1) if href else None))
        if len(cells) < 7:
            continue
        label = cells[2][0]
        if not label or label in ("Hero",) or not label[0].isalpha():
            continue
        name = label.split(",")[0].strip()
        if not name or name in ("Icon", "Hero order"):
            continue
        rel = cells[9][0] if len(cells) > 9 else None
        # a bare year means the wiki never published an exact date
        out.append({
            "name": name,
            "title": label.split(",", 1)[1].strip() if "," in label else None,
            "order": _num(cells[3][0]),
            "roles": [x.strip() for x in cells[4][0].split("/") if x.strip()],
            "specialties": [x.strip() for x in cells[5][0].split("/") if x.strip()],
            "lanes": [x.strip() for x in cells[6][0].split("/") if x.strip()],
            "region": cells[7][0] if len(cells) > 7 else None,
            "release_date": rel,
            "release_year": int(rel) if rel and rel.isdigit() else None,
        })
    return out


def _mlbb_hero_parse(wikitext):
    """Pull the plain fields out of a hero page's wikitext."""
    def field(key):
        m = re.search(r"\|\s*%s\s*=\s*(.*?)(?=\n\||\n\}\}|\Z)" % key,
                      wikitext, re.S)
        if not m:
            return None
        val = re.sub(r"<ref[^>]*>.*?</ref>", "", m.group(1), flags=re.S)
        val = re.sub(r"<!--.*?-->", "", val, flags=re.S)
        val = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", val)
        val = re.sub(r"\[\[([^\]]+)\]\]", r"\1", val)
        val = re.sub(r"\{\{[^}]*\}\}", "", val)
        val = re.sub(r"^[\*#:]+", "", val, flags=re.M)
        return txt(val)

    stats = {}
    sm = re.search(r"\{\{Hero stats(.*?)\}\}", wikitext, re.S)
    if sm:
        for k, v in re.findall(r"\|\s*([a-z_ ]+)\s*=\s*([^|\n]+)", sm.group(1)):
            stats[k.strip()] = txt(v)

    story = None
    sm2 = re.search(r"==\s*Story\s*==(.*?)(?=\n==[^=]|\Z)", wikitext, re.S)
    if sm2:
        story = txt(sm2.group(1))[:1500] or None

    return {
        "full_name": field("full_name"),
        "title": field("title") or field("alias"),
        "role": field("role"),
        "specialty": field("specialty"),
        "lane": field("lane"),
        "damage_type": field("damage_type"),
        "resource": field("resource"),
        "birthday": field("birthday"),
        "origin": field("origin"),
        "age": field("age"),
        "gender": field("gender"),
        "species": field("species"),
        "stats": stats or None,
        "story": story,
    }


def register_routes(route, fetch, fetch_json, UpstreamError, CACHE, cfg):
    long = cfg["cache_ttl_long"]
    med = cfg["cache_ttl_default"]

    def q(query, key, default=None, required=False):
        v = (query.get(key) or [default])[0]
        if required and (v is None or v == ""):
            raise UpstreamError("missing required query param: %s" % key, 400)
        if isinstance(v, str):
            v = v.strip()
        return v if v not in (None, "") else default

    def nq(query, key, default, lo, hi):
        v = q(query, key)
        if v is None:
            return default
        try:
            return max(lo, min(hi, int(v)))
        except ValueError:
            return default

    # ---------------------------------------------------------------- MPL
    @route("GET", r"/api/v1/mpl/schedule")
    def mpl_schedule(h, m, query):
        """Full MPL Indonesia regular-season schedule (weeks, dates, scores, replay links)."""
        html, _ = fetch(_mpl("/schedule"), ttl=med, cache_key="mpl|schedule")
        weeks = parse_mpl_schedule(html)
        flat = [x for w in weeks for x in w["matches"]]
        for x in flat:
            x["date"] = _mpl_date_id(x.pop("date_id", None))
        want = q(query, "team")
        if want:
            want = want.upper()
            flat = [x for x in flat
                    if x["home"] == want or x["away"] == want]
        return {
            "source": "id-mpl.com",
            "season": _mpl_season(html),
            "count": len(flat),
            "matches": flat,
        }

    @route("GET", r"/api/v1/mpl/standings")
    def mpl_standings(h, m, query):
        """MPL Indonesia standings table (regular season or playoffs)."""
        which = q(query, "phase", "regular-season")
        if which not in ("regular-season", "playoffs"):
            raise UpstreamError("phase must be regular-season or playoffs", 400)
        html, _ = fetch(_mpl("/schedule"), ttl=med, cache_key="mpl|schedule")
        rows = parse_mpl_standings(html, which)
        return {"source": "id-mpl.com", "phase": which, "count": len(rows),
                "standings": rows}

    @route("GET", r"/api/v1/mpl/teams")
    def mpl_teams(h, m, query):
        """All MPL Indonesia teams with logo and full name."""
        html, _ = fetch(_mpl("/teams"), ttl=long, cache_key="mpl|teams")
        teams = parse_mpl_teams(html)
        return {"source": "id-mpl.com", "count": len(teams), "teams": teams}

    @route("GET", r"/api/v1/mpl/team/(?P<slug>[a-z0-9\-]+)")
    def mpl_team(h, m, query):
        """One team: roster (nickname, role) + full match history."""
        slug = m.group("slug")
        html, _ = fetch(_mpl("/team/" + slug), ttl=long,
                        cache_key="mpl|team|" + slug)
        return {"source": "id-mpl.com",
                **parse_mpl_team_page(html, slug)}

    @route("GET", r"/api/v1/mpl/match/(?P<mid>\d+)")
    def mpl_match(h, m, query):
        """Match detail: series score, per-game kills, per-player KDA / gold / items / runes."""
        mid = m.group("mid")
        html, _ = fetch(_mpl("/match-detail/" + mid), ttl=med,
                        cache_key="mpl|md|" + mid)
        d = parse_mpl_detail(html)
        d["source"] = "id-mpl.com"
        d["match_id"] = int(mid)
        return d

    # -------------------------------------------------------------- MLBB-ish

    # MLBB: the third-party JSON APIs are dead (402) and the official site
    # ships no JSON, so this reads the Fandom MediaWiki API table.

    MLBB_TABLE_URL = ("https://mobile-legends.fandom.com/api.php?action=parse"
                      "&page=List_of_heroes&prop=text&format=json")

    @route("GET", r"/api/v1/mlbb/heroes")
    def mlbb_heroes(h, m, query):
        """All Mobile Legends heroes: title, roles, specialties, lanes, release. ?role=Marksman|Tank|..."""
        role = q(query, "role", "")
        data, _ = fetch_json(MLBB_TABLE_URL, ttl=long, rate_per_min=40, burst=3)
        html = (data.get("parse") or {}).get("text", {}).get("*") or ""
        heroes = _mlbb_hero_table(html)
        if not heroes:
            raise UpstreamError("could not read the MLBB hero table", 502)
        if role:
            heroes = [x for x in heroes
                      if role.lower() in [r.lower() for r in x.get("roles") or []]]
        return {"source": "mobile-legends.fandom.com", "count": len(heroes),
                "roles": sorted({r for x in heroes for r in (x.get("roles") or [])}),
                "results": heroes}

    @route("GET", r"/api/v1/mlbb/hero/(?P<name>[\w\s\-']+)")
    def mlbb_hero(h, m, query):
        """One MLBB hero: roles/lanes/release from the live table plus infobox lore."""
        name = txt(m.group("name"))
        if not name:
            raise UpstreamError("hero name required", 400)
        table, _ = fetch_json(MLBB_TABLE_URL, ttl=long, rate_per_min=40, burst=3)
        html = (table.get("parse") or {}).get("text", {}).get("*") or ""
        row = _mlbb_hero_table(html)
        match = next((x for x in row
                      if x["name"].lower() == name.lower()
                      or name.lower() in x["name"].lower()), None)
        url = ("https://mobile-legends.fandom.com/api.php?action=parse&page=%s"
               "&prop=wikitext&format=json" % _qp((match["name"] if match else name).replace(" ", "_")))
        try:
            data, _ = fetch_json(url, ttl=long, rate_per_min=40, burst=3)
            wt = ((data.get("parse") or {}).get("wikitext") or {}).get("*")
        except UpstreamError:
            wt = None
        if not wt and not match:
            raise UpstreamError("MLBB hero not found: %s" % name, 404)
        out = {"source": "mobile-legends.fandom.com", "name": name}
        if match:
            out.update({k: v for k, v in match.items() if k != "name"})
        if wt:
            out.update({k: v for k, v in _mlbb_hero_parse(wt).items() if v})
        out["url"] = "https://mobile-legends.fandom.com/wiki/" + name.replace(" ", "_")
        return out

    # ---------------------------------------------------------------- JKT48
    @route("GET", r"/api/v1/jkt48/news")
    def jkt48_news(h, m, query):
        """JKT48 news (Google News RSS aggregator, newest first)."""
        term = q(query, "q", "JKT48")
        limit = nq(query, "limit", 30, 1, 100)
        url = "%s?q=%s%s" % (GNEWS, _qp(term), GNEWS_PARAMS)
        xml, _ = fetch(url, ttl=180, rate_per_min=30, burst=4)
        return {"query": term, "count": len(parse_gnews(xml, limit)),
                "news": parse_gnews(xml, limit),
                "note": "aggregated from Google News RSS; official site is Cloudflare-protected"}

    @route("GET", r"/api/v1/jkt48/member/(?P<name>[\w\s\-]{2,40})")
    def jkt48_member(h, m, query):
        """JKT48 member page summary from Wikipedia (name, extract, photo)."""
        name = m.group("name").replace("_", " ").strip()
        url = ("https://id.wikipedia.org/api/rest_v1/page/summary/" +
               _qp(name.replace(" ", "_")))
        data, _ = fetch_json(url, ttl=long, rate_per_min=30)
        if not data.get("title"):
            raise UpstreamError("member not found on Wikipedia: %s" % name, 404)
        return {"source": "id.wikipedia.org", **parse_wiki_summary(data)}

    @route("GET", r"/api/v1/jkt48/members")
    def jkt48_members(h, m, query):
        """Search Wikipedia for JKT48 members / generation references."""
        term = q(query, "q", "JKT48")
        limit = nq(query, "limit", 10, 1, 50)
        url = ("%s?action=query&list=search&srsearch=%s&srlimit=%d&format=json"
               % (WIKI, _qp(term), limit))
        data, _ = fetch_json(url, ttl=med, rate_per_min=30)
        return {"query": term, "count": len(parse_wiki_search(data, limit)),
                "results": parse_wiki_search(data, limit)}

    # ---------------------------------------------------------------- anime
    @route("GET", r"/api/v1/anime/search")
    def anime_search(h, m, query):
        """Search anime by title (AniList GraphQL). ?q=one piece"""
        term = q(query, "q", required=True)
        page = nq(query, "page", 1, 1, 5)
        gql = ANILIST_QUERY.replace(
            "($search: String, $type: MediaType, $page: Int, $perPage: Int, $id: Int)",
            "($search: String, $type: MediaType, $page: Int, $perPage: Int)",
        ).replace("media(search: $search, type: $type, id: $id)",
                  "media(search: $search, type: $type, sort: SEARCH_MATCH)")
        body = json.dumps({"query": gql,
                           "variables": {"search": term, "type": "ANIME",
                                         "page": page, "perPage": 10}}).encode()
        data, _ = fetch_json(ANILIST, ttl=med, method="POST", data=body,
                             rate_per_min=40, burst=2, cache_key="anl|search|" + term)
        return {"query": term, "results": [_anlist_to_json(data)]}

    @route("GET", r"/api/v1/anime/(?P<aid>\d+)")
    def anime_detail(h, m, query):
        """Anime detail by AniList id. /api/v1/anime/21 (One Piece)"""
        aid = m.group("aid")
        body = json.dumps({
            "query": (
                "query ($id: Int) {"
                " Media(id: $id) {"
                "  id idMal"
                "  title { romaji english native }"
                "  description(asHtml: false)"
                "  episodes duration status season seasonYear format genres"
                "  averageScore popularity"
                "  coverImage { extraLarge large color }"
                "  bannerImage siteUrl"
                "  studios(isMain: true) { nodes { name } }"
                "  startDate { year month day }"
                " }"
                "}"
            ),
            "variables": {"id": int(aid)},
        }).encode()
        data, _ = fetch_json(ANILIST, ttl=long, method="POST", data=body,
                             rate_per_min=40, burst=2, cache_key="anl|id|" + aid)
        med_ = (data.get("data") or {}).get("Media")
        if not med_:
            raise UpstreamError("anime id not found: %s" % aid, 404)
        return {
            "anilist_id": med_["id"], "mal_id": med_.get("idMal"),
            "title": med_["title"], "description": med_.get("description"),
            "episodes": med_.get("episodes"), "duration": med_.get("duration"),
            "status": med_.get("status"), "season": med_.get("season"),
            "year": med_.get("seasonYear"), "format": med_.get("format"),
            "genres": med_.get("genres") or [],
            "score": med_.get("averageScore"),
            "popularity": med_.get("popularity"),
            "cover": (med_.get("coverImage") or {}).get("extraLarge"),
            "banner": med_.get("bannerImage"), "url": med_.get("siteUrl"),
            "studio": ((med_.get("studios") or {}).get("nodes") or [{}])[0].get("name"),
            "start_date": med_.get("startDate"),
        }

    @route("GET", r"/api/v1/anime/trending")
    def anime_trending(h, m, query):
        """Currently-airing anime (AniList)."""
        body = json.dumps({
            "query": "query($page:Int,$perPage:Int){Page(page:$page,perPage:$perPage){pageInfo{hasNextPage} media(type:ANIME,status:RELEASING,sort:TRENDING_DESC){id title{romaji english} coverImage{extraLarge} averageScore episodes seasonYear genres}}}",
            "variables": {"page": 1, "perPage": nq(query, "limit", 20, 1, 50)},
        }).encode()
        data, _ = fetch_json(ANILIST, ttl=180, method="POST", data=body,
                             rate_per_min=40, burst=2, cache_key="anl|trending")
        media = data.get("data", {}).get("Page", {}).get("media") or []
        return {"count": len(media),
                "results": [{
                    "anilist_id": x["id"],
                    "title": x["title"],
                    "cover": (x.get("coverImage") or {}).get("extraLarge"),
                    "score": x.get("averageScore"),
                    "episodes": x.get("episodes"),
                    "year": x.get("seasonYear"),
                    "genres": x.get("genres"),
                } for x in media]}

    @route("GET", r"/api/v1/manga/search")
    def manga_search(h, m, query):
        """Search manga by title (AniList). ?q=naruto"""
        term = q(query, "q", required=True)
        body = json.dumps({
            "query": "query($s:String,$p:Int){Page(page:$p,perPage:10){media(search:$s,type:MANGA,sort:SEARCH_MATCH){id title{romaji english} coverImage{extraLarge} averageScore chapters status}}}",
            "variables": {"s": term, "p": 1},
        }).encode()
        data, _ = fetch_json(ANILIST, ttl=med, method="POST", data=body,
                             rate_per_min=40, burst=2, cache_key="anl|manga|" + term)
        media = data.get("data", {}).get("Page", {}).get("media") or []
        return {"query": term, "count": len(media), "results": [{
            "anilist_id": x["id"], "title": x["title"],
            "cover": (x.get("coverImage") or {}).get("extraLarge"),
            "score": x.get("averageScore"),
            "chapters": x.get("chapters"), "status": x.get("status"),
        } for x in media]}

    @route("GET", r"/api/v1/jikan/anime/(?P<aid>\d+)")
    def jikan_anime(h, m, query):
        """Full MyAnimeList record via Jikan: /api/v1/jikan/anime/16498 (One Piece). Falls back to AniList when Jikan is down."""
        aid = m.group("aid")
        try:
            data, _ = fetch_json("%s/anime/%s/full" % (JIKAN, aid), ttl=long,
                                 rate_per_min=45, burst=3)
            return {"source": "myanimelist.net (via Jikan)", **data}
        except UpstreamError:
            pass  # Jikan mirrors MAL and goes down often - AniList always answers
        body = json.dumps({
            "query": (
                "query ($id: Int) {"
                " Media(idMal: $id) {"
                "  id idMal title { romaji english native }"
                "  description(asHtml: false) episodes duration status"
                "  season seasonYear format genres averageScore popularity"
                "  coverImage { extraLarge large } bannerImage siteUrl"
                "  studios(isMain: true) { nodes { name } }"
                "  startDate { year month day } endDate { year month day }"
                " }"
                "}"
            ),
            "variables": {"id": int(aid)},
        }).encode()
        data, _ = fetch_json(ANILIST, ttl=long, method="POST", data=body,
                             rate_per_min=40, burst=2, cache_key="anl|mal|" + aid)
        med_ = (data.get("data") or {}).get("Media")
        if not med_:
            raise UpstreamError("anime mal_id not found: %s" % aid, 404)
        return {
            "source": "myanimelist.net (via AniList mirror - Jikan unavailable)",
            "mal_id": med_.get("idMal"), "anilist_id": med_.get("id"),
            "title": med_["title"], "description": med_.get("description"),
            "episodes": med_.get("episodes"), "duration": med_.get("duration"),
            "status": med_.get("status"), "season": med_.get("season"),
            "year": med_.get("seasonYear"), "format": med_.get("format"),
            "genres": med_.get("genres") or [],
            "score": med_.get("averageScore"),
            "popularity": med_.get("popularity"),
            "cover": (med_.get("coverImage") or {}).get("extraLarge"),
            "banner": med_.get("bannerImage"), "url": med_.get("siteUrl"),
            "studio": ((med_.get("studios") or {}).get("nodes") or [{}])[0].get("name"),
            "start_date": med_.get("startDate"), "end_date": med_.get("endDate"),
        }

    @route("GET", r"/api/v1/jikan/top")
    def jikan_top(h, m, query):
        """Top anime by category. ?filter=bypopularity|airing|manga - falls back to AniList when Jikan is down."""
        filt = q(query, "filter", "bypopularity")
        limit = nq(query, "limit", 25, 1, 25)
        try:
            data, _ = fetch_json(
                "%s/top/anime?filter=%s&limit=%d" % (JIKAN, filt, limit),
                ttl=med, rate_per_min=45, burst=3)
            return {"source": "myanimelist.net (via Jikan)", "filter": filt,
                    "count": len(data.get("data") or []),
                    "results": [{"mal_id": a["mal_id"],
                                 "title": a["title"],
                                 "score": a.get("score"),
                                 "episodes": a.get("episodes"),
                                 "genres": a.get("genres", []),
                                 "cover": a.get("images", {}).get("jpg", {}).get("large_image_url"),
                                 "url": a.get("url")}
                                for a in data.get("data", [])]}
        except UpstreamError:
            pass
        sort_map = {"bypopularity": "POPULARITY_DESC",
                    "airing": "TRENDING_DESC",
                    "upcoming": "START_DATE_DESC",
                    "manga": "TRENDING_DESC"}
        body = json.dumps({
            "query": (
                "query ($perPage: Int) {"
                " Page(page: 1, perPage: $perPage) {"
                "  media(type: ANIME, sort: %s) {"
                "   id idMal title { romaji english } episodes format"
                "   averageScore popularity genres"
                "   coverImage { extraLarge } siteUrl"
                "  }"
                " }"
                "}"
            ) % sort_map.get(filt, "POPULARITY_DESC"),
            "variables": {"perPage": limit},
        }).encode()
        data, _ = fetch_json(ANILIST, ttl=med, method="POST", data=body,
                             rate_per_min=40, burst=2, cache_key="anl|top|" + filt + str(limit))
        media = (data.get("data") or {}).get("Page", {}).get("media") or []
        return {
            "source": "myanimelist.net (via AniList mirror - Jikan unavailable)",
            "filter": filt, "count": len(media),
            "results": [{"mal_id": x.get("idMal"), "anilist_id": x.get("id"),
                         "title": x.get("title"), "score": x.get("averageScore"),
                         "episodes": x.get("episodes"),
                         "format": x.get("format"),
                         "genres": x.get("genres") or [],
                         "cover": (x.get("coverImage") or {}).get("extraLarge"),
                         "url": x.get("siteUrl")}
                        for x in media],
        }

    # ----------------------------------------------------------------- games
    @route("GET", r"/api/v1/game/steam/(?P<appid>\d+)")
    def steam_app(h, m, query):
        """Steam store app details. /api/v1/game/steam/570 (Dota 2)"""
        appid = m.group("appid")
        data, _ = fetch_json(
            "https://store.steampowered.com/api/appdetails?appids=%s&l=id&cc=id" % appid,
            ttl=long, rate_per_min=40)
        app = (data.get(appid) or {}).get("data")
        if not app:
            raise UpstreamError("steam appid not found: %s" % appid, 404)
        return {
            "appid": app.get("steam_appid"), "name": app.get("name"),
            "type": app.get("type"), "is_free": app.get("is_free"),
            "short_description": app.get("short_description"),
            "developers": app.get("developers"), "publishers": app.get("publishers"),
            "genres": [g.get("description") for g in app.get("genres", [])],
            "platforms": app.get("platforms"),
            "release_date": app.get("release_date"),
            "header_image": app.get("header_image"),
            "price": app.get("price_overview"),
        }

    @route("GET", r"/api/v1/game/dota/heroes")
    def dota_heroes(h, m, query):
        """All Dota 2 heroes with attributes and roles."""
        data, _ = fetch_json("https://api.opendota.com/api/heroes", ttl=long,
                             rate_per_min=40)
        return {"count": len(data), "heroes": [{
            "id": x["id"], "name": x.get("localized_name"),
            "primary_attr": x.get("primary_attr"),
            "attack_type": x.get("attack_type"),
            "roles": x.get("roles"),
        } for x in data]}

    @route("GET", r"/api/v1/game/dota/patch")
    def dota_patch(h, m, query):
        """Current Dota 2 patch version list."""
        data, _ = fetch_json("https://api.opendota.com/api/constants/patch",
                             ttl=long, rate_per_min=20)
        return {"current": data[0] if data else None, "recent": data[:20]}

    @route("GET", r"/api/v1/game/valorant/agents")
    def val_agents(h, m, query):
        """Valorant agent list (name, role, description)."""
        data, _ = fetch_json("https://valorant-api.com/v1/agents",
                             ttl=long, rate_per_min=40)
        agents = data.get("data") or []
        return {"count": len(agents), "agents": [{
            "uuid": a.get("uuid"), "name": a.get("displayName"),
            "role": a.get("role"), "description": a.get("description"),
            "img": ((a.get("fullPortrait") or a.get("displayIcon")) or ""),
        } for a in agents]}

    @route("GET", r"/api/v1/game/valorant/maps")
    def val_maps(h, m, query):
        """Valorant map list."""
        data, _ = fetch_json("https://valorant-api.com/v1/maps",
                             ttl=long, rate_per_min=40)
        maps = data.get("data") or []
        return {"count": len(maps), "maps": [{
            "uuid": x.get("uuid"), "name": x.get("displayName"),
            "img": x.get("displayIcon"),
        } for x in maps]}

    @route("GET", r"/api/v1/game/pokemon/(?P<name>[a-z0-9\-]+)")
    def pokemon(h, m, query):
        """Pokemon detail. /api/v1/game/pokemon/pikachu or numeric id."""
        name = m.group("name")
        url = ("https://pokeapi.co/api/v2/pokemon/%s" % name) if name.isalpha() \
            else ("https://pokeapi.co/api/v2/pokemon/%d" % int(name))
        data, _ = fetch_json(url, ttl=long, rate_per_min=40)
        if not data.get("name"):
            raise UpstreamError("pokemon not found: %s" % name, 404)
        types = [t["type"]["name"] for t in data.get("types", [])]
        ab = [a["ability"]["name"] for a in data.get("abilities", [])]
        return {
            "id": data["id"], "name": data["name"], "types": types,
            "height": data.get("height"), "weight": data.get("weight"),
            "base_experience": data.get("base_experience"),
            "abilities": ab,
            "stats": {s["stat"]["name"]: s["base_stat"] for s in data.get("stats", [])},
            "sprites": {"front": ((data.get("sprites") or {}).get("front_default")),
                        "shiny": ((data.get("sprites") or {}).get("front_shiny"))},
        }

    @route("GET", r"/api/v1/game/lol/champions")
    def lol_champions(h, m, query):
        """All League of Legends champions (latest patch, Indonesian names)."""
        ver, _ = fetch_json("https://ddragon.leagueoflegends.com/api/versions.json",
                            ttl=long, rate_per_min=20)
        cur = ver[0]
        data, _ = fetch_json(
            "https://ddragon.leagueoflegends.com/cdn/%s/data/id_ID/champion.json" % cur,
            ttl=long, rate_per_min=20)
        ch = (data.get("data") or {})
        return {"patch": cur, "count": len(ch), "champions": [{
            "id": k, "name": v.get("name"), "title": v.get("title"),
            "tags": v.get("tags"),
            "img": ("https://ddragon.leagueoflegends.com/cdn/%s/img/champion/%s.png"
                    % (cur, v.get("image", {}).get("full"))),
        } for k, v in ch.items()]}

    @route("GET", r"/api/v1/game/lol/items")
    def lol_items(h, m, query):
        """League of Legends item list (latest patch, Indonesian names)."""
        ver, _ = fetch_json("https://ddragon.leagueoflegends.com/api/versions.json",
                            ttl=long, rate_per_min=20)
        cur = ver[0]
        data, _ = fetch_json(
            "https://ddragon.leagueoflegends.com/cdn/%s/data/id_ID/item.json" % cur,
            ttl=long, rate_per_min=20)
        it = (data.get("data") or {})
        return {"patch": cur, "count": len(it), "items": [{
            "id": k, "name": v.get("name"), "description": v.get("plaintext"),
            "gold": (v.get("gold") or {}).get("total"),
            "tags": v.get("tags"),
        } for k, v in it.items()]}

    @route("GET", r"/api/v1/game/chess/archives/(?P<user>[\w\-]+)")
    def chess_archives(h, m, query):
        """Chess.com monthly game archives for a player."""
        user = m.group("user")
        data, _ = fetch_json(
            "https://api.chess.com/pub/player/%s/games/archives" % user,
            ttl=med, rate_per_min=30)
        return {"player": user, "archives": (data.get("archives") or [])[-12:]}

    @route("GET", r"/api/v1/game/chess/leaderboard")
    def chess_leaderboard(h, m, query):
        """Chess.com global leaderboard. ?cat=daily|blitz|bullet|rapid"""
        cat = q(query, "cat", "daily")
        limit = nq(query, "limit", 20, 1, 50)
        url = "https://api.chess.com/pub/leaderboards?cat=%s" % cat
        data, _ = fetch_json(url, ttl=120, rate_per_min=20,
                             headers={"User-Agent": cfg["user_agent"]})
        groups = data if isinstance(data, list) else (
            data.get(cat) or data.get("live") or data.get("daily_rapid")
            or (list(data.values())[0] if data else []))
        out = []
        for p in (groups or [])[:limit]:
            country = p.get("country")
            out.append({
                "rank": p.get("rank"), "username": p.get("username"),
                "name": p.get("name"), "title": p.get("title"),
                "score": p.get("score"),
                "country": (country.rsplit("/", 1)[-1].lower()
                            if isinstance(country, str) else None),
                "win": p.get("win_count"), "loss": p.get("loss_count"),
                "draw": p.get("draw_count"),
                "avatar": p.get("avatar"),
                "url": p.get("url"),
            })
        return {"category": cat, "count": len(out), "players": out}

    # ------------------------------------------------------- gacha / RPG
    # One MediaWiki generator query per category = one HTTP call, and the
    # registry is data, not code, so adding a game is a one-line change.
    GAMES_RPM = 24

    @route("GET", r"/api/v1/games")
    def games_list(h, m, query):
        """Every game wiki available. ?genre=text"""
        rows = [{"slug": k, "game": v[1], "host": v[0], "categories": v[2]}
                for k, v in sorted(games_mod.WIKIS.items())]
        genre = q(query, "genre")
        if genre:
            rows = [r for r in rows if genre.lower() in r["game"].lower()]
        return {"count": len(rows), "games": rows}

    @route("GET", r"/api/v1/games/(?P<slug>[a-z0-9\-]+)")
    def games_by_game(h, m, query):
        """Characters / items / bosses of one game wiki. /api/v1/games/genshin ?category=Bosses&limit=20"""
        slug = m.group("slug")
        entry = games_mod.WIKIS.get(slug)
        if not entry:
            raise UpstreamError("unknown game slug: %s (see /api/v1/games)"
                                % slug, 404)
        host, label, cats = entry
        want = q(query, "category")
        if want:
            cats = [want]
        limit = nq(query, "limit", 20, 1, 50)
        prop, extra = games_mod.member_props(host, fetch_json, 200)
        out, seen, warnings = [], set(), []
        for cat in cats:
            url = games_mod.list_url(host, cat, limit, prop, extra, 200)
            try:
                data, _ = fetch_json(url, ttl=long, rate_per_min=GAMES_RPM, burst=3,
                                     cache_key="games|%s|%s|%s|%s" % (
                                         slug, cat, limit, prop))
            except UpstreamError as exc:
                warnings.append("%s: %s" % (cat, exc))
                continue
            for row in games_mod.parse_category_pages(data):
                if row["name"] in seen:
                    continue
                seen.add(row["name"])
                row["category"] = cat
                out.append(row)
        return {"game": label, "slug": slug, "source": host,
                "count": len(out), "results": out,
                **({"warnings": warnings} if warnings else {})}

    @route("GET", r"/api/v1/games/(?P<slug>[a-z0-9\-]+)/search")
    def games_search(h, m, query):
        """Search one game wiki. /api/v1/games/genshin/search?q=raiden"""
        slug = m.group("slug")
        entry = games_mod.WIKIS.get(slug)
        if not entry:
            raise UpstreamError("unknown game slug: %s" % slug, 404)
        host = entry[0]
        term = q(query, "q", required=True)
        prop, extra = games_mod.member_props(host, fetch_json, 200)
        url = games_mod.wiki_url(
            host, generator="search", gsrsearch=term, gsrnamespace=0, gsrlimit=15,
            prop=prop, piprop="thumbnail", pithumbsize=200, redirects=1, **extra)
        data, _ = fetch_json(url, ttl=med, rate_per_min=GAMES_RPM, burst=3)
        rows = games_mod.parse_category_pages(data)
        return {"game": entry[1], "slug": slug, "query": term,
                "count": len(rows), "results": rows}

    @route("GET", r"/api/v1/games/(?P<slug>[a-z0-9\-]+)/entry/(?P<name>[^?#]+)")
    def games_entry(h, m, query):
        """One entry (character, boss, item) with lead image + lore."""
        slug = m.group("slug")
        entry = games_mod.WIKIS.get(slug)
        if not entry:
            raise UpstreamError("unknown game slug: %s" % slug, 404)
        host, label, _ = entry
        name = txt(m.group("name"))
        if not name:
            raise UpstreamError("entry name required", 400)
        prop, extra = games_mod.page_props(host, fetch_json, 400)
        url = games_mod.wiki_url(
            host, titles=name, prop=prop, piprop="thumbnail", pithumbsize=400,
            redirects=1, **extra)
        data, _ = fetch_json(url, ttl=long, rate_per_min=GAMES_RPM, burst=3,
                             cache_key="gamesent|%s|%s" % (slug, name.lower()))
        row = games_mod.parse_page(data, host)
        if not row:
            raise UpstreamError("not found on %s: %s" % (label, name), 404)
        row["game"] = label
        return row

    # ------------------------------------------------- Team Liquid / esports
    # liquid123.com is a GoDaddy parking page, not the team site. The real one
    # is teamliquid.com (Webflow, server-rendered). 20 divisions, ~172 players.
    TL_BASE = "https://www.teamliquid.com"
    TL_RPM = 20

    @route("GET", r"/api/v1/liquid/divisions")
    def liquid_divisions(h, m, query):
        """All Team Liquid esports divisions. /api/v1/liquid/divisions"""
        html, _ = fetch(TL_BASE + "/games", ttl=long, rate_per_min=TL_RPM,
                        cache_key="liquid|divisions")
        rows = liquid_mod.parse_divisions(html)
        if not rows:
            raise UpstreamError("could not read the Liquid divisions list", 502)
        return {"source": "teamliquid.com", "count": len(rows),
                "divisions": rows}

    @route("GET", r"/api/v1/liquid/roster")
    def liquid_roster(h, m, query):
        """Roster of one division. /api/v1/liquid/roster?division=mlbb/tlid"""
        division = q(query, "division", "mlbb/tlid")
        valid = dict(liquid_mod.TL_DIVISIONS)
        if division not in valid:
            raise UpstreamError(
                "unknown division: %s (see /api/v1/liquid/divisions)" % division, 400)
        html, _ = fetch(TL_BASE + "/games/" + division, ttl=long,
                        rate_per_min=TL_RPM,
                        cache_key="liquid|roster|" + division)
        players = liquid_mod.parse_roster(html, division)
        if not players:
            raise UpstreamError("no roster parsed for %s" % division, 502)
        return {"source": "teamliquid.com", "division": division,
                "game": valid[division], "count": len(players),
                "url": TL_BASE + "/games/" + division, "players": players}

    @route("GET", r"/api/v1/liquid/roster/all")
    def liquid_roster_all(h, m, query):
        """Every division's roster in one call (20 upstream requests)."""
        out, failed = [], []
        for division, label in liquid_mod.TL_DIVISIONS:
            try:
                html, _ = fetch(TL_BASE + "/games/" + division, ttl=long,
                                rate_per_min=TL_RPM, burst=2,
                                cache_key="liquid|roster|" + division)
                players = liquid_mod.parse_roster(html, division)
                out.append({"division": division, "game": label,
                            "count": len(players), "players": players})
            except UpstreamError as exc:
                failed.append({"division": division, "error": str(exc)})
        return {"source": "teamliquid.com",
                "divisions": len(out) + len(failed),
                "players": sum(d["count"] for d in out),
                "failed": failed, "rosters": out}

    @route("GET", r"/api/v1/liquid/news")
    def liquid_news(h, m, query):
        """Team Liquid news (site articles + Google News RSS)."""
        rows = []
        try:
            html, _ = fetch(TL_BASE + "/articles", ttl=med, rate_per_min=TL_RPM,
                            cache_key="liquid|articles")
            rows = liquid_mod.parse_articles(html)
        except UpstreamError as exc:
            rows = [{"error": str(exc)}]
        term = q(query, "q", "Team Liquid")
        rss = ("https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"
               % _qp(term))
        xml, _ = fetch(rss, ttl=med, rate_per_min=30, cache_key="liquid|rss|" + term)
        return {"source": "teamliquid.com", "query": term,
                "articles": rows, "press": ai_mod.parse_rss(xml, 15)}

    # ------------------------------------------------------------------- AI
    # Every upstream here is keyless and Cloudflare-free: Hugging Face JSON,
    # OpenRouter catalogue, HN Algolia, Google News RSS.
    AI_RPM = 40

    @route("GET", r"/api/v1/ai/models")
    def ai_models(h, m, query):
        """Trending models on Hugging Face. ?search=&task=&limit="""
        search = q(query, "search")
        task = q(query, "task")
        limit = nq(query, "limit", 20, 1, 50)
        if search:
            url = (ai_mod.HF + "/models?search=%s&limit=%d&sort=downloads"
                   "&direction=-1" % (_qp(search), limit))
        else:
            url = (ai_mod.HF + "/models?limit=%d&sort=trendingScore"
                   "&direction=-1" % limit)
        data, _ = fetch_json(url, ttl=med, rate_per_min=AI_RPM,
                             cache_key="ai|hf|%s|%s" % (search or "trending", limit))
        rows = ai_mod.parse_hf_models(data, limit)
        if task:
            rows = [r for r in rows
                    if (r.get("task") or "").lower() == task.lower()]
        return {"source": "huggingface.co", "query": search or "trending",
                "count": len(rows), "results": rows}

    @route("GET", r"/api/v1/ai/papers")
    def ai_papers(h, m, query):
        """Daily papers from Hugging Face (today's arXiv AI/ML highlights)."""
        limit = nq(query, "limit", 20, 1, 50)
        data, _ = fetch_json(ai_mod.HF + "/daily_papers?limit=%d" % limit,
                             ttl=med, rate_per_min=AI_RPM,
                             cache_key="ai|papers|%d" % limit)
        rows = ai_mod.parse_hf_papers(data, limit)
        return {"source": "huggingface.co", "count": len(rows), "papers": rows}

    @route("GET", r"/api/v1/ai/catalogue")
    def ai_catalogue(h, m, query):
        """OpenRouter model catalogue: context size + real per-1M pricing."""
        provider = q(query, "provider")
        limit = nq(query, "limit", 40, 1, 200)
        data, _ = fetch_json(ai_mod.OPENROUTER, ttl=long, rate_per_min=10, burst=2,
                             cache_key="ai|openrouter")
        rows = ai_mod.parse_openrouter(data, limit, provider)
        return {"source": "openrouter.ai", "provider": provider,
                "total_catalogue": (data or {}).get("total_count"),
                "count": len(rows), "results": rows}

    @route("GET", r"/api/v1/ai/news")
    def ai_news(h, m, query):
        """AI news: Hacker News + Google News RSS. ?q="""
        term = q(query, "q", "AI")
        limit = nq(query, "limit", 20, 1, 50)
        hn, _ = fetch_json(ai_mod.HN + "?query=%s&tags=story&hitsPerPage=%d"
                           % (_qp(term), limit), ttl=med, rate_per_min=AI_RPM,
                           cache_key="ai|hn|%s" % term)
        rss = ("https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en"
               % _qp(term))
        xml, _ = fetch(rss, ttl=med, rate_per_min=30,
                       cache_key="ai|rss|%s" % term)
        return {"source": "news.ycombinator.com + news.google.com",
                "query": term, "hacker_news": ai_mod.parse_hn(hn, limit),
                "press": ai_mod.parse_rss(xml, limit)}

    # ------------------------------------------------- AI (pure HTML scrape)
    # The endpoints above use keyless JSON APIs because they are cheaper and
    # more precise. These three read the rendered HTML directly - no JSON API
    # involved at all - for callers who want scrape-only behaviour.
    SCRAPE_RPM = 20

    @route("GET", r"/api/v1/ai/scrape/models")
    def ai_scrape_models(h, m, query):
        """Hugging Face trending models, read from the HTML grid. ?sort=trending|downloads|likes"""
        sort = q(query, "sort", "trending")
        if sort not in ("trending", "downloads", "likes", "modified"):
            raise UpstreamError("sort must be trending, downloads, likes or modified", 400)
        limit = nq(query, "limit", 30, 1, 50)
        html, _ = fetch("https://huggingface.co/models?sort=" + sort,
                        ttl=med, rate_per_min=SCRAPE_RPM, burst=2,
                        cache_key="aiscrape|hfmodels|" + sort)
        rows = aiweb_mod.parse_hf_cards(html, limit)
        if not rows:
            raise UpstreamError("could not read the Hugging Face model grid", 502)
        task = q(query, "task")
        if task:
            rows = [r for r in rows
                    if (r.get("task") or "").lower().find(task.lower()) >= 0]
        return {"source": "huggingface.co", "method": "html-scrape",
                "sort": sort, "count": len(rows), "results": rows}

    @route("GET", r"/api/v1/ai/scrape/papers")
    def ai_scrape_papers(h, m, query):
        """Hugging Face Daily Papers, read from the page's data-props JSON."""
        limit = nq(query, "limit", 20, 1, 50)
        html, _ = fetch("https://huggingface.co/papers", ttl=med,
                        rate_per_min=SCRAPE_RPM, burst=2,
                        cache_key="aiscrape|hfpapers")
        rows = aiweb_mod.parse_hf_papers_html(html, limit)
        if not rows:
            raise UpstreamError("could not read the HF daily papers payload", 502)
        return {"source": "huggingface.co", "method": "html-scrape",
                "count": len(rows), "papers": rows}

    @route("GET", r"/api/v1/ai/scrape/ollama")
    def ai_scrape_ollama(h, m, query):
        """Ollama model library, read from the HTML listing. ?limit="""
        limit = nq(query, "limit", 40, 1, 100)
        html, _ = fetch("https://ollama.com/library", ttl=long,
                        rate_per_min=SCRAPE_RPM, burst=2,
                        cache_key="aiscrape|ollama")
        rows = aiweb_mod.parse_ollama(html, limit)
        if not rows:
            raise UpstreamError("could not read the Ollama library page", 502)
        return {"source": "ollama.com", "method": "html-scrape",
                "count": len(rows), "models": rows}

    # --------------------------------------- AI tool & model registries
    # Straight HTML scrape of two public AI directories. No key, no signup.
    #   rewind.ai          - /tools/ grid, 866 entries incl. 437 AI models
    #   chatbotchatapp.com - model picker dropdown on the chat page
    # One request each for the full catalogue.
    RW_RPM = 12

    @route("GET", r"/api/v1/rewind/tools")
    def rewind_tools(h, m, query):
        """Rewind.ai tool registry. ?category=&kind=tool|model&q=&limit="""
        html, _ = fetch(aitools_mod.REWIND_TOOLS, ttl=long,
                        rate_per_min=RW_RPM, burst=2,
                        cache_key="rewind|tools")
        rows = aitools_mod.parse_tools_grid(html)
        if not rows:
            raise UpstreamError("could not read the Rewind.ai tool grid", 502)
        total = len(rows)
        rows = aitools_mod.filter_tools(rows, category=q(query, "category"),
                                        kind=q(query, "kind"), q_=q(query, "q"))
        limit = nq(query, "limit", 50, 1, 900)
        return {"source": "rewind.ai", "total": total,
                "count": len(rows[:limit]), "results": rows[:limit]}

    @route("GET", r"/api/v1/rewind/categories")
    def rewind_categories(h, m, query):
        """Rewind.ai tool categories with per-category counts."""
        html, _ = fetch(aitools_mod.REWIND_TOOLS, ttl=long,
                        rate_per_min=RW_RPM, burst=2,
                        cache_key="rewind|tools")
        rows = aitools_mod.parse_tools_grid(html)
        if not rows:
            raise UpstreamError("could not read the Rewind.ai tool grid", 502)
        agg = {}
        for r in rows:
            k = r["category"]
            e = agg.setdefault(k, {"category": k, "title": r["category_title"],
                                  "tools": 0, "models": 0})
            e["tools"] += 1
            if r["kind"] == "model":
                e["models"] += 1
        out = sorted(agg.values(), key=lambda x: -x["tools"])
        return {"source": "rewind.ai", "count": len(out),
                "total_entries": len(rows), "categories": out}

    @route("GET", r"/api/v1/rewind/models")
    def rewind_models(h, m, query):
        """The 437 AI models Rewind.ai serves. ?provider=&q="""
        html, _ = fetch(aitools_mod.REWIND_TOOLS, ttl=long,
                        rate_per_min=RW_RPM, burst=2,
                        cache_key="rewind|tools")
        rows = aitools_mod.parse_models(aitools_mod.parse_tools_grid(html))
        if not rows:
            raise UpstreamError("could not read the Rewind.ai model list", 502)
        total = len(rows)
        prov = q(query, "provider")
        if prov:
            rows = [r for r in rows
                    if (r["provider"] or "").lower() == prov.lower()]
        needle = q(query, "q")
        if needle:
            n = needle.lower()
            rows = [r for r in rows
                    if n in r["name"].lower() or n in r["slug"].lower()]
        limit = nq(query, "limit", 50, 1, 500)
        return {"source": "rewind.ai", "total": total, "count": len(rows[:limit]),
                "providers": sorted({r["provider"] for r in rows
                                     if r["provider"]}),
                "results": rows[:limit]}

    @route("GET", r"/api/v1/rewind/compare")
    def rewind_compare(h, m, query):
        """Model-vs-model spec sheet (context window, cost, free tier).

        `url` accepts a full /compare/<a>-vs-<b>/ URL or a bare slug pair
        `a-vs-b`; with neither, returns the index of every comparison."""
        ref = q(query, "url") or q(query, "pair")
        sm, _ = fetch(aitools_mod.REWIND_SITEMAP, ttl=med,
                      rate_per_min=RW_RPM, burst=2, cache_key="rewind|sitemap")
        pairs = aitools_mod.compare_pairs(sm)
        if not pairs:
            raise UpstreamError("could not read the Rewind.ai sitemap", 502)
        if not ref:
            limit = nq(query, "limit", 50, 1, 300)
            return {"source": "rewind.ai", "count": len(pairs),
                    "comparisons": pairs[:limit]}
        url = ref if ref.startswith("http") else (
            aitools_mod.REWIND_COMPARE + ref.strip("/") + "/")
        if "-vs-" not in url:
            raise UpstreamError("use a 'a-vs-b' pair or a /compare/ URL", 400)
        html, _ = fetch(url, ttl=long, rate_per_min=RW_RPM, burst=2,
                        cache_key="rewind|cmp|" + url)
        page = aitools_mod.parse_compare_page(html)
        if not page["specs"]:
            raise UpstreamError("could not read the comparison table", 502)
        page["source"] = "rewind.ai"
        page["url"] = url
        return page

    @route("GET", r"/api/v1/chatbotchatapp/models")
    def cbb_models(h, m, query):
        """chatbotchatapp.com model picker (name, blurb, paid-only flag)."""
        html, _ = fetch(aitools_mod.CBB_ROOT, ttl=med,
                        rate_per_min=RW_RPM, burst=2, cache_key="cbb|root")
        rows = aitools_mod.parse_cbb_models(html)
        if not rows:
            raise UpstreamError("could not read the model picker", 502)
        return {"source": "chatbotchatapp.com", "count": len(rows),
                "models": rows}

    @route("GET", r"/api/v1/chatbotchatapp/info")
    def cbb_info(h, m, query):
        """chatbotchatapp.com capability list and free-tier limits."""
        html, _ = fetch(aitools_mod.CBB_ROOT, ttl=med,
                        rate_per_min=RW_RPM, burst=2, cache_key="cbb|root")
        info = aitools_mod.parse_cbb_features(html)
        info["source"] = "chatbotchatapp.com"
        info["url"] = aitools_mod.CBB_ROOT
        return info

    # ------------------------------------------------------------- AI ask
    # The one endpoint that hits a live AI model, so it is also the only one
    # with real limits. chatbotchatapp.com caps anonymous chats per egress IP
    # (5/window plus an undocumented daily cap), so the route order is:
    #   1. cache (24h) - the same prompt must never cost two upstream calls
    #   2. direct     - fast (~3-5s) while the daily cap allows it
    #   3. proxy pool - rotating egress IP, bypasses the cap, but slow
    # Every attempt is time-bounded; a failure returns 503, never a hang.
    # Proxy credentials come from the environment, never from config.json.
    @route("GET", r"/api/v1/ai/ask")
    def ai_ask(h, m, query):
        """Ask a free AI model a question.

        ?prompt= (required)  &model=gpt-5|deepseek-v4|glm-5.3|qwen3.8...
        &proxy=0 to skip the direct attempt and go straight to the pools.
        &retries= how many times to retry a failed proxy attempt.
        Results are cached 24h per prompt+model, so repeating a question is
        free and instant."""
        prompt = q(query, "prompt", required=True)
        if len(prompt) > 4000:
            raise UpstreamError("prompt longer than 4000 characters", 400)
        model = q(query, "model", "gpt-5")
        retries = nq(query, "retries", 1, 0, 4)
        use_proxy = q(query, "proxy", "1") != "0"
        key = "aiask|%s|%s" % (model, hashlib.sha256(
            prompt.encode("utf8")).hexdigest()[:32])
        hit = CACHE.get(key)
        if hit is not None:
            payload = json.loads(hit)
            payload["cached"] = True
            return payload
        started = time.time()
        try:
            res = aiask_mod.ask(prompt, model=model, proxy_tries=retries + 1,
                                direct=use_proxy,
                                pools=aiask_mod.parse_pools(
                                    _ENV.get("ASK_PROXIES"),
                                    _ENV.get("ASK_PROXY_PASSWORD"))
                                if use_proxy else [])
        except aiask_mod.QuotaExhausted as exc:
            raise UpstreamError(
                "the free upstream is out of daily chats for this IP; the "
                "server has no proxy pool configured (ASK_PROXIES)", 429)
        except aiask_mod.AskError as exc:
            raise UpstreamError(str(exc), exc.status if exc.status >= 400 else 502)
        res.update({"model": model, "cached": False,
                    "source": "chatbotchatapp.com"})
        CACHE.set(key, json.dumps(res), ttl=86400)
        return res

    # ------------------------------------------------------- phone numbers
    # Format + country + plausibility only. Nothing is ever sent to a carrier
    # and no account is needed: the data is libphonenumber's static metadata.
    @route("GET", r"/api/v1/phone/validate")
    def phone_validate(h, m, query):
        """Validate a phone number. ?number= required, accepts +62..., 0812...

        Returns the E.164 form, calling code, region, digit count and whether
        the length matches what that country actually issues."""
        num = q(query, "number", required=True)
        region = q(query, "region")
        e164, why = phone_mod.to_e164(num, region)
        if not e164:
            raise UpstreamError(why or "could not read that number", 400)
        meta, _ = fetch(phone_mod.PHONEMETA_URL, ttl=long, rate_per_min=4,
                        burst=1, cache_key="phone|meta",
                        headers={"Accept": "*/*"})
        table = _phone_meta(meta)
        res = phone_mod.validate(e164, table, region_hint=region)
        res["split"] = phone_mod.format_e164(res.get("e164") or "")
        res["country"] = phone_mod.country_name(
            (res.get("country_calling_code") or "+")[1:])
        return res

    # --------------------------------------------------- country table
    # The 206-entry calling-code -> (name, flag, search code) table the form's
    # country picker is driven from, plus longest-prefix detection. Offline:
    # it is a dict in countries.py, no request leaves the server.
    @route("GET", r"/api/v1/country/list")
    def country_list(h, m, query):
        """All 206 entries: calling code, Indonesian name, flag, search code.

        ?limit= (default 250) &offset= (0) to page it."""
        rows = country_mod.all_countries()
        off = nq(query, "offset", 0, 0, len(rows))
        lim = nq(query, "limit", 250, 1, 500)
        return {"count": len(rows), "offset": off, "limit": lim,
                "total": len(rows), "countries": rows[off:off + lim]}

    @route("GET", r"/api/v1/country/detect")
    def country_detect(h, m, query):
        """Which country is this number in, and what the picker should get.

        ?number= required. Also returns the national part to type, the search
        terms to try in the form's country box (name, then bare code), and the
        code the option must be verified against - that check is what keeps
        +249 Sudan from selecting +211 Sudan Selatan."""
        num = q(query, "number", required=True)
        # q() strips, so a ?number= of only spaces arrives here as None and a
        # missing one raises already. Either way there is nothing to detect, and
        # defaulting would hand back a confident wrong country (+62).
        if not num or not "".join(ch for ch in str(num) if ch.isdigit()):
            raise UpstreamError(
                "number has no digits: %r" % (num,), 400)
        c = country_mod.search_candidates(num)
        c["fallback_used"] = not c.pop("matched_exact")
        c["table_size"] = len(country_mod.COUNTRIES)
        return c

    # ----------------------------------------------------------------- misc
    @route("GET", r"/api/v1/wiki/search")
    def wiki_search(h, m, query):
        """Indonesian Wikipedia search. ?q=JKT48"""
        term = q(query, "q", required=True)
        limit = nq(query, "limit", 10, 1, 50)
        url = ("%s?action=query&list=search&srsearch=%s&srlimit=%d&format=json"
               % (WIKI, _qp(term), limit))
        data, _ = fetch_json(url, ttl=med, rate_per_min=30)
        return {"query": term, "count": len(parse_wiki_search(data, limit)),
                "results": parse_wiki_search(data, limit)}

    @route("GET", r"/api/v1/wiki/page/(?P<title>.+)")
    def wiki_page(h, m, query):
        """Indonesian Wikipedia article summary. /api/v1/wiki/page/Mobile_Legends"""
        title = m.group("title").replace("_", " ").strip()
        url = "https://id.wikipedia.org/api/rest_v1/page/summary/" + _qp(title.replace(" ", "_"))
        data, _ = fetch_json(url, ttl=long, rate_per_min=30)
        if not data.get("title"):
            raise UpstreamError("wikipedia article not found: %s" % title, 404)
        return {"source": "id.wikipedia.org", **parse_wiki_summary(data)}

    @route("GET", r"/api/v1/news/(?P<qterm>[\w%\+ ]+)")
    def news_search(h, m, query):
        """Generic news search via Google News RSS. /api/v1/news/MPL%20Indonesia"""
        term = m.group("qterm")
        url = "%s?q=%s%s" % (GNEWS, _qp(term), GNEWS_PARAMS)
        xml, _ = fetch(url, ttl=180, rate_per_min=30, burst=4)
        limit = nq(query, "limit", 20, 1, 100)
        return {"query": term, "count": len(parse_gnews(xml, limit)),
                "news": parse_gnews(xml, limit)}

    @route("GET", r"/api/v1/fact/cat")
    def cat_fact(h, m, query):
        """Random cat fact."""
        data, _ = fetch_json("https://catfact.ninja/fact", ttl=60, rate_per_min=30)
        return data

    @route("GET", r"/api/v1/tech/news")
    def tech_news(h, m, query):
        """Hacker News top stories (ids + top item details)."""
        ids, _ = fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json",
                            ttl=120, rate_per_min=20)
        limit = nq(query, "limit", 10, 1, 30)
        out = []
        for i in (ids or [])[:limit]:
            try:
                item, _ = fetch_json("https://hacker-news.firebaseio.com/v0/item/%s.json" % i,
                                     ttl=120, rate_per_min=60, burst=10)
            except Exception:
                continue
            if item:
                out.append({"id": item.get("id"), "title": item.get("title"),
                            "url": item.get("url"), "score": item.get("score"),
                            "by": item.get("by"), "comments": item.get("descendants")})
        return {"count": len(out), "stories": out}

    @route("GET", r"/api/v1/country/(?P<code>[a-zA-Z]{2})")
    def country(h, m, query):
        """Country info by ISO code. /api/v1/country/id"""
        code = m.group("code")
        data, _ = fetch_json(
            "https://restcountries.com/v3/alpha/%s" % code, ttl=long,
            rate_per_min=30)
        if not data:
            raise UpstreamError("country not found: %s" % code, 404)
        c = data[0] if isinstance(data, list) else data
        return {
            "name": (c.get("name") or {}).get("common"),
            "official": (c.get("name") or {}).get("official"),
            "flag": (c.get("flags") or {}).get("png"),
            "capital": c.get("capital"),
            "region": c.get("region"), "population": c.get("population"),
            "languages": [l.get("name") for l in (c.get("languages") or {}).values()],
            "currencies": [x.get("name") for x in (c.get("currencies") or {}).values()],
            "tld": c.get("tld"), "timezones": c.get("timezones"),
        }

    @route("GET", r"/api/v1/book/(?P<title>[\w\s\-]+)")
    def book(h, m, query):
        """Book search via Open Library. /api/v1/book/dune"""
        title = m.group("title")
        data, _ = fetch_json(
            "https://openlibrary.org/search.json?q=%s&limit=5" % _qp(title),
            ttl=med, rate_per_min=20)
        docs = data.get("docs") or []
        return {"query": title, "count": len(docs), "books": [{
            "key": d.get("key"), "title": d.get("title"),
            "author": d.get("author_name"),
            "year": d.get("first_publish_year"),
            "rating": d.get("average_rating"),
            "cover": ("https://covers.openlibrary.org/b/id/%s-M.jpg" % d["cover_i"])
            if d.get("cover_i") else None,
        } for d in docs]}

    @route("GET", r"/api/v1/tv/(?P<qterm>[\w%\+ ]+)")
    def tv_search(h, m, query):
        """TV show search via TVMaze. /api/v1/tv/friends"""
        term = m.group("qterm")
        data, _ = fetch_json("https://api.tvmaze.com/search/shows?q=%s" % _qp(term),
                             ttl=med, rate_per_min=20)
        return {"query": term, "count": len(data or []), "results": [{
            "id": r["show"]["id"], "name": r["show"]["name"],
            "genre": r["show"].get("genre"), "network": r["show"].get("network"),
            "status": r["show"].get("status"),
            "image": (r["show"].get("medium_image") or r["show"].get("image") or {}).get("original"),
        } for r in (data or [])]}


def _qp(s):
    from urllib.parse import quote_plus
    return quote_plus(s)


_PHONE_TABLE = {}


def _phone_meta(xml):
    """Parse libphonenumber metadata once per process and reuse it."""
    global _PHONE_TABLE
    if not _PHONE_TABLE:
        _PHONE_TABLE = phone_mod._parse_metadata(xml)
    return _PHONE_TABLE


def _mpl_season(html):
    m = re.search(r"SEASON\s+(\d+)", html, re.I)
    return "Season " + m.group(1) if m else None
