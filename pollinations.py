#!/usr/bin/env python3
"""
text.pollinations.ai - keyless anonymous text generation.

The endpoint is a plain GET with the prompt in the path, so there is no SDK and
no account. Three things are not in its documentation and cost real time to
discover:

1. ``Referer`` (and ``Origin``) must point back at the site. Without them the
   very same request that worked a moment earlier answers ``402 {}``.
2. Anonymous use is metered by IP at roughly one request per cooldown window.
   A burst right after a success is 100% 402; the window reopens on its own
   after a few minutes.
3. Model names are accepted on the classic path but only the default model is
   available anonymously - asking for a specific one still 402s.

So this module is deliberately conservative: it spends a request, reads the
failure honestly, and never pretends a 402 is an upstream outage. The caller
decides whether to queue, cache, or report.
"""

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://text.pollinations.ai"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

# These are the headers the site's own page sends. Omitting Referer is the
# difference between an answer and 402.
SITE_HEADERS = {
    "User-Agent": UA,
    "Accept": "*/*",
    "Referer": BASE + "/",
    "Origin": BASE,
}

DEFAULT_MODEL = "openai-fast"       # GPT-OSS 20B, tier "anonymous"
DIRECT_TIMEOUT = 60


class AskError(Exception):
    def __init__(self, message, status=502, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class QuotaExhausted(AskError):
    """The anonymous window is closed. Not a failure of the service."""

    def __init__(self, message="anonymous quota exhausted (402)"):
        super().__init__(message, 429)


def ask(prompt, model=None, timeout=DIRECT_TIMEOUT, referer=True):
    """One generation. Returns (text, model_used, seconds).

    Raises QuotaExhausted on 402 and AskError on anything else.
    """
    if not prompt or not str(prompt).strip():
        raise AskError("prompt is required", 400)
    url = BASE + "/" + urllib.parse.quote(str(prompt), safe="")
    if model:
        url += "?model=" + urllib.parse.quote(model, safe="")
    headers = dict(SITE_HEADERS)
    if not referer:
        headers.pop("Referer", None)
        headers.pop("Origin", None)
    started = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                    timeout=timeout) as f:
            text = f.read().decode("utf8", "replace").strip()
    except urllib.error.HTTPError as e:
        if e.code == 402:
            raise QuotaExhausted()
        raise AskError("pollinations HTTP %d" % e.code, e.code)
    except Exception as e:
        raise AskError("%s: %s" % (type(e).__name__, str(e)[:90]), 502)
    return text, (model or DEFAULT_MODEL), round(time.time() - started, 2)


def models(timeout=25):
    """The catalogue is public even though generation is not (works keyless)."""
    url = "https://gen.pollinations.ai/v1/models"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as f:
        data = json.loads(f.read())
    return data.get("data", [])


def wait_for_window(attempts=40, sleep_between=30, jitter=8, log=None):
    """Poll cheaply until the anonymous window reopens. Returns True/False.

    A refused request costs nothing upstream (it is rejected before generation),
    so polling with a trivial prompt is the cheap way to probe the window.
    """
    for i in range(attempts):
        try:
            ask("What is 5*5? number only", timeout=30)
            if log:
                log("anonymous window reopened after %d probes" % (i + 1))
            return True
        except QuotaExhausted:
            time.sleep(sleep_between + random.random() * jitter)
        except AskError:
            time.sleep(sleep_between)
    return False
