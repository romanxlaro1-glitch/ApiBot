#!/usr/bin/env python3
"""
ApiBot - Vercel serverless entry point (api/index.py).

Reuses the exact same parsers/routes as the standalone server: `api.py` and
`sources.py` sit in the project root. Those are loaded by explicit file path
(importlib) because a directory named `api/` next to a module named `api.py`
is ambiguous for the plain `import` statement.

Handler contract: Vercel passes a request dict, expects
{statusCode, headers, body}. No socket, no long-lived process.

Differences from the standalone server, and why:
  * Auth token comes from the API_TOKEN env var (config.json is not deployed).
  * The TTL/LRU cache dies with the invocation, so it is not a cross-request
    cache - the budget is cut to 1 MB. It still helps when one request touches
    the same upstream twice.
  * Upstream timeout is cut to ~8s and retries trimmed so a request fits inside
    `maxDuration` in vercel.json instead of burning the whole invocation.

Deploy:
  vercel --prod
  vercel env add API_TOKEN production
"""

import importlib.util
import json
import os
import re
import secrets
import sys
import threading
import time
from urllib.parse import unquote, urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _load(name, filename):
    """Load a root-level module by path, immune to the api/ vs api.py clash."""
    path = os.path.join(ROOT, filename)
    if not os.path.exists(path):
        raise RuntimeError("missing %s (expected at %s)" % (filename, path))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


core = _load("apibot_core", "api.py")

# --- serverless-safe runtime limits -----------------------------------------
core._cfg["upstream_timeout"] = int(os.environ.get("UPSTREAM_TIMEOUT", "8"))
core._cfg["max_concurrency"] = 4
core.CACHE.max_bytes = 1 * 1024 * 1024      # per-invocation only
core.CACHE.max_entries = 60
core.SEM = threading.Semaphore(4)

TOKEN = (os.environ.get("API_TOKEN") or "").strip()
PUBLIC = {"/", "/api", "/health", "/api/v1/catalog", "/api/v1/openapi.json"}
_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "X-Content-Type-Options": "nosniff",
}
_START = time.time()
_CATALOG = None
_OPENAPI = None


def _json(status, payload, extra=None):
    body = json.dumps(payload, ensure_ascii=False, default=str)
    headers = dict(_CORS)
    headers["Content-Type"] = "application/json; charset=utf-8"
    if extra:
        headers.update(extra)
    return {"statusCode": status, "headers": headers, "body": body}


def _authed(headers, query):
    """No token configured -> open access (handy on a first deploy)."""
    if not TOKEN:
        return True
    raw = ""
    for k, v in (headers or {}).items():
        if k.lower() == "authorization":
            raw = v or ""
            break
    if raw.startswith("Bearer ") and secrets.compare_digest(raw[7:].strip(), TOKEN):
        return True
    key = (query.get("key") or [None])[0]
    return bool(key) and secrets.compare_digest(key, TOKEN)


def _index():
    return {
        "service": "ApiBot",
        "platform": "vercel",
        "docs": "/api/v1/catalog",
        "openapi": "/api/v1/openapi.json",
        "health": "/health",
        "auth": "on (bearer)" if TOKEN else "open (set API_TOKEN to require it)",
    }


def _docs(method):
    global _CATALOG, _OPENAPI
    if method == "catalog":
        if _CATALOG is None:
            _CATALOG = core.Handler._catalog(None)
        return _CATALOG
    if _OPENAPI is None:
        _OPENAPI = core.Handler._openapi(None)
    return _OPENAPI


def handle(path, query, headers):
    """Route one request. Returns a Vercel response dict."""
    path = unquote(path).rstrip("/") or "/"
    qs = {k: list(v) if isinstance(v, (list, tuple)) else [v]
          for k, v in (query or {}).items() if k != "__path"}

    if path in ("/", "/api"):
        return _json(200, _index())
    if path == "/health":
        return _json(200, {
            "status": "ok",
            "uptime_s": round(time.time() - _START, 1),
            "routes": len([r for r in core.ROUTES if r[0] == "GET"]),
            "auth": "on" if TOKEN else "off",
            "cache": core.CACHE.stats(),
        })
    if path == "/api/v1/catalog":
        return _json(200, _docs("catalog"))
    if path == "/api/v1/openapi.json":
        return _json(200, _docs("openapi"))

    if not _authed(headers, qs):
        return _json(401, {"error": "unauthorized",
                           "hint": "Authorization: Bearer <API_TOKEN>"})

    for method, rx, fn, public, _name in core.ROUTES:
        m = rx.match(path)
        if not m:
            continue
        try:
            result = fn(None, m, qs)
        except core.UpstreamError as exc:
            return _json(exc.status, {"error": str(exc), "path": path})
        except Exception as exc:
            sys.stderr.write("[vercel] %s: %r\n" % (path, exc))
            return _json(500, {"error": "internal error", "detail": str(exc)[:200]})
        if isinstance(result, tuple):
            payload, extra = result
        else:
            payload, extra = result, None
        return _json(200, payload, extra)

    return _json(404, {"error": "not found", "path": path,
                       "hint": "GET /api/v1/catalog"})


def handler(request):
    """Vercel Python entry point."""
    try:
        method = (request.get("method") or "GET").upper()
        headers = request.get("headers") or {}

        if method == "OPTIONS":
            return {"statusCode": 204, "headers": dict(_CORS), "body": ""}
        if method not in ("GET", "HEAD"):
            return _json(405, {"error": "method not allowed"})

        raw = request.get("url") or ""
        path = urlparse(raw).path if raw else (request.get("path") or "/")
        if not path:
            path = request.get("path") or "/"

        query = {}
        for k, v in (request.get("queryStringParameters") or {}).items():
            query[k] = [v] if isinstance(v, str) else list(v or [""])
        inline = urlparse(raw).query if raw else ""
        if inline:
            for k, v in parse_qs(inline).items():
                query.setdefault(k, v)

        # Vercel hands the function the path it routed to; when a rewrite
        # collapses everything onto /api the original survives in a header.
        for hk in ("x-forwarded-path", "x-matched-path", "x-vercel-original-path"):
            fwd = next((v for k, v in headers.items()
                        if k.lower() == hk and v), None)
            if fwd and fwd.startswith("/api/v1"):
                path = urlparse(fwd).path
                break

        return handle(path, query, headers)
    except Exception as exc:  # never leak a traceback
        sys.stderr.write("[vercel] fatal: %r\n" % (exc,))
        return _json(500, {"error": "internal error", "detail": str(exc)[:200]})
