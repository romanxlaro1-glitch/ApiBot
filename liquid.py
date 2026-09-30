#!/usr/bin/env python3
"""
Team Liquid esports data (teamliquid.com) + T1 (t1.gg).

IMPORTANT: liquid123.com is NOT the team site any more - it is a GoDaddy
aftermarket parking page that 302s to /lander. The real site is
teamliquid.com (Webflow, server-rendered, no bot wall). tl.gg is the same site.

Webflow CMS markup is stable and self-describing, which makes it cheap to
scrape: every roster entry carries tl-element="roster_item", the team slot in
.fs-cmsfilter-field="roster", the handle in h3.cc-roster and the photo in
img[alt]. No JS execution needed.
"""

import re

TL_BASE = "https://www.teamliquid.com"
T1_BASE = "https://www.t1.gg"

# Divisions published on the site, from /games. Includes the two MLBB rosters
# (TLID = Indonesia, TLPH = Philippines), which is the connection to the MPL
# endpoints elsewhere in this API.
TL_DIVISIONS = [
    ("mlbb/tlid", "Mobile Legends: Bang Bang (Indonesia)"),
    ("mlbb/tlph", "Mobile Legends: Bang Bang (Philippines)"),
    ("valorant/brazil", "Valorant - Brazil"),
    ("valorant/emea", "Valorant - EMEA"),
    ("valorant/valorant-academy", "Valorant Academy"),
    ("league/lcs", "League of Legends - LCS"),
    ("cs", "Counter-Strike 2"),
    ("dota2", "Dota 2"),
    ("apex-legends", "Apex Legends"),
    ("rainbow-six", "Rainbow Six Siege"),
    ("overwatch", "Overwatch 2"),
    ("pubg", "PUBG"),
    ("quake", "Quake"),
    ("chess", "Chess"),
    ("crossfire", "CrossFire"),
    ("delta-force", "Delta Force"),
    ("fgc", "Fighting Game Collective"),
    ("rts/sc2", "StarCraft II"),
    ("trackmania", "Trackmania"),
    ("wow", "World of Warcraft"),
]

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def _txt(s):
    if not s:
        return ""
    return _WS.sub(" ", _TAG.sub(" ", s)).replace("&amp;", "&") \
        .replace("&#x27;", "'").replace("&nbsp;", " ") \
        .replace("&quot;", '"').strip()


# --------------------------------------------------------------------------
# teamliquid.com
# --------------------------------------------------------------------------
def parse_divisions(html):
    """The division list + descriptions shown on /games."""
    out, seen = [], set()
    for href in re.findall(r'href="(/games/[^"#?]+)"', html):
        if href in seen:
            continue
        seen.add(href)
        slug = href[len("/games/"):].strip("/")
        pretty = dict(TL_DIVISIONS).get(slug, slug.replace("-", " ").title())
        out.append({"slug": slug, "name": pretty, "url": TL_BASE + href})
    return out


def parse_roster(html, slug=None):
    """Roster entries from a division page.

    Two markups are in use and both are handled:
      * MLBB pages  - <div tl-element="roster_item"> with a .role-name tag
                       (Main Roster / Academy) and h3.cc-roster
      * other pages - <div class="swiper-slide cc-roster w-dyn-item"> with
                       h3.h2 and no role tag
    Both wrap the same person_card, so matching on that is enough.
    """
    people, seen = [], set()
    for block in re.findall(
            r'<div[^>]*class="[^"]*person_card[^"]*"(.*?)(?=<div[^>]*class="[^"]*person_card|'
            r'<div[^>]*tl-element="roster_item"|$)', html, re.S):
        name = None
        m = re.search(r'<h3[^>]*class="[^"]*h2[^"]*"[^>]*>(.*?)</h3>', block, re.S)
        if m:
            name = _txt(m.group(1))
        if not name:
            m = re.search(r'alt="(?:Team Liquid\s+)?([^"]{2,40}?)(?:\s+\w{3,12})?"'
                          r'\s+class="[^"]*u-img-cover', block)
            if m:
                name = _txt(m.group(1))
        if not name or len(name) > 40 or name in seen:
            continue
        team = None
        m = re.search(r'class="role-name"[^>]*>(.*?)</div>', block, re.S)
        if m:
            team = _txt(m.group(1)) or None
        img = None
        for u in re.findall(r'<img[^>]*src="([^"]+)"[^>]*>', block):
            if "placeholder" not in u:
                img = u
                break
        country = None
        m = re.search(r'cc-country[^>]*>(.*?)</', block, re.S)
        if m:
            country = _txt(m.group(1)) or None
        seen.add(name)
        people.append({
            "name": name,
            "team": team,
            "country": country,
            "image": img,
            "game": dict(TL_DIVISIONS).get(slug) if slug else None,
        })
    return people


def parse_articles(html, base=TL_BASE):
    """News/article cards from /articles.

    A card is <a href="/articles/slug" class="u-link-cover cc-z2"> whose body
    starts with the cover image; the headline is a heading further inside the
    card and the date is plain text. So the card is delimited by the NEXT
    article href, not by the <a> closing tag.
    """
    hrefs = sorted(set(re.findall(r'href="(/articles/[^"#?]+)"', html)))
    out = []
    for i, href in enumerate(hrefs):
        start = html.find('href="%s"' % href)
        end = html.find('href="%s"' % hrefs[i + 1]) if i + 1 < len(hrefs) \
            else start + 6000
        card = html[start:end if end > start else start + 6000]
        title = None
        for m in re.finditer(r'<h[1-6][^>]*>(.*?)</h[1-6]>', card, re.S):
            t = _txt(m.group(1))
            if len(t) > 8:
                title = t[:160]
                break
        if not title:
            # fallback: slug is descriptive enough to stand in
            title = href[len("/articles/"):].replace("-", " ").capitalize()
        date = None
        m = re.search(r"(\w{3,9}\s+\d{1,2},\s+\d{4})", card)
        if m:
            date = m.group(1)
        out.append({"title": title, "date": date, "url": base + href,
                    "slug": href[len("/articles/"):]})
    return out


# --------------------------------------------------------------------------
# t1.gg
# --------------------------------------------------------------------------
def parse_t1_teams(html):
    """T1 roster sections (/teams)."""
    out = []
    for m in re.finditer(
            r'<div[^>]*class="[^"]*team[^"]*"[^>]*>(.{0,6000}?)</div>\s*</div>', html, re.S):
        seg = m.group(1)
        names = [_txt(x) for x in re.findall(r'>([A-Z][a-zA-Z\'\.\- ]{1,22})</h\d>', seg)]
        names = [n for n in names if n and n.lower() not in
                 ("teams", "about", "news", "shop", "community")]
        if names:
            out.append({"squad": _txt(seg[:60]) or None, "players": names})
    return out


def parse_t1_news(html, base=T1_BASE):
    out, seen = [], set()
    for href, title in re.findall(r'href="(/news/[^"#?]+)"[^>]*>(.{0,200}?)</a>',
                                  html, re.S):
        t = _txt(title)
        if t and len(t) > 8 and href not in seen:
            seen.add(href)
            out.append({"title": t[:160], "url": base + href})
    return out
