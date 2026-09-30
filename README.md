# ApiBot

Eighty keyless REST endpoints for public data that normally needs one scraper
per site: MPL ID match schedules and standings, JKT48 member profiles, Mobile
Legends hero stats, game wikis, seven playable games, AI model catalogues, a
live anonymous AI chat endpoint, and phone/country data.

Pure Python standard library. No dependencies, no API keys, no accounts. Every
endpoint is either a scrape of a public page or a call to an upstream that
does not require authentication.

## Install

```bash
git clone https://github.com/romanxlaro1-glitch/ApiBot.git
cd ApiBot
cp config.example.json config.json     # set your own token
python3 api.py
```

Host and port come from `config.json`; `python3 api.py --port 9000` overrides
them, and `--gen-token` prints a fresh one. `config.json` is gitignored. The
token in it is the access token for this server, not a key for any upstream.

## Auth

```bash
TOKEN=$(python3 -c "import json;print(json.load(open('config.json'))['token'])")
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:18742/api/v1/mpl/schedule
curl "http://127.0.0.1:18742/api/v1/mpl/standings?key=$TOKEN"
```

`/health` and `/api/v1/catalog` are public.

## Playable games

Seven games that are actually played, not looked up. State lives in the
server's LRU cache, so a session survives across requests without a database
and expires after six hours - the bot keeps the id, the server forgets the
game. Every response carries a `next` field naming the URL for the following
move, so a bot can drive a game without parsing prose.

| Endpoint | Returns |
|---|---|
| `/api/v1/play/list` | The games and how many sessions are alive |
| `/api/v1/play/tictactoe` | New game, 3x3 to 15x15. `?size=5&first=O` |
| `/api/v1/play/tictactoe/move` | Place a mark. `?session=&cell=1..N` (1-based) |
| `/api/v1/play/word/start` | Word guessing, 2,323 words or 191 Indonesian. `?length=5&lang=id` |
| `/api/v1/play/word/guess` | One letter. `?session=&letter=a` |
| `/api/v1/play/word/solve` | Give up and reveal |
| `/api/v1/play/riddle/start` | A riddle with a three-step hint ladder. `?lang=en\|id` |
| `/api/v1/play/riddle/hint` | Next hint, each more direct than the last |
| `/api/v1/play/riddle/answer` | Submit. `?answer=towel` |
| `/api/v1/play/gacha/pull` | 1-20 pulls, four rarities, 1% SSR with a hard pity at 40 |
| `/api/v1/play/dice` | Dice notation. `?dice=2d6+3`, `?dice=d20`, `?dice=2d20+5-3` |
| `/api/v1/play/puzzle` | Sliding puzzle, 2x2 to 6x6. Every board is solvable |
| `/api/v1/play/puzzle/move` | Slide a tile. `?session=&tile=0..N-1` |
| `/api/v1/play/puzzle/hint` | Which tile can move toward its place |
| `/api/v1/play/mines` | Minesweeper, 5x5 to 30x30. The first click is always safe |
| `/api/v1/play/mines/reveal` | Open a cell, flood fill included |
| `/api/v1/play/drop` | Forget a session |

Two details worth knowing if you are building the bot side:

- **Tic-tac-toe cells are 1-based** (`cell=1` is the top-left). A 0-based 4
  and a 1-based 4 are different squares and 4 is in range either way, so
  accepting both silently is a bug; pass `zero_based=True` in Python if you
  really want indices.
- **Dice accepts what people actually type.** In a query string a literal
  `+` arrives as a space, so `?dice=3d6+2` reaches the parser as `3d6 2`.
  Stripping spaces blindly would make that sixty-two-sided dice, so the
  parser reconstructs the sign instead. `2d6 x 3`, `2d6*3` and `2d6 + 3` all
  work; `d20d20` and `1d1` are rejected rather than guessed at.

Puzzle solvability is a real inversion-parity test, not a shuffle count: the
generator swaps two tiles in different rows when the parity is wrong, because
swapping inside one row does not change it.

## Gaming

**MPL Indonesia** — scraped from `id-mpl.com`

| Endpoint | Returns |
|---|---|
| `/api/v1/mpl/schedule` | 72 regular-season matches: week, date, WIB time, score, replay. `?team=ONIC` |
| `/api/v1/mpl/standings` | Standings. `?phase=regular-season\|playoffs` |
| `/api/v1/mpl/teams` | 9 teams with logo and full name |
| `/api/v1/mpl/team/{slug}` | Roster (nick, role) and match history. `onic`, `evos`, `rrq`, … |
| `/api/v1/mpl/match/{id}` | Series score, per-game kills and duration, KDA/gold/damage/items/runes per player |

**JKT48** — the official site and the wiki's HTML pages are both behind
Cloudflare, but the wiki's MediaWiki `api.php` is not, so the member roster
comes from there. Indonesian Wikipedia is queried alongside for prose.

| Endpoint | Returns |
|---|---|
| `/api/v1/jkt48/roster` | All 167 member names. `?category=JKT48V` for the idols |
| `/api/v1/jkt48/member?name=` | Full profile: birth name, nickname, birthday, blood type, zodiac, height, generation, team, join dates, social links. `&wiki=1` adds the Indonesian Wikipedia lead |
| `/api/v1/jkt48/member/search?q=` | Search the roster by name, nickname, generation or team |
| `/api/v1/jkt48/news` | Latest member news via Google News RSS. `?q=...&limit=30` |

Field coverage across the 167-member roster: generation 80%, team 71%,
nickname 65%, blood type 43%, zodiac 44%, height 44%, social links 78%.
Not every page on the wiki carries a full infobox, so the gaps are the wiki's,
not the parser's.

**Mobile Legends** — Fandom wiki, because the third-party API now returns 402

| Endpoint | Returns |
|---|---|
| `/api/v1/mlbb/heroes` | 133 heroes: title, role, specialty, lane, region, release date. `?role=Tank\|Assassin\|Mage` |
| `/api/v1/mlbb/hero/{name}` | Single hero: table data and lore |

**Liquid / Team Liquid** — server-rendered teamliquid.com

| Endpoint | Returns |
|---|---|
| `/api/v1/liquid/divisions` | 20 divisions (MLBB TLID/TLPH, Valorant, CS2, LoL, Dota 2, Apex, R6, OW2, Chess, SC2, …) |
| `/api/v1/liquid/roster?division=mlbb/tlid` | Roster per division |
| `/api/v1/liquid/roster/all` | All 20 rosters in one call |
| `/api/v1/liquid/news?q=Team%20Liquid&limit=15` | Articles plus press via Google News RSS |

**Game wikis** — 21 Fandom MediaWiki sources, one request per category

| Endpoint | Returns |
|---|---|
| `/api/v1/games` | Available game wikis. `?genre=` |
| `/api/v1/games/{slug}` | Characters/bosses/items. `?category=Bosses&limit=20` |
| `/api/v1/games/{slug}/search?q=` | Search one wiki |
| `/api/v1/games/{slug}/entry/{name}` | One entry: lead image and lore |

Slugs: `alchemy-stars`, `arknights`, `azur-lane`, `blue-archive`, `elden-ring`,
`final-fantasy`, `fire-emblem`, `genshin`, `guardian-tales`, `honkai-starrail`,
`kingdom-hearts`, `limbus-company`, `monster-hunter`, `onmyoji`, `overwatch`,
`stardew-valley`, `terraria`, `undertale`, `warframe`, `wuthering-waves`,
`zenless-zone-zero`.

**Other game data**

| Endpoint | Returns |
|---|---|
| `/api/v1/game/steam/{appid}` | Steam store detail, IDR price |
| `/api/v1/game/dota/heroes`, `/game/dota/patch` | 127 heroes, current patch |
| `/api/v1/game/valorant/agents`, `/game/valorant/maps` | 30 agents, maps |
| `/api/v1/game/pokemon/{name\|id}` | Pokémon detail |
| `/api/v1/game/lol/champions`, `/game/lol/items` | 173 champions, 870 items |
| `/api/v1/game/chess/leaderboard` | Chess.com. `?cat=daily\|blitz\|bullet\|rapid` |
| `/api/v1/game/chess/archives/{user}` | Monthly game archive |

## Anime and manga

AniList, with automatic fallback to Jikan when it returns 504.

| Endpoint | Returns |
|---|---|
| `/api/v1/anime/search?q=` | Anime search |
| `/api/v1/anime/{id}` | Detail by AniList id |
| `/api/v1/anime/trending` | Currently airing |
| `/api/v1/manga/search?q=` | Manga search |
| `/api/v1/jikan/anime/{mal_id}` | Full MyAnimeList record |
| `/api/v1/jikan/top` | Top anime. `?filter=bypopularity\|airing` |

## AI

| Endpoint | Returns |
|---|---|
| `/api/v1/ai/models` | Trending Hugging Face models. `?search=llama`, `?task=text-generation` |
| `/api/v1/ai/papers` | Hugging Face Daily Papers (arXiv) |
| `/api/v1/ai/catalogue` | Model catalogue with context window and pricing. `?provider=anthropic` |
| `/api/v1/ai/news?q=AI&limit=20` | Hacker News plus Google News RSS |
| `/api/v1/ai/tools` | 866 tools and 437 models from rewind.ai |
| `/api/v1/ai/scrape/models` | HTML grid scrape of Hugging Face: id, likes, task, parameter count, "updated N ago" |
| `/api/v1/ai/scrape/papers` | Daily Papers from the `data-props` JSON embedded in the page |
| `/api/v1/ai/scrape/ollama` | Ollama library: model name and pull count |

### Asking a model

`GET /api/v1/ai/ask?prompt=...&model=gpt-5`

No account anywhere, no API key. Two keyless upstreams are tried in order:

1. **text.pollinations.ai** - a plain `GET` with the prompt in the path.
   Answers in 1-5 seconds, needs no proxy. Two things it does not document:
   the request must carry `Referer: https://text.pollinations.ai/`, and
   anonymous use is metered per IP at roughly one request per cooldown window,
   so a burst right after a success is refused with `402`.
2. **chatbotchatapp.com** - also anonymous, but capped at 5 chats per window per
   egress IP plus an undocumented daily cap, so it needs a rotating proxy.

If both are out of quota the endpoint returns 429 and says so, rather than
reporting a failure that did not happen. Results are cached 24 hours per
prompt, so repeating a question is free and instant.

`&retries=0..4` sets how many times a failed proxy attempt is retried, and
`&proxy=0` skips the direct attempt and goes straight to the pools.

`&wait=0..300` makes the endpoint block instead of giving up. The anonymous
window on the first upstream measured a steady 60.5 second cooldown, so
`&wait=120` will poll every 12 seconds until a slot opens and then return the
answer rather than a 429. The default is 0, which never blocks. The response
reports how many polls it took in `waited_polls`.

`GET /api/v1/ai/models/free` lists the 310 models the keyless upstream exposes.
The catalogue is public even when generation is not, so it is a reliable way to
see what exists. `?search=llama` filters it.

### Proxy configuration

Only the second upstream uses a proxy. Free proxy lists are deliberately not
used.

Copy `.env.example` to `.env` (mode 600, gitignored):

```
ASK_PROXIES=user1@host:port,user2@host:port
ASK_PROXY_PASSWORD=your-password
ASK_PROXY_TIMEOUT=60
POLLINATIONS_TIMEOUT=45
```

`ASK_PROXIES` accepts `user@host:port` (password from `ASK_PROXY_PASSWORD`) or
`user:pass@host:port`. Both HTTP CONNECT and SOCKS5 vendors work, and
`socks5.py` implements SOCKS5 because the standard library has no SOCKS client.

Rotating the proxy password: edit `.env`, then `systemctl restart apibot`.

### Open proxies

`/api/v1/ai/ask` can fall back to open proxies, and for the first upstream
that is genuinely useful rather than merely desperate: the anonymous window on
`text.pollinations.ai` is **per exit IP**, so a different IP is a different
window. When the direct window is shut, a working open proxy is the difference
between an answer and a 429.

`refresh_free_proxies.py` builds the list. It matters that it probes in two
stages, because most of these lists are hosts that are not proxies any more:

```
$ python3 refresh_free_proxies.py --sample 900
collected 106177 unique candidates
stage 1: 287/900 accept TCP (40s)
stage 2: 1/900 actually proxy (14s)
```

**Roughly 0.1% of advertised free proxies complete a real request.** A TCP
connect is not evidence of anything; only a completed proxied request is. The
script keeps the second list, and never overwrites the file with fewer entries
than `--min`.

Treat the output as a cache with a short shelf life. In testing, one proxy
answered a real request and was refusing `CONNECT` a few minutes later. The
route reuses whatever is in `free_proxies.json` and caps it at eight
candidates, tries them only after the direct attempt has failed, and never
sends a prompt through one on the first try - a public proxy can read the
request.

Free proxies are not configured by default. Drop a `free_proxies.json` next to
the app and the route picks it up; add `&proxy=0` to a request to skip proxies
entirely.

## Phone and country data

Offline, from libphonenumber's static metadata. Nothing is sent to a carrier.

| Endpoint | Returns |
|---|---|
| `/api/v1/phone/validate?number=+628123456789&region=ID` | E.164 form, real region, length plausibility |
| `/api/v1/country/list?limit=250&offset=0` | All 206 entries: calling code, name, flag, search code |
| `/api/v1/country/detect?number=+249123456789` | Calling code, country, national part, picker search terms, verification code |

`phone/validate` accepts national and E.164 formats and resolves shared calling
codes correctly (+1 NANP, +7 RU/KZ, +376 Andorra).

`country/detect` does longest-prefix matching, which is required because 160 of
the 206 codes are three digits. It returns `target_code` — the code the chosen
option must be verified against, which is what keeps +249 Sudan from selecting
+211 Sudan Selatan. An unrecognised number falls back to `+62` with
`fallback_used: true`; a number with no digits is rejected with 400 rather than
quietly becoming Indonesia.

## Misc

| Endpoint | Returns |
|---|---|
| `/api/v1/news/{query}` | Any news topic via Google News RSS |
| `/api/v1/wiki/search?q=` | Indonesian Wikipedia search |
| `/api/v1/wiki/page/{title}` | Wikipedia article summary |
| `/api/v1/country/{code}` | Country info by ISO code |
| `/api/v1/book/{title}` | Open Library search |
| `/api/v1/tv/{title}` | TVMaze search |
| `/api/v1/tech/news` | Hacker News top stories |
| `/api/v1/fact/cat` | Random cat fact |

`/api/v1/catalog` lists every endpoint, and `/api/v1/openapi.json` is a full
OpenAPI document.

## Configuration

| Key | Default | Meaning |
|---|---|---|
| `cache_max_bytes` | 8 MB | TTL+LRU cache, bounded |
| `cache_max_entries` | 400 | Entry cap |
| `max_concurrency` | 6 | Parallel upstream fetches; the rest queue |
| `max_upstream_bytes` | 12 MB | Reject larger upstream responses |
| `upstream_timeout` | 15 s | Per-fetch timeout |

Rate limits are token buckets per upstream host, not per caller: AniList
40/min, id-mpl.com 20/min, and so on. Responses are cached in memory only, so
nothing grows on disk.

## Deploy

**systemd** — `apibot.service` is included:

```bash
cp apibot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now apibot
systemctl status apibot
```

It runs as a single process with `MemoryHigh`/`MemoryMax` and a `CPUQuota`
ceiling in the unit, and reads `.env` via `EnvironmentFile`.

**Vercel** — `vercel.json` rewrites every path to `api/index.py`. The repository
can stay private.

**GitHub Pages** is not used. It serves static files only and cannot run this
server, and it is unavailable for private repositories on the free plan.

## Notes

- The JKT48 site is behind Cloudflare, so that data comes from Google News RSS
  and Wikipedia instead.
- `api.jikan.moe` frequently returns 504, so `/api/v1/jikan/*` falls back to
  AniList to stay up.
- `/api/v1/mlbb/*` uses the Fandom wiki because the third-party API
  (`ml-api-psi.vercel.app`) now answers 402.
- The server keeps no per-user state and does not log request bodies.
