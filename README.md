# ApiBot — REST API scraper

REST API buat scraping data web: esports (**MPL Indonesia**), **JKT48**,
anime/manga, game, news, dan lain-lain. Pure Python stdlib — **tanpa dependency**,
RAM ~42 MB, CPU ~3% di mesin 1 core.

## Jalankan

```bash
cd /root/ApiBot
python3 api.py                        # host & port dibaca dari config.json
python3 api.py --port 18742 --host 0.0.0.0   # override
python3 api.py --gen-token            # cetak token baru
```

Token digenerate otomatis saat boot pertama dan disimpan di `config.json`
(`chmod 600`). Semua endpoint butuh auth kecuali `/health` dan
`/api/v1/catalog`.

## Auth

```bash
TOKEN=$(python3 -c "import json;print(json.load(open('/root/ApiBot/config.json'))['token'])")
curl -H "Authorization: Bearer $TOKEN" http://127.0.0.1:18742/api/v1/mpl/schedule
curl "http://127.0.0.1:18742/api/v1/mpl/standings?key=$TOKEN"
```

## Endpoint (34)

**MPL Indonesia** (scrape `id-mpl.com`)

| Endpoint | Isi |
|---|---|
| `/api/v1/mpl/schedule` | 72 match regular season: week, tanggal, jam WIB, skor, replay. `?team=ONIC` |
| `/api/v1/mpl/standings` | Klasemen. `?phase=regular-season\|playoffs` |
| `/api/v1/mpl/teams` | 9 tim + logo + nama lengkap |
| `/api/v1/mpl/team/{slug}` | Roster (nick, role) + riwayat match. `onic`, `evos`, `rrq`, ... |
| `/api/v1/mpl/match/{id}` | Detail: skor seri, per-game kill/durasi, KDA+gold+dmg+item+rune tiap pemain |

**JKT48** (situs resmi Cloudflare-walled → Google News RSS + Wikipedia)

| Endpoint | Isi |
|---|---|
| `/api/v1/jkt48/news` | Berita JKT48 terbaru. `?q=...&limit=30` |
| `/api/v1/jkt48/members` | Cari member/generasi di Wikipedia. `?q=...` |
| `/api/v1/jkt48/member/{nama}` | Ringkasan artikel member |

**Anime / Manga** (AniList, fallback otomatis kalau Jikan down)

| Endpoint | Isi |
|---|---|
| `/api/v1/anime/search?q=` | Cari anime |
| `/api/v1/anime/{id}` | Detail anime by AniList id |
| `/api/v1/anime/trending` | Anime sedang tayang |
| `/api/v1/manga/search?q=` | Cari manga |
| `/api/v1/jikan/anime/{mal_id}` | Record MyAnimeList lengkap (fallback AniList) |
| `/api/v1/jikan/top` | Top anime. `?filter=bypopularity\|airing` |

**Game**

| Endpoint | Isi |
|---|---|
| `/api/v1/game/steam/{appid}` | Detail Steam store (harga IDR) |
| `/api/v1/game/dota/heroes` | 127 hero Dota 2 |
| `/api/v1/game/dota/patch` | Patch Dota 2 |
| `/api/v1/game/valorant/agents` | 30 agent Valorant |
| `/api/v1/game/valorant/maps` | Map Valorant |
| `/api/v1/game/pokemon/{nama\|id}` | Detail Pokemon |
| `/api/v1/game/lol/champions` | 173 champion LoL (patch terbaru, nama ID) |
| `/api/v1/game/lol/items` | 870 item LoL |
| `/api/v1/game/chess/leaderboard` | Leaderboard Chess.com. `?cat=daily\|blitz\|bullet\|rapid` |
| `/api/v1/game/chess/archives/{user}` | Arsip game bulanan |

**Games / gacha** (Fandom MediaWiki, 21 game wiki, 1 request per kategori)

| Endpoint | Isi |
|---|---|
| `/api/v1/games` | Semua game wiki yang tersedia. `?genre=` |
| `/api/v1/games/{slug}` | Character/boss/item/wiki. `?category=Bosses&limit=20` |
| `/api/v1/games/{slug}/search?q=` | Cari di wiki game itu |
| `/api/v1/games/{slug}/entry/{nama}` | Satu entry: lead image + lore |

Slug: `alchemy-stars`, `arknights`, `azur-lane`, `blue-archive`, `elden-ring`,
`final-fantasy`, `fire-emblem`, `genshin`, `guardian-tales`, `honkai-starrail`,
`kingdom-hearts`, `limbus-company`, `monster-hunter`, `onmyoji`, `overwatch`,
`stardew-valley`, `terraria`, `undertale`, `warframe`, `wuthering-waves`,
`zenless-zone-zero`.

```bash
curl -H "Authorization: Bearer $TOKEN" $BASE/api/v1/games/genshin?category=Playable%20Characters
curl -H "Authorization: Bearer $TOKEN" $BASE/api/v1/games/elden-ring/entry/Malenia
```

**Liquid / T1 esports** (teamliquid.com, server-rendered)

| Endpoint | Isi |
|---|---|
| `/api/v1/liquid/divisions` | 20 divisi Team Liquid (MLBB TLID/TLPH, Valorant, CS2, LoL, Dota 2, Apex, R6, OW2, Chess, SC2, dll.) |
| `/api/v1/liquid/roster?division=mlbb/tlid` | Roster per divisi (nama, role/team slot, gambar). Lihat `/api/v1/liquid/divisions` |
| `/api/v1/liquid/roster/all` | Semua roster 20 divisi (1 panggilan, 20 upstream request) |
| `/api/v1/liquid/news?q=Team%20Liquid&limit=15` | Artikel teamliquid.com + press via Google News RSS |

**AI / ML** (tanpa API key, tanpa signup, tanpa biaya — semua anonymous)

| Endpoint | Isi |
|---|---|
| `/api/v1/ai/models?search=&task=&limit=20` | Trending Hugging Face models. `?search=llama`, `?task=text-generation` |
| `/api/v1/ai/papers?limit=20` | Hugging Face Daily Papers (arXiv AI/ML) |
| `/api/v1/ai/catalogue?provider=&limit=40` | OpenRouter model catalogue (context, per-1M USD, reasoning). `?provider=anthropic` |
| `/api/v1/ai/news?q=AI&limit=20` | Hacker News + Google News RSS |

**AI — tanya model (butuh proxy buat kuota)** ⚠️

| Endpoint | Isi |
|---|---|
| `/api/v1/ai/ask?prompt=...&model=gpt-5` | Tanya AI, jawaban di-cache 24 jam per prompt |
| `&model=` | `gpt-5`, `gpt-6`, `deepseek-v4`, `glm-5.3`, `qwen3.8`, `mimo-v2.6`, `minimax-m3` |
| `&retries=0..4` | berapa kali retry tiap proxy (default 1) |
| `&proxy=0` | lewati koneksi direct, langsung ke pool |

Sumber: **chatbotchatapp.com** — anonymous, tanpa akun, tanpa key. Tapi ada
batas per IP: 5 request per window + kuota harian (nilai dobok nggak diumumkan,
teramati 5). Karena itu urutannya:

1. **Cache 24 jam** — prompt yang sama cuma sekali panggil upstream
2. **Direct** — cepat (3-5 detik) selama kuota harian belum habis
3. **Proxy pool** — IP egress dirotasi, jadi lewat batas harian, tapi lambat

Konfigurasi proxy (env var, **nggak pernah** masuk `config.json` atau git):

```bash
export ASK_PROXIES="mob-id@gw.proxyrise.com:443,mob-sg@gw.proxyrise.com:443"
export ASK_PROXY_PASSWORD="password-mu"
export ASK_PROXY_TIMEOUT=45        # detik per percobaan proxy (default 60)
export ASK_DIRECT=0                # lewati direct, langsung ke proxy
```

Tanpa `ASK_PROXIES`, endpoint ini tetap jalan selama kuota harian IP server
belum habis; setelah itu balas **429**. Semua kegagalan balas **503** — client
nggak pernah nunggu lebih dari `ASK_PROXY_TIMEOUT`.

> Di Vercel (serverless)_atur env var yang sama di Project Settings → Env Vars.
> Cache 8MB per instance nggak persisten, jadi prompt yang sering diulang akan
> request baru tiap kali.

**AI — pure HTML scrape (nol JSON API)**

| Endpoint | Isi |
|---|---|
| `/api/v1/ai/scrape/models?sort=trending\|downloads\|likes&task=&limit=30` | Grid HTML Hugging Face: id, likes, task, param count, "updated N ago" |
| `/api/v1/ai/scrape/papers?limit=20` | HF Daily Papers dari `data-props` JSON di halaman (43 paper/hari) |
| `/api/v1/ai/scrape/ollama?limit=40` | Ollama library dari HTML: nama model + pull count |

**MLBB** (scrape wiki Fandom — API pihak ketiga sudah mati)

| Endpoint | Isi |
|---|---|
| `/api/v1/mlbb/heroes` | 133 hero: title, role, specialty, lane, region, tanggal rilis. `?role=Tank\|Assassin\|Mage\|...` |
| `/api/v1/mlbb/hero/{nama}` | Satu hero: data tabel + lore (nama asli, umur, asal, story) |

**Lain-lain**

| Endpoint | Isi |
|---|---|
| `/api/v1/news/{query}` | Berita apa pun via Google News RSS |
| `/api/v1/wiki/search?q=` | Cari di Wikipedia ID |
| `/api/v1/wiki/page/{judul}` | Ringkasan artikel Wikipedia |
| `/api/v1/country/{kode}` | Info negara by ISO code |
| `/api/v1/book/{judul}` | Cari buku (Open Library) |
| `/api/v1/tv/{judul}` | Cari serial TV (TVMaze) |
| `/api/v1/tech/news` | Hacker News top stories |
| `/api/v1/fact/cat` | Fakta kucing random |

Plus `/api/v1/catalog` (daftar semua endpoint) dan `/api/v1/openapi.json`.

## Port

`18742` (bukan 8080). Ubah di `config.json` (`host`/`port`).

## Resource budget

| Setting | Default | Arti |
|---|---|---|
| `cache_max_bytes` | 8 MB | cache TTL+LRU, tidak pernah tumbuh |
| `cache_max_entries` | 400 | batas jumlah entri |
| `max_concurrency` | 6 | fetch upstream paralel maksimum (sisanya antre) |
| `max_upstream_bytes` | 12 MB | tolak respons upstream lebih besar |
| `upstream_timeout` | 15 s | timeout per fetch |
| rate limit | per-host | token bucket, mis. AniList 40/menit, id-mpl 20/menit |

Terukur: **CPU 2.9% dari 1 core**, **RAM 42→43 MB** saat 48 request cache-miss
dengan 6 thread paralel. Service idle: ~11 MB.

## Auto-start

Jalan sebagai systemd service (`/etc/systemd/system/apibot.service`):
`systemctl {status,restart,stop} apibot` — enabled, otomatis hidup saat reboot.
Batas resource dipasang di unit: `MemoryHigh=150M`, `MemoryMax=200M`,
`CPUQuota=70%`.

```bash
systemctl status apibot        # cek
systemctl restart apibot       # restart
journalctl -u apibot -n 50     # log
tail -f /root/.hermes/logs/apibot.err.log
```

## Catatan

- `/api/v1/mlbb/*` memakai wiki Fandom karena API pihak ketiga
  (ml-api-psi.vercel.app) sudah balas 402 — deployment dimatikan. Wiki Fandom
  jalan tanpa key.
- Situs JKT48 (`jkt48.com`) dilindungi Cloudflare, jadi berita diambil lewat
  Google News RSS dan profil member lewat Wikipedia.
- Jikan (`api.jikan.moe`) sering balas 504; endpoint `/jikan/*` otomatis
  fallback ke AniList supaya tetap 200.
- Rate limit dan cache sama-sama dijaga di memori; tidak ada file cache, jadi
  tidak ada pertumbuhan disk.
