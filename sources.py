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
import jkt48 as jkt48_mod
import play as play_mod
import liquid as liquid_mod
import ai as ai_mod
import aiweb as aiweb_mod
import aitools as aitools_mod
import aiask as aiask_mod
import pollinations as pollinations_mod
import countries as country_mod
import phone as phone_mod

# Free-proxy pool for /ai/ask, probed in the background. Reads a local file the
# operator refreshes; when it is missing or empty the route just uses no proxy.
_FREE_PROXY_FILE = (os.environ.get("ASK_FREE_PROXIES")
                    or "/root/ApiBot/free_proxies.json")
_free_proxies = {"list": [], "checked": 0, "at": 0.0}
FREE_PROXY_MAX_AGE = 3600

# Game sessions. In-process and deliberately small: a bot holds a handful of
# games at a time, and anything stale should evaporate rather than accumulate.
_SESSIONS = play_mod.Sessions(max_items=2000)


def _load_free_proxies(force=False):
    """Return the cached list of free proxies, reloading if it is stale.

    The file is a plain JSON array of ``host:port`` strings. Probing them is
    the operator's job (see the README) because a live probe is slow and rude;
    this only reads whatever was last verified.
    """
    now = time.time()
    if (not force and _free_proxies["list"]
            and now - _free_proxies["at"] < FREE_PROXY_MAX_AGE):
        return _free_proxies["list"]
    try:
        with open(_FREE_PROXY_FILE, "r") as f:
            data = json.load(f)
        if isinstance(data, list):
            clean = [str(x).strip() for x in data
                     if isinstance(x, str) and re.match(
                         r"^\d{1,3}(\.\d{1,3}){3}:\d{2,5}$", x.strip())]
            _free_proxies.update(list=clean, checked=len(clean), at=now)
    except Exception:
        _free_proxies.setdefault("at", now)
    return _free_proxies["list"]

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

    # ------------------------------------------------- JKT48 (fandom wiki)
    def _fandom_json(url, ttl=None):
        """MediaWiki api.php returns plain JSON and is not behind the
        Cloudflare wall that blocks the wiki's HTML pages, so the whole
        member roster is reachable without a browser."""
        data, _ = fetch_json(url, ttl=ttl if ttl is not None else long,
                             rate_per_min=40)
        if isinstance(data, dict) and data.get("error"):
            raise UpstreamError("fandom api: %s" % data["error"].get("info"),
                                502)
        return data

    @route("GET", r"/api/v1/jkt48/roster")
    def jkt48_roster(h, m, query):
        """The full member roster, names only, straight from the Fandom wiki.

        jkt48.com itself answers 403 to non-browser clients, and the wiki's
        HTML pages are blocked the same way; its api.php is not.
        """
        category = q(query, "category", "Members")
        limit = nq(query, "limit", 200, 1, 500)
        names = jkt48_mod.category_members(_fandom_json, category, limit)
        return {"source": "jkt48.fandom.com", "category": category,
                "count": len(names), "members": names}

    @route("GET", r"/api/v1/jkt48/member")
    def jkt48_member_full(h, m, query):
        """One member in detail: birth name, nickname, blood type, zodiac,
        height, generation, team, join dates and social links.

        &wiki=1 adds the Indonesian Wikipedia lead paragraph for context the
        wiki's one-line description does not carry.
        """
        name = q(query, "name", required=True)
        rec = jkt48_mod.member_record(_fandom_json, name)
        if rec is None:
            raise UpstreamError("no JKT48 member page named %r" % name, 404)
        rec["source"] = "jkt48.fandom.com"
        if q(query, "wiki", "0") == "1":
            rec["id_wikipedia"] = jkt48_mod.id_wikipedia_summary(
                _fandom_json, name)
        return rec

    @route("GET", r"/api/v1/jkt48/member/search")
    def jkt48_member_search(h, m, query):
        """Search the roster by name, nickname, generation or team."""
        term = q(query, "q", required=True)
        limit = nq(query, "limit", 20, 1, 100)
        names = jkt48_mod.roster(_fandom_json)
        recs = jkt48_mod.member_batch(_fandom_json, names)
        needle = term.lower()
        hits = [r for r in recs.values()
                if needle in json.dumps(r, ensure_ascii=False).lower()]
        return {"source": "jkt48.fandom.com", "query": term,
                "scanned": len(recs), "count": len(hits[:limit]),
                "members": hits[:limit]}

    # ------------------------------------------------------------ playable
    def _session(sid, game=None):
        st = _SESSIONS.get(sid)
        if st is None:
            raise UpstreamError("no such game session (it expires after %dh, "
                                "or the server restarted)" % (
                                    play_mod.GAME_TTL // 3600), 404)
        if game and st.get("game") != game:
            raise UpstreamError("session %s is a %s game, not %s"
                                % (sid, st.get("game"), game), 400)
        return st

    @route("GET", r"/api/v1/play/list")
    def play_list(h, m, query):
        """What can be played, and the session ids currently alive."""
        return {
            "games": ["tictactoe", "wordguess", "riddle", "gacha", "dice",
                      "puzzle", "minesweeper"],
            "active_sessions": _SESSIONS.count(),
            "note": "start a game, keep its id, then send moves to the "
                    "matching /play/<game>/<action> route",
        }

    @route("GET", r"/api/v1/play/tictactoe")
    def play_ttt_new(h, m, query):
        """Start a tic-tac-toe game. &size=3..15, &first=X|O."""
        size = nq(query, "size", 3, 3, play_mod.MAX_TTT_SIZE)
        first = (q(query, "first", "X") or "X").upper()[:1]
        if first not in ("X", "O"):
            raise UpstreamError("first must be X or O", 400)
        st = play_mod.new_tictactoe(size, first)
        sid = _SESSIONS.put(play_mod.new_id("ttt"), st)
        return {"session": sid, "size": size, "first": first,
                "your_mark": first, "board": play_mod.ttt_board_text(
                    st["board"], size), "cells": size * size,
                "next": "/api/v1/play/tictactoe/move?session=%s&cell=1"
                         % sid}

    @route("GET", r"/api/v1/play/tictactoe/move")
    def play_ttt_move(h, m, query):
        """Place a mark. &session= &cell=1..N (1-based)."""
        sid = q(query, "session", required=True)
        st = _session(sid, "tictactoe")
        raw = q(query, "cell", required=True)
        try:
            cell = int(raw)
        except ValueError:
            raise UpstreamError("cell must be a number, got %r" % raw, 400)
        if not (1 <= cell <= st["size"] ** 2):
            # Reject out of range as a client error rather than burying it in
            # the message field: a bot should not have to parse prose to tell
            # a bad input from a normal move.
            raise UpstreamError("cell must be between 1 and %d for a %dx%d board"
                                % (st["size"] ** 2, st["size"], st["size"]),
                                400)
        st, msg = play_mod.ttt_play(st, cell)
        _SESSIONS.put(sid, st)
        return {"session": sid, "message": msg, "board": play_mod.ttt_board_text(
            st["board"], st["size"]), "turn": st["turn"], "winner": st["winner"],
            "over": st["over"], "moves": st["moves"]}

    @route("GET", r"/api/v1/play/word/start")
    def play_word_new(h, m, query):
        """Start a word-guessing game. &length=3..12, &lang=en|id."""
        length = q(query, "length")
        st = play_mod.new_wordgame(length, q(query, "lang", "en"))
        sid = _SESSIONS.put(play_mod.new_id("word"), st)
        view = play_mod.wordgame_state(st)
        return {"session": sid, "length": len(st["word"]), "lang": st["lang"],
                **view, "next": "/api/v1/play/word/guess?session=%s&letter=a"
                               % sid}

    @route("GET", r"/api/v1/play/word/guess")
    def play_word_guess(h, m, query):
        """Guess one letter. &session= &letter=A-Z."""
        sid = q(query, "session", required=True)
        st = _session(sid, "wordguess")
        st, msg = play_mod.wordgame_guess(st, q(query, "letter", required=True))
        _SESSIONS.put(sid, st)
        return {"session": sid, "message": msg,
                **play_mod.wordgame_state(st, reveal=st["status"] == "lost")}

    @route("GET", r"/api/v1/play/word/solve")
    def play_word_solve(h, m, query):
        """Give up and reveal the word."""
        sid = q(query, "session", required=True)
        st = _session(sid, "wordguess")
        st, msg = play_mod.wordgame_solve(st)
        _SESSIONS.put(sid, st)
        return {"session": sid, "message": msg,
                **play_mod.wordgame_state(st, reveal=True)}

    @route("GET", r"/api/v1/play/riddle/start")
    def play_riddle_new(h, m, query):
        """Start an asah-otak riddle. &lang=en|id."""
        lang = q(query, "lang", "en")
        st = play_mod.new_riddle(lang)
        sid = _SESSIONS.put(play_mod.new_id("riddle"), st)
        return {"session": sid, "lang": st["lang"], "riddle": st["riddle"],
                "hints_available": len(st["hints"]) + 1,
                "next": "/api/v1/play/riddle/hint?session=%s" % sid}

    @route("GET", r"/api/v1/play/riddle/hint")
    def play_riddle_hint(h, m, query):
        """Take the next hint (there are three, each more direct)."""
        sid = q(query, "session", required=True)
        st = _session(sid, "riddle")
        st, msg = play_mod.riddle_hint(st)
        _SESSIONS.put(sid, st)
        return {"session": sid, "message": msg, "hints_used": st["hints_used"]}

    @route("GET", r"/api/v1/play/riddle/answer")
    def play_riddle_answer(h, m, query):
        """Submit an answer. &session= &answer=towel"""
        sid = q(query, "session", required=True)
        st = _session(sid, "riddle")
        st, msg = play_mod.riddle_answer(st, q(query, "answer", required=True))
        _SESSIONS.put(sid, st)
        return {"session": sid, "message": msg, "solved": st["solved"]}

    @route("GET", r"/api/v1/play/gacha/pull")
    def play_gacha(h, m, query):
        """Draw from the gacha. &count=1..20. A pity rule forces an SSR after
        40 pulls with none, so the bot can promise a guarantee honestly."""
        sid = q(query, "session")
        st = _SESSIONS.get(sid) if sid else None
        fresh = st is None or st.get("game") != "gacha"
        if fresh:
            sid = play_mod.new_id("gacha")
            st = play_mod.new_gacha()
        st, got = play_mod.gacha_pull(st, q(query, "count", 1))
        _SESSIONS.put(sid, st)
        best = max(got, key=lambda x: ("N", "R", "SR", "SSR").index(x["rarity"]))
        return {"session": sid, "new_player": fresh, "count": len(got),
                "pulls": got, "best": best, "pulls_since_ssr": st["since_ssr"],
                "total_pulls": st["pulls"],
                "pity_at": play_mod.PITY_THRESHOLD}

    @route("GET", r"/api/v1/play/dice")
    def play_dice(h, m, query):
        """Roll dice. ?dice=2d6+3 (also d20, 4D8-2). No session needed."""
        notation = q(query, "dice", required=True)
        total, rolls, mods, ok = play_mod.roll_dice(notation)
        if not ok:
            raise UpstreamError("cannot parse dice notation %r; try 2d6+3, "
                                "d20, 4D8-2" % notation, 400)
        return {"notation": notation, "total": total, "rolls": rolls,
                "modifiers": mods}

    @route("GET", r"/api/v1/play/puzzle")
    def play_puzzle_new(h, m, query):
        """Start a sliding puzzle. &size=2..6. Every board is solvable."""
        size = nq(query, "size", 4, 2, 6)
        st = play_mod.new_puzzle(size)
        sid = _SESSIONS.put(play_mod.new_id("puzz"), st)
        return {"session": sid, "size": size, "board": st["board"],
                "display": play_mod.puzzle_text(st["board"], size),
                "solvable": play_mod.is_solvable(st["board"]),
                "next": "/api/v1/play/puzzle/move?session=%s&tile=1" % sid}

    @route("GET", r"/api/v1/play/puzzle/move")
    def play_puzzle_move(h, m, query):
        """Slide a tile into the blank. &session= &tile=0..N-1 (0-based)."""
        sid = q(query, "session", required=True)
        st = _session(sid, "puzzle")
        raw = q(query, "tile", required=True)
        try:
            idx = int(raw)
        except ValueError:
            raise UpstreamError("tile must be a number, got %r" % raw, 400)
        if not (0 <= idx < st["size"] ** 2):
            raise UpstreamError("tile must be between 0 and %d for a %dx%d board"
                                % (st["size"] ** 2 - 1, st["size"],
                                   st["size"]), 400)
        st, msg = play_mod.puzzle_moves(st, idx)
        _SESSIONS.put(sid, st)
        return {"session": sid, "message": msg, "board": st["board"],
                "display": play_mod.puzzle_text(st["board"], st["size"]),
                "moves": st["moves"],
                "solved": st["board"] == list(range(1, st["size"] ** 2)) + [0]}

    @route("GET", r"/api/v1/play/puzzle/hint")
    def play_puzzle_hint(h, m, query):
        """Which tile can move toward its place right now."""
        sid = q(query, "session", required=True)
        st = _session(sid, "puzzle")
        return {"session": sid, "hint": play_mod.puzzle_hint(st)}

    @route("GET", r"/api/v1/play/mines")
    def play_mines_new(h, m, query):
        """Start minesweeper. &size=5..30, &mines=. The first click is
        always safe - mines are placed around it, not on it."""
        size = nq(query, "size", 9, 5, 30)
        mines = nq(query, "mines", max(10, size * size // 8), 1,
                   size * size - 9)
        st = play_mod.new_mines(mines, size)
        sid = _SESSIONS.put(play_mod.new_id("mine"), st)
        return {"session": sid, "size": size, "mines": st["mines"],
                "display": play_mod.mines_text(st),
                "next": "/api/v1/play/mines/reveal?session=%s&cell=0" % sid}

    @route("GET", r"/api/v1/play/mines/reveal")
    def play_mines_reveal(h, m, query):
        """Open a cell. &session= &cell=0..N-1."""
        sid = q(query, "session", required=True)
        st = _session(sid, "minesweeper")
        raw = q(query, "cell", required=True)
        try:
            idx = int(raw)
        except ValueError:
            raise UpstreamError("cell must be a number, got %r" % raw, 400)
        if not (0 <= idx < st["size"] ** 2):
            raise UpstreamError("cell must be between 0 and %d for a %dx%d board"
                                % (st["size"] ** 2 - 1, st["size"],
                                   st["size"]), 400)
        st, msg = play_mod.mines_reveal(st, idx)
        _SESSIONS.put(sid, st)
        opened = len(st["opened"])
        return {"session": sid, "message": msg, "display": play_mod.mines_text(st),
                "opened": opened, "dead": st["dead"],
                "cleared": opened >= st["size"] ** 2 - st["mines"],
                "mines": st["mines"]}

    @route("GET", r"/api/v1/play/drop")
    def play_drop(h, m, query):
        """Forget a game session."""
        sid = q(query, "session", required=True)
        _SESSIONS.drop(sid)
        return {"session": sid, "dropped": True, "active_sessions":
                _SESSIONS.count()}

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
        # &wait=seconds: the anonymous window on the first upstream is closed
        # most of the time, so a client that can block gets a real answer
        # instead of an immediate 429. Capped, because an unbounded wait would
        # just hold a thread.
        wait_for = nq(query, "wait", 0, 0, 300)
        key = "aiask|%s|%s" % (model, hashlib.sha256(
            prompt.encode("utf8")).hexdigest()[:32])
        hit = CACHE.get(key)
        if hit is not None:
            payload = json.loads(hit)
            payload["cached"] = True
            return payload
        started = time.time()
        # Upstream 1: text.pollinations.ai. Keyless, needs no proxy, answers in
        # a few seconds. Anonymous use is metered per IP at roughly one request
        # per cooldown window, so a 402 here means "come back later", not
        # "service down" - fall through to the proxy-backed route below.
        poll_timeout = int(_ENV.get("POLLINATIONS_TIMEOUT", "45"))
        poll_deadline = time.time() + wait_for
        polls = 0
        # Open proxies matter for this upstream specifically: the anonymous
        # window is per exit IP, so a different IP is a different window. They
        # are only consulted once the direct window is closed, because a
        # public proxy sees the request.
        free_pools = _load_free_proxies() if use_proxy else []
        while True:
            try:
                text, used_model, secs = pollinations_mod.ask(
                    prompt, timeout=poll_timeout,
                    proxies=free_pools if polls else [])
                res = {"answer": text, "via": "pollinations", "attempts": 1,
                       "waited_polls": polls,
                       "elapsed": round(time.time() - started, 2),
                       "route_seconds": secs, "upstream_model": used_model}
                if polls and free_pools:
                    res["via_open_proxy"] = True
                res.update({"model": model, "cached": False,
                            "source": "text.pollinations.ai"})
                CACHE.set(key, json.dumps(res), ttl=86400)
                return res
            except pollinations_mod.QuotaExhausted:
                # Only a client that asked to wait gets to wait; the default
                # path falls through immediately to the proxy-backed upstream.
                if time.time() >= poll_deadline:
                    break
                polls += 1
                time.sleep(min(12, max(0, poll_deadline - time.time())))
            except pollinations_mod.AskError as exc:
                if exc.status < 500:
                    raise UpstreamError(str(exc), exc.status)
                break

        # Upstream 2: chatbotchatapp.com. Paid proxy pools first, then any
        # open proxies the operator has verified - free ones can read the
        # traffic, so they are strictly the last resort and capped.
        paid_pools = aiask_mod.parse_pools(
            _ENV.get("ASK_PROXIES"), _ENV.get("ASK_PROXY_PASSWORD")
        ) if use_proxy else []
        free_pools = _load_free_proxies() if use_proxy else []
        try:
            res = aiask_mod.ask(prompt, model=model, proxy_tries=retries + 1,
                                direct=use_proxy, pools=paid_pools,
                                free_pools=free_pools)
        except aiask_mod.QuotaExhausted:
            # Say plainly that BOTH upstreams ran out, otherwise the error reads
            # as if only one of them was tried.
            raise UpstreamError(
                "both keyless upstreams are out of anonymous quota for this "
                "IP right now (text.pollinations.ai: 402, "
                "chatbotchatapp.com: daily cap). No proxy pool is configured "
                "(ASK_PROXIES) and no verified open proxy is available "
                "(free_proxies.json), so there is no third route to try. Retry "
                "in a few minutes, or pass &wait=<seconds> to block until the "
                "anonymous window reopens.", 429)
        except aiask_mod.AskError as exc:
            raise UpstreamError(str(exc), exc.status if exc.status >= 400 else 502)
        res.update({"model": model, "cached": False,
                    "source": "chatbotchatapp.com"})
        CACHE.set(key, json.dumps(res), ttl=86400)
        return res

    @route("GET", r"/api/v1/ai/models/free")
    def ai_models_free(h, m, query):
        """The model catalogue the keyless upstream exposes (no auth).

        Generating needs a slot in the anonymous window, but the catalogue
        itself is public, so this is a reliable way to see what exists."""
        rows = pollinations_mod.models()
        want = q(query, "search")
        if want:
            needle = want.lower()
            rows = [r for r in rows
                    if needle in (r.get("id", "") + " " + r.get("description", "")).lower()]
        return {"count": len(rows), "source": "gen.pollinations.ai",
                "models": [{"id": r.get("id"), "title": r.get("title"),
                            "description": r.get("description")}
                           for r in rows[:nq(query, "limit", 50, 1, 310)]]}

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
