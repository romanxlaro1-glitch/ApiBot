# ApiBot

REST API for public data that normally needs one scraper per site: MPL ID match
schedules and standings, JKT48 member data, Mobile Legends hero stats, game
wikis, AI model catalogues and papers, a live anonymous AI chat endpoint, and
phone/country data.

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

## Gaming

**MPL Indonesia** — scraped from `id-mpl.com`

| Endpoint | Returns |
|---|---|
| `/api/v1/mpl/schedule` | 72 regular-season matches: week, date, WIB time, score, replay. `?team=ONIC` |
| `/api/v1/mpl/standings` | Standings. `?phase=regular-season\|playoffs` |
| `/api/v1/mpl/teams` | 9 teams with logo and full name |
| `/api/v1/mpl/team/{slug}` | Roster (nick, role) and match history. `onic`, `evos`, `rrq`, … |
| `/api/v1/mpl/match/{id}` | Series score, per-game kills and duration, KDA/gold/damage/items/runes per player |

**JKT48** — the official site sits behind Cloudflare, so news comes from Google
News RSS and member profiles from Wikipedia

| Endpoint | Returns |
|---|---|
| `/api/v1/jkt48/news` | Latest member news. `?q=...&limit=30` |
| `/api/v1/jkt48/members` | Member/generation search. `?q=...` |
| `/api/v1/jkt48/member/{name}` | Article summary |

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

No account anywhere. The upstream is an anonymous public chat site with a
per-IP daily guest quota, so the order is:

1. **Cache, 24 hours** per prompt, so an identical question costs one request.
2. **Direct connection** — about 3-5 seconds while the daily quota holds.
3. **Proxy fallback** — rotates the egress IP to get past the daily limit, and is
   therefore slow.

Models: `gpt-5`, `gpt-6`, `deepseek-v4`, `glm-5.3`, `qwen3.8`, `mimo-v2.6`,
`minimax-m3`.

Options: `&retries=0..4` per proxy, `&proxy=0` to skip the direct attempt,
`&limit=` characters of answer.

Without `ASK_PROXIES` this endpoint still works until the server's own IP
exhausts its daily quota, after which it returns 429. When every route fails
it returns 503.

### Proxy configuration

Only this endpoint uses a proxy. Free proxy lists are deliberately not used.

Copy `.env.example` to `.env` (mode 600, gitignored):

```
ASK_PROXIES=user1@host:port,user2@host:port
ASK_PROXY_PASSWORD=your-password
ASK_PROXY_TIMEOUT=60
ASK_DIRECT=0
```

`ASK_PROXIES` accepts `user@host:host` style entries written as `user@host:port`
(the password is taken from `ASK_PROXY_PASSWORD`), or `user:pass@host:port`.
Both HTTP CONNECT and SOCKS5 vendors work — SOCKS5 is implemented in
`socks5.py` because the standard library has no SOCKS client.

On Vercel set the same variables in Project Settings → Env Vars, and note the
8 MB cache is per instance and not persistent.

Rotating the proxy password: edit `.env`, then `systemctl restart apibot`.

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
