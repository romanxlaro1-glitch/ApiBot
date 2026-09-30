#!/usr/bin/env python3
"""
Ask chatbotchatapp.com's free chat, anonymously, from the server.

No account, no API key. The site is a Laravel app: you GET the page for a
CSRF token + session cookie, POST /api/get-timestamp for a server timestamp,
derive the request id the same way the shipped JS does, then POST /api/mai
and read an SSE stream.

    id = md5( "".join(k+v) for the {timestamp,nonce,messages} seed
              + "keyTokenXXXXXXYYYvv1" )

"XXXXXXYYY" is literally what the client's own JS uses - it is not a secret.

Two limits matter and both are per egress IP:
  * X-RateLimit-Limit: 5 per window
  * dailyChatLimitOfGuest - a hard daily cap, undocumented value (observed 5)

Because the cap is per-IP, a rotating proxy bypasses it. So the order here is:
direct first (fast, 3-5s), and only on a quota failure fall back to a proxy
pool. Proxies are slow and flaky, so every proxy attempt is bounded and the
caller gets an honest error rather than a multi-minute hang.

Configuration (environment):
  ASK_PROXIES   comma-separated pools, "user@host:port,user@host:port".
                "user:pass@host:port" is also accepted.
  ASK_PROXY_PASSWORD
                shared password when ASK_PROXIES uses the "user@host:port"
                short form. Passwords are never read from config.json and are
                never written to disk by this module.
  ASK_PROXY_TIMEOUT  seconds per proxy attempt (default 60)
  ASK_DIRECT    "0" to skip the direct attempt and go straight to proxies.
"""

import base64
import hashlib
import http.cookiejar
import json
import os
import random
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
BASE = "https://chatbotchatapp.com"
NONCE_TPL = "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx"
MODELS = {
    "gpt-5": "model-gpt-5", "gpt-6": "model-gpt-6",
    "deepseek-v4": "model-deepseek-v4", "glm-5.3": "model-glm-5-3",
    "minimax-m3": "model-minimax-m3", "mimo-v2.6": "model-mimo-v2-6",
    "qwen3.8": "model-qwen3-8",
}


class AskError(Exception):
    def __init__(self, message, code="upstream", status=502, detail=None):
        Exception.__init__(self, message)
        self.code = code
        self.status = status
        self.detail = detail


class QuotaExhausted(AskError):
    """The upstream refused because this egress IP is out of daily chats."""

    def __init__(self):
        AskError.__init__(self, "daily chat limit reached for this IP",
                          code="quota", status=429)


def _nonce():
    out = []
    for ch in NONCE_TPL:
        v = int(random.random() * 16)
        out.append(hex(v)[2:] if ch == "x" else hex(8 + int(random.random() * 4))[2:])
    return "".join(out)


def _proxy_auth(user, pw):
    return base64.b64encode(("%s:%s" % (user, pw)).encode()).decode()


def parse_pools(spec, password):
    """Turn "user@host:port" / "user:pass@host:port" into opener arguments."""
    pools = []
    for chunk in (spec or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        cred, _, hp = chunk.rpartition("@")
        if not cred:
            continue
        if ":" in cred:
            user, _, pw = cred.partition(":")
        else:
            user, pw = cred, (password or "")
        if not pw:
            continue
        host, _, port = hp.partition(":")
        pools.append((host + ":" + (port or "443"), _proxy_auth(user, pw),
                      user))
    return pools


def _opener(auth, timeout):
    cj = http.cookiejar.CookieJar()
    if auth:
        op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj),
            urllib.request.ProxyHandler({"https": auth[0]}))
        op.addheaders = [("User-Agent", UA), ("Accept", "*/*"),
                         ("Proxy-Authorization", "Basic " + auth[1])]
    else:
        op = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj),
            urllib.request.ProxyHandler({}))
        op.addheaders = [("User-Agent", UA), ("Accept", "*/*")]
    return op, cj


def _ask_once(msg, model, auth, timeout):
    """One full attempt. Returns (answer, country_code). Raises on failure."""
    op, cj = _opener(auth, timeout)
    page = op.open(BASE + "/", timeout=timeout).read().decode("utf8", "ignore")
    m = re.search(r'<meta name="csrf-token" content="([^"]+)"', page)
    if not m:
        raise AskError("no csrf token in the landing page", code="layout")
    csrf = m.group(1)
    xsrf = urllib.parse.unquote(
        [c.value for c in cj if c.name == "XSRF-TOKEN"][0])

    def post(url, data=None, hdrs=None):
        h = {"User-Agent": UA, "Referer": BASE + "/", "Origin": BASE,
             "X-Requested-With": "XMLHttpRequest", "X-CSRF-TOKEN": csrf,
             "X-XSRF-TOKEN": xsrf, "Content-Type": "application/json",
             "Accept": "*/*"}
        if auth:
            h["Proxy-Authorization"] = "Basic " + auth[1]
        if hdrs:
            h.update(hdrs)
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, headers=h, method="POST")
        with op.open(req, timeout=timeout) as f:
            return f.status, f.read().decode("utf8", "ignore"), dict(f.headers)

    try:
        info = json.loads(post(BASE + "/api/get-timestamp")[1])
        ts = info["timestamp"]
    except (ValueError, KeyError):
        raise AskError("could not read a server timestamp", code="layout")
    cc = (info.get("ipInfo") or {}).get("country_code2")

    seed = {"timestamp": ts, "nonce": _nonce(), "messages": msg}
    blob = "".join(k + str(v) for k, v in seed.items())
    key = hashlib.md5((blob + "keyToken" + "XXXXXXYYY" + "vv1").encode()).hexdigest()
    status, out, hd = post(
        BASE + "/api/mai",
        {"id": key, "timestamp": ts, "nonce": seed["nonce"],
         "messages": [{"role": "user", "content": msg}],
         "url": BASE + "/", "modal": model},
        hdrs={"Accept": "text/event-stream"})

    if "dailyChatLimitOfGuest" in out:
        raise QuotaExhausted()
    if status != 200:
        raise AskError("upstream returned HTTP %d" % status,
                       code="upstream", status=502)
    buf = ""
    for line in out.split("\n"):
        if line.startswith("data: ") and "[DONE]" not in line:
            try:
                d = json.loads(line[6:])
            except ValueError:
                continue
            for ch in d.get("choices") or []:
                buf += (ch.get("delta") or {}).get("content") or ""
    if not buf.strip():
        raise AskError("upstream returned an empty answer", code="empty")
    return buf.strip(), cc


def ask(prompt, model="gpt-5", proxy_tries=1, direct=True,
        proxy_timeout=None, direct_timeout=30, pools=None):
    """Ask the model, preferring a direct connection and falling back to pools.

    Returns ``{"answer", "via", "country", "attempts", "elapsed"}``. Raises
    AskError - QuotaExhausted only if every route hit the daily cap.
    """
    if not prompt or not str(prompt).strip():
        raise AskError("prompt is empty", code="bad_request", status=400)
    if len(prompt) > 4000:
        raise AskError("prompt longer than 4000 characters", code="bad_request",
                       status=400)
    model_id = MODELS.get(str(model).lower())
    if not model_id:
        raise AskError("unknown model %r; try one of: %s"
                       % (model, ", ".join(sorted(MODELS))), code="bad_request",
                       status=400)
    if pools is None:
        pools = parse_pools(os.environ.get("ASK_PROXIES"),
                            os.environ.get("ASK_PROXY_PASSWORD"))
    if proxy_timeout is None:
        try:
            proxy_timeout = int(os.environ.get("ASK_PROXY_TIMEOUT", "60"))
        except ValueError:
            proxy_timeout = 60

    routes = []
    if direct and os.environ.get("ASK_DIRECT", "1") != "0":
        routes.append((None, "direct"))
    for hostport, auth, user in pools:
        routes.append(((hostport, auth), "proxy:%s" % user))
    routes = routes[:1] if not direct and not pools else routes

    started = time.time()
    attempts, last = 0, None
    for auth, label in routes:
        for _ in range(max(1, proxy_tries)):
            attempts += 1
            t0 = time.time()
            try:
                # direct is capped short so a hung socket cannot eat the
                # whole budget; proxies get their own, longer cap.
                limit = proxy_timeout if auth else direct_timeout
                ans, cc = _ask_once(prompt, model_id, auth, limit)
                return {"answer": ans, "via": label, "country": cc,
                        "attempts": attempts,
                        "elapsed": round(time.time() - started, 2),
                        "route_seconds": round(time.time() - t0, 2)}
            except QuotaExhausted as exc:
                last = exc
                break                      # rotating pool may not help, but try next
            except (urllib.error.URLError, socket.timeout, OSError) as exc:
                last = exc
                continue
            except AskError as exc:
                last = exc
                if exc.code in ("bad_request", "layout"):
                    raise
                continue
            if attempts >= 12:
                break
    if isinstance(last, QuotaExhausted):
        raise last
    if not routes:
        raise QuotaExhausted()
    raise AskError("every route failed: %s" % (last or "unknown"),
                   code="unavailable", status=503)
