# Deploy ke GitHub

Pure stdlib, nol dependency. Repository ini **publik** dan tidak memuat satu
pun kredensial: `config.json` dan `__pycache__` ada di `.gitignore`.

## 1. Push

```bash
git init
git add .
git commit -m "ApiBot: 56 keyless endpoints (MPL/Liquid/MLBB/games/AI)"
git branch -M main
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

## 2. Vercel

Import repo dari dashboard, lalu set env var:

| Key | Value | Wajib |
|---|---|---|
| `API_TOKEN` | token random lo (`python3 -c "import secrets;print(secrets.token_urlsafe(32))"`) | ya, untuk auth |
| `ASK_PROXIES` | `user@host:port,user@host:port` | tidak, hanya untuk `/api/v1/ai/ask` |
| `ASK_PROXY_PASSWORD` | password proxy | tidak |
| `ASK_PROXY_TIMEOUT` | `45` | tidak |

`API_TOKEN` kosong = API terbuka untuk semua orang. `ASK_PROXIES` kosong =
`/ai/ask` tetap jalan selama kuota harian IP Vercel belum habis.

## 3. Self-host

```bash
python3 -c "import json,secrets; c=json.load(open('config.example.json')); c['token']=secrets.token_urlsafe(32); json.dump(c,open('config.json','w'),indent=2)"
chmod 600 config.json
python3 api.py
```

systemd: `sudo cp apibot.service /etc/systemd/system/ && sudo systemctl enable --now apibot`

## Yang perlu diketahui soal `/api/v1/ai/ask`

Satu-satunya endpoint yang memanggil model AI sungguhan, jadi satu-satunya yang
punya batasan nyata. Sumbernya chatbotchatapp.com: anonymous, tanpa akun, tanpa
API key, tapi kuota **per IP** (5 per window + batas harian). Proxy dengan IP
rotasi melewati batas itu, tapi lambat dan tidak selalu stabil.

Karena itu urutannya: cache 24 jam → direct (3-5 detik) → proxy pool. Semua
percobaan dibatasi waktunya; kegagalan mengembalikan 503, tidak pernah menggantung.
