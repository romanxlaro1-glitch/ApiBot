#!/usr/bin/env python3
"""
ApiBot - REST API scraper (pure stdlib, no dependencies).

Resource-light by design:
  * ThreadingHTTPServer with a hard concurrency cap
  * TTL + LRU byte-budgeted cache (bounded, never grows)
  * Per-host token bucket so we never hammer an upstream
  * Streaming response with an upstream size cap

Run:  python3 api.py [--port 8080] [--host 0.0.0.0]
Auth: Authorization: Bearer <token>   or   ?key=<token>
      /health and /api/v1/catalog are public.
"""

import argparse
import gzip
import io
import json
import os
import re
import secrets
import sys
import threading
import time
import zlib
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import sources  # local package

# --------------------------------------------------------------------------
# config
# --------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")

DEFAULTS = {
    "host": "0.0.0.0",
    "port": 8080,
    "token": None,               # generated on first boot if null
    "cache_ttl_default": 300,    # seconds
    "cache_ttl_long": 1800,      # for near-static game data
    "cache_max_bytes": 8 * 1024 * 1024,
    "cache_max_entries": 400,
    "max_upstream_bytes": 12 * 1024 * 1024,
    "max_concurrency": 6,
    "upstream_timeout": 15,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
}

_cfg = dict(DEFAULTS)
TOKEN = ""


def load_config():
    global _cfg, TOKEN
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as fh:
                _cfg.update(json.load(fh))
        except Exception as exc:  # keep serving with defaults
            print("[warn] config.json unreadable: %s" % exc, file=sys.stderr)
    if not _cfg.get("token"):
        _cfg["token"] = secrets.token_urlsafe(32)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(_cfg, fh, indent=2)
            os.chmod(CONFIG_PATH, 0o600)
        except Exception:
            pass
    TOKEN = _cfg["token"]


# --------------------------------------------------------------------------
# cache: TTL + LRU with a hard byte budget
# --------------------------------------------------------------------------
class Cache:
    def __init__(self, max_bytes, max_entries):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.bytes = 0
        self._d = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _size(val):
        try:
            return len(json.dumps(val, ensure_ascii=False))
        except Exception:
            return 1024

    def get(self, key):
        with self._lock:
            item = self._d.get(key)
            if item is None:
                self.misses += 1
                return None
            expires, val = item
            if expires < time.time():
                self._d.pop(key, None)
                self.bytes -= self._size(val)
                self.misses += 1
                return None
            self._d.move_to_end(key)
            self.hits += 1
            return val

    def set(self, key, val, ttl):
        size = self._size(val)
        if size > self.max_bytes:
            return  # never cache something bigger than the whole budget
        with self._lock:
            if key in self._d:
                self.bytes -= self._size(self._d[key][1])
                self._d.pop(key)
            self._d[key] = (time.time() + ttl, val)
            self._d.move_to_end(key)
            self.bytes += size
            while self.bytes > self.max_bytes or len(self._d) > self.max_entries:
                _, (_, old) = self._d.popitem(last=False)
                self.bytes -= self._size(old)
                if self.bytes < 0:
                    self.bytes = 0

    def stats(self):
        with self._lock:
            total = self.hits + self.misses
            return {
                "entries": len(self._d),
                "bytes": self.bytes,
                "max_bytes": self.max_bytes,
                "max_entries": self.max_entries,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0,
            }


CACHE = Cache(DEFAULTS["cache_max_bytes"], DEFAULTS["cache_max_entries"])


# --------------------------------------------------------------------------
# per-host rate limiting (token bucket)
# --------------------------------------------------------------------------
class RateLimiter:
    """Simple token bucket keyed by host. Prevents hammering upstreams."""

    def __init__(self):
        self._buckets = {}
        self._lock = threading.Lock()

    def check(self, host, rate_per_min, burst):
        with self._lock:
            b = self._buckets.get(host)
            now = time.time()
            if b is None:
                b = {"tokens": float(burst), "ts": now}
                self._buckets[host] = b
            b["tokens"] = min(
                float(burst), b["tokens"] + (now - b["ts"]) * (rate_per_min / 60.0)
            )
            b["ts"] = now
            if b["tokens"] < 1.0:
                wait = (1.0 - b["tokens"]) / (rate_per_min / 60.0)
                return max(wait, 0.05)
            b["tokens"] -= 1.0
            return 0.0


LIMITER = RateLimiter()

# Hard cap on simultaneous upstream fetches. This is what keeps a request
# burst from spiking CPU/RAM on a small box: extra requests wait, they do not
# each open their own outbound socket + buffer.
SEM = threading.Semaphore(DEFAULTS["max_concurrency"])


# --------------------------------------------------------------------------
# http fetch
# --------------------------------------------------------------------------
class UpstreamError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def fetch(url, *, ttl=300, accept=None, rate_per_min=60, burst=6,
          method="GET", data=None, headers=None, cache_key=None,
          allow_fail_fresh=None, retries=1, backoff=0.35):
    """Fetch a URL, return (text, from_cache). Raises UpstreamError.

    One retry on a transient failure (429 / 5xx / network blip) with a short
    backoff. Two retries is not worth the latency: the caller has a fallback.
    """
    key = cache_key or ("GET|" + url)
    cached = CACHE.get(key)
    if cached is not None:
        return cached, True

    last_exc = None
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(backoff * attempt)
        try:
            with _semaphore():
                return _fetch_once(url, accept=accept, rate_per_min=rate_per_min,
                                   burst=burst, method=method, data=data,
                                   headers=headers, key=key, ttl=ttl,
                                   allow_fail_fresh=allow_fail_fresh)
        except UpstreamError as exc:
            last_exc = exc
            # 4xx (other than 429) is a real answer - do not retry
            if exc.status < 500 and exc.status != 429:
                raise
    raise last_exc


class _semaphore:
    """Bounded concurrency for outbound fetches, with a bounded wait."""

    def __init__(self, timeout=25.0):
        self.timeout = timeout

    def __enter__(self):
        if not SEM.acquire(timeout=self.timeout):
            raise UpstreamError("server busy, try again shortly", 503)
        return self

    def __exit__(self, *exc):
        SEM.release()
        return False


def _fetch_once(url, *, accept, rate_per_min, burst, method, data, headers,
                key, ttl, allow_fail_fresh):
    host = urlparse(url).netloc
    wait = LIMITER.check(host, rate_per_min, burst)
    if wait > 0:
        time.sleep(wait)

    hdrs = {
        "User-Agent": _cfg["user_agent"],
        "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "close",
    }
    if accept:
        hdrs["Accept"] = accept
    if headers:
        hdrs.update(headers)
    if data is not None:
        hdrs.setdefault("Content-Type", "application/json")

    req = Request(url, data=data, headers=hdrs, method=method)
    try:
        with urlopen(req, timeout=_cfg["upstream_timeout"]) as resp:
            raw = resp.read(_cfg["max_upstream_bytes"] + 1)
            if len(raw) > _cfg["max_upstream_bytes"]:
                raise UpstreamError("upstream response too large", 502)
            enc = (resp.headers.get("Content-Encoding") or "").lower()
            if enc == "gzip":
                raw = gzip.decompress(raw)
            elif enc == "deflate":
                try:
                    raw = zlib.decompress(raw)
                except zlib.error:
                    raw = zlib.decompress(raw, -zlib.MAX_WBITS)
            charset = "utf-8"
            ctype = resp.headers.get("Content-Type", "")
            m = re.search(r"charset=([\w-]+)", ctype, re.I)
            if m:
                charset = m.group(1)
            text = raw.decode(charset, errors="replace")
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read(2000).decode("utf-8", "replace")
        except Exception:
            pass
        if allow_fail_fresh is not None and exc.code in allow_fail_fresh:
            return allow_fail_fresh[exc.code], False
        raise UpstreamError("upstream HTTP %d: %s" % (exc.code, body[:200]),
                           502 if exc.code >= 500 else exc.code)
    except (URLError, socket_timeout_error(), OSError) as exc:
        raise UpstreamError("upstream unreachable: %s" % exc, 504)

    CACHE.set(key, text, ttl)
    return text, False


def socket_timeout_error():
    import socket
    return socket.timeout


def fetch_json(url, **kw):
    text, cached = fetch(url, accept="application/json", **kw)
    try:
        return json.loads(text), cached
    except json.JSONDecodeError as exc:
        raise UpstreamError("upstream returned invalid JSON: %s" % exc, 502)


# --------------------------------------------------------------------------
# routing
# --------------------------------------------------------------------------
ROUTES = []


def route(method, pattern, *, public=False, name=None):
    rx = re.compile("^" + pattern + "$")

    def deco(fn):
        ROUTES.append((method, rx, fn, public, name or pattern))
        return fn
    return deco


def _summary_and_description(doc):
    """Split a docstring into OpenAPI's summary and description.

    OpenAPI's summary is meant to be a complete, self-contained sentence. Taking
    only the first line of a wrapped docstring produced things like "A pity rule
    forces an SSR after" in the docs, which reads as a bug rather than a
    sentence. The first line is the summary; the rest joins into description.
    """
    if not doc:
        return {"summary": ""}
    parts = doc.rstrip("\n").splitlines()
    summary = parts[0].strip() if parts else ""
    out = {"summary": re.sub(r"\s+", " ", summary)}
    rest = [p.strip() for p in parts[1:] if p.strip()]
    if rest:
        out["description"] = re.sub(r"\s+", " ", " ".join(rest))
    return out


sources.register_routes(route, fetch, fetch_json, UpstreamError, CACHE, _cfg)


# --------------------------------------------------------------------------
# server
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "ApiBot/1.0"
    protocol_version = "HTTP/1.1"

    # ---- helpers ----
    def _send(self, status, payload, extra_headers=None):
        body = json.dumps(payload, ensure_ascii=False, indent=None).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _authed(self, query):
        if not TOKEN:
            return True
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return secrets.compare_digest(header[7:].strip(), TOKEN)
        key = (query.get("key") or [None])[0]
        if key:
            return secrets.compare_digest(key, TOKEN)
        return False

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---- verbs ----
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path).rstrip("/") or "/"
        query = parse_qs(parsed.query)

        if path in ("/", "/api"):
            return self._send(200, self._index())

        if path == "/health":
            return self._send(200, {
                "status": "ok",
                "uptime_s": round(time.time() - _BOOT, 1),
                "routes": len([r for r in ROUTES if r[0] == "GET"]),
                "cache": CACHE.stats(),
            })

        if path == "/api/v1/catalog":
            return self._send(200, self._catalog())

        if path == "/api/v1/openapi.json":
            return self._send(200, self._openapi())

        if not self._authed(query):
            return self._send(401, {"error": "unauthorized",
                                    "hint": "Authorization: Bearer <token>"})

        for method, rx, fn, _public, _name in ROUTES:
            m = rx.match(path)
            if not m:
                continue
            if not LIMITER_OK(fn, path):
                pass
            try:
                result = fn(self, m, query)
            except UpstreamError as exc:
                return self._send(exc.status, {"error": str(exc),
                                               "path": path})
            except Exception as exc:  # never leak a traceback to the client
                import traceback
                traceback.print_exc()
                return self._send(500, {"error": "internal error",
                                        "detail": str(exc)[:200]})
            if isinstance(result, tuple):
                payload, extra = result
            else:
                payload, extra = result, None
            return self._send(200, payload, extra)

        return self._send(404, {"error": "not found", "path": path,
                                "hint": "GET /api/v1/catalog"})

    # ---- documents ----
    def _index(self):
        return {
            "service": "ApiBot",
            "version": "1.0",
            "docs": "/api/v1/catalog",
            "health": "/health",
            "auth": "Bearer token required on all /api/v1/* except catalog",
        }

    def _openapi(self):
        paths = {}
        for method, _rx, fn, public, name in ROUTES:
            if method != "GET":
                continue
            path = re.sub(r"\(\?P<(\w+)>[^>]+>", r"{\1}", name)
            path = path.replace(")", "")
            params = [
                {"name": p, "in": "path", "required": True,
                 "schema": {"type": "string"}}
                for p in re.findall(r"\{(\w+)\}", path)
            ] + [
                {"name": qn, "in": "query", "required": False,
                 "schema": {"type": "string"},
                 "description": qd}
                for qn, qd in re.findall(r"\?(\w+)=([\w|\.\-]+)", fn.__doc__ or "")
            ]
            paths[path] = {
                "get": {
                    # The whole docstring, not just its first line: a summary
                    # cut mid-sentence ("A pity rule forces an SSR after") reads
                    # as a bug to anyone skimming the docs. OpenAPI has a place
                    # for the rest, so use it.
                    **_summary_and_description(fn.__doc__),
                    "security": [] if public else [{"bearerAuth": []}],
                    "parameters": params,
                    "responses": {"200": {"description": "OK"},
                                  "401": {"description": "unauthorized"},
                                  "502": {"description": "upstream error"}},
                }
            }
        return {
            "openapi": "3.0.3",
            "info": {
                "title": "ApiBot",
                "version": "1.0",
                "description": ("Scraper REST API: esports (MPL Indonesia), JKT48, "
                                "anime/manga, games, news, misc. "
                                "Send `Authorization: Bearer <token>` or `?key=<token>`."),
            },
            "servers": [{"url": "/"}],
            "components": {"securitySchemes": {"bearerAuth": {
                "type": "http", "scheme": "bearer"}}},
            "paths": dict(sorted(paths.items())),
        }

    def _catalog(self):
        groups = {}
        for method, _rx, fn, public, name in ROUTES:
            if method != "GET":
                continue
            doc = _summary_and_description(fn.__doc__ or "")["summary"]
            parts = name.split("/")
            # /api/v1/<group>/<rest...> -> group
            grp = parts[3] if len(parts) > 3 else "misc"
            pretty = "/" + "/".join(
                re.sub(r"\(\?P<[^>]+>", "{", p).replace(")", "}")
                for p in parts[1:])
            groups.setdefault(grp, []).append({
                "path": pretty, "public": public, "desc": doc,
            })
        return {
            "version": "1.0",
            "endpoint_count": sum(len(v) for v in groups.values()),
            "groups": {
                g: sorted(items, key=lambda x: x["path"])
                for g, items in sorted(groups.items())
            },
        }


def LIMITER_OK(fn, path):
    return True


_BOOT = time.time()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32


def main():
    ap = argparse.ArgumentParser(description="ApiBot - REST scraper API")
    ap.add_argument("--host", default=None)
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--gen-token", action="store_true",
                    help="print a fresh token and exit")
    args = ap.parse_args()

    if args.gen_token:
        print(secrets.token_urlsafe(32))
        return

    load_config()
    CACHE.max_bytes = _cfg["cache_max_bytes"]
    CACHE.max_entries = _cfg["cache_max_entries"]
    global SEM
    SEM = threading.Semaphore(_cfg["max_concurrency"])
    host = args.host or _cfg["host"]
    port = args.port or _cfg["port"]

    srv = Server((host, port), Handler)
    print("=" * 62)
    print(" ApiBot listening on http://%s:%d" % (host, port))
    print(" token : %s... (%d chars, config.json)"
          % (TOKEN[:6], len(TOKEN)))
    print(" routes: %d" % len([r for r in ROUTES if r[0] == "GET"]))
    print(" cache : %d KB budget / %d entries, concurrency %d"
          % (_cfg["cache_max_bytes"] // 1024, _cfg["cache_max_entries"],
             _cfg["max_concurrency"]))
    print("=" * 62)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        srv.shutdown()


if __name__ == "__main__":
    main()
