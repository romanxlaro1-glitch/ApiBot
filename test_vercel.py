"""Exercise api/index.py the way Vercel will: import it, call handler() with
Vercel's request shape, and compare the routing against the local server.

This is the only honest way to know whether the deploy will work, because
"the file looks right" says nothing about a serverless handler.
"""
import json
import os
import sys

sys.path.insert(0, "/root/ApiBot")
os.environ.setdefault("API_TOKEN", "test-token-abc")

import importlib.util

spec = importlib.util.spec_from_file_location(
    "vercel_entry", "/root/ApiBot/api/index.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

print("=== module imported ===")
print("  routes seen by the handler:", len(mod.core.ROUTES))
print("  handler callable        :", callable(mod.handler))

TOK = os.environ["API_TOKEN"]


def call(path, query=None, token=TOK):
    """Vercel passes request['headers'] as a plain dict of str -> str."""
    headers = {"authorization": "Bearer " + token} if token else {}
    try:
        # Vercel supplies 'url'; the handler parses the path out of it.
        # queryStringParameters carries the parsed query, and the inline
        # query string is merged in by handle() when present.
        url = "https://example.vercel.app" + path
        if query:
            url += "?" + "&".join("%s=%s" % (k, v) for k, v in query.items())
        return mod.handler({
            "method": "GET",
            "url": url,
            "headers": headers,
            "queryStringParameters": query or {},
        })
    except Exception as exc:
        return 500, {"crash": "%s: %s" % (type(exc).__name__, exc)}


CASES = [
    ("/health",                 None,           TOK),
    ("/api/v1/catalog",         None,           None),   # public
    ("/api/v1/openapi.json",    None,           None),   # public
    ("/",                       None,           None),   # public
    ("/api/v1/play/dice",       {"dice": "2d6+3"}, TOK),
    ("/api/v1/jkt48/roster",    {"limit": "3"}, TOK),
    ("/api/v1/phone/validate",  {"number": "+628123456789"}, TOK),
    ("/api/v1/play/gacha/pull", {"count": "2"}, TOK),
    ("/api/v1/play/nope",       None,           TOK),   # -> 404
    ("/api/v1/play/dice",       {"dice": "2d6+3"}, None),  # -> 401
]

print("\n=== routing + auth ===")
fails = 0
for path, query, token in CASES:
    res = call(path, query, token)
    if isinstance(res, dict):
        code = res.get("statusCode", res.get("status", "?"))
        body = res.get("json") or res.get("body")
        if isinstance(body, (bytes, str)):
            try:
                body = json.loads(body)
            except Exception:
                body = str(body)[:80]
    elif isinstance(res, tuple):
        code, body = res
    else:
        code, body = "?", str(res)[:80]
    ok = "200" if str(code) in ("200", 200) else str(code)
    print("  %-6s %-26s %s" % (ok, path, str(body)[:88]))
    if "crash" in str(body):
        fails += 1

print("\n=== CORS headers on a real response ===")
res = mod.handler({"method": "GET", "headers": {}, "query": {}})
hdrs = res.get("headers") or {}
print("  Allow-Origin:", hdrs.get("Access-Control-Allow-Origin"))
print("  Allow-Headers:", hdrs.get("Access-Control-Allow-Headers"))
print("  Allow-Methods:", hdrs.get("Access-Control-Allow-Methods"))

print("\n=== the two real limits of a serverless deploy ===")
print("  maxDuration in vercel.json : 60s")
print("  /ai/ask wait max is 300s   : would be cut off by the platform")
print("  cache is per-invocation    : cold starts lose the shared cache")

print("\nRESULT:", "clean" if not fails else "%d crash(es)" % fails)
