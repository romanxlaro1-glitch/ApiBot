# Deploy ke Vercel

Struktur folder ini yang di-upload:

```
api/index.py      <- entry point Vercel (handler)
api.py            <- core server (dipakai ulang, dimuat lewat importlib)
sources.py        <- semua parser
vercel.json       <- config runtime + rewrite
requirements.txt  <- kosong (nol dependency)
```

`api/index.py` **memuat `api.py` via `importlib`**, bukan `import api` biasa — karena
folder `api/` dan file `api.py` di root sama-sama ada, dan `import` biasa akan
ambigu.

## 1. Deploy

```bash
cd ApiBot
vercel --prod
vercel env add API_TOKEN production     # masukkan token acakmu
```

Atau lewat dashboard: import repo → Settings → Environment Variables → `API_TOKEN`.

**Tanpa `API_TOKEN`, API terbuka untuk semua orang** (berguna untuk tes pertama,
langsung pasang sebelum production).

## 2. Tes

```bash
BASE=https://apibot.vercel.app
curl $BASE/health
curl $BASE/api/v1/catalog
curl -H "Authorization: Bearer $API_TOKEN" $BASE/api/v1/mpl/schedule
curl "$BASE/api/v1/mlbb/heroes?key=$API_TOKEN"
```

## 3. Batasan yang harus lo tahu

Vercel = serverless. Ini konsekuensi nyata, bukan Fear Mongering:

- **Cache tidak persisten.** Cache TTL/LRU 8MB ada di RAM proses; tiap
  invocation = instance baru, jadi cache selalu kosong antar-request. Di dalam
  satu request masih berguna (2.0% hit rate di test). Endpoint yang dipanggil
  ulang = scrape ulang.
- **IP bersama.** Ribuan project Vercel keluar dari IP yang sama. `id-mpl.com`
  dan Cloudflare (Fandom/JKT48) bisa sewaktu-waktu memblokir IP itu. Kalau
  mulai dapat 403/429, itu sebabnya — bukan parser.
- **Timeout.** `maxDuration: 60` di `vercel.json`. Endpoint paling lambat di
  test = 1.96s (`/jikan/top`), jadi masih aman 30x. Plan Hobby yang tidak punya
  `maxDuration` 60 akan ditolak — naikkan plan atau turunkan ke 30.
- **Mulai lambat (cold start).** Request pertama setelah idle menambah 1-3 detik
  Python startup.
- **Biaya.** 1.000 request/hari gratis di Hobby. Karena tiap request = 1 scrape,
  1.000 request = 1.000 scrape ke situs lain. Jangan:set `rate limit` sendiri
  kalau nanti dipakai publik.

**Yang paling aman dipakai dari Vercel:** `/mlbb/heroes` (Fandom, cepat),
`/mpl/standings`, `/mpl/teams`, `/country/*`, `/book/*`, `/anime/*`.
**Yang paling mahal:** `/mpl/match/*` (5 halaman per request),
`/mpl/team/*`, `/jikan/*`, `/game/chess/leaderboard`.

## 4. Kalau butuh yang serius

Long-running + persistent cache + IP dedicated → Railway / Render / VPS
(machine ini juga sudah jalan, tinggal `systemctl start apibot`).
