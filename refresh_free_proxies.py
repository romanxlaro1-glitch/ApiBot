"""Refresh free_proxies.json from the public lists.

The point of this script is the SECOND stage: a proxy that accepts a TCP
connection is not a proxy that works. Probing 600 candidates and keeping the
one or two that actually complete a request is the whole job, and it takes a
couple of minutes.

Run it on a schedule, or by hand:

    python3 refresh_free_proxies.py --sample 800

Output is a plain JSON array of "host:port" strings, consumed by
sources.py::_load_free_proxies. Nothing here talks to ApiBot's own service.
"""
import argparse
import concurrent.futures as cf
import json
import random
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/"
    "proxies/protocols/http/data.txt",
    "https://api.proxyscrape.com/v4/free-proxy-list/get"
    "?request=displayproxies&proxy_format=protocolipport&format=text&timeout=10000",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
    "https://raw.githubusercontent.com/MuRongPIG/Proxy-Master/main/http.txt",
    "https://raw.githubusercontent.com/proxifly/free-proxy-list/main/"
    "proxies/all/data.txt",
]

# A public proxy can read the request, so probe it with a harmless endpoint
# that returns nothing sensitive. api.ipify.org echoes back the exit IP and
# nothing else.
PROBE_URL = "https://api.ipify.org?format=json"
PROBE_TIMEOUT = 10

PROXY_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}:\d{2,5}$")


def fetch(url):
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": UA}),
                timeout=15) as f:
            return f.read().decode("utf8", "replace").split()
    except Exception as exc:
        sys.stderr.write("  list failed: %s\n" % url.split("/")[2])
        return []


def collect(verbose=True):
    seen = {}
    with cf.ThreadPoolExecutor(len(SOURCES)) as ex:
        for lines in ex.map(fetch, SOURCES):
            for line in lines:
                p = line.strip()
                if p.startswith(("http://", "https://")):
                    p = p.split("://", 1)[1]
                if PROXY_RE.match(p):
                    seen[p] = True
    if verbose:
        sys.stderr.write("collected %d unique candidates\n" % len(seen))
    return list(seen)


def tcp_ok(p):
    host, _, port = p.partition(":")
    try:
        socket.create_connection((host, int(port)), timeout=5).close()
        return True
    except Exception:
        return False


def works(p, timeout=PROBE_TIMEOUT):
    """A proxy only counts if it completes a real request through it."""
    try:
        op = urllib.request.build_opener(urllib.request.ProxyHandler(
            {"http": "http://" + p, "https": "http://" + p}))
        op.addheaders = [("User-Agent", UA)]
        with op.open(urllib.request.Request(PROBE_URL), timeout=timeout) as f:
            ip = json.loads(f.read())["ip"]
        return p, ip
    except Exception:
        return p, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=600,
                    help="how many candidates to test (default 600)")
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--out", default="/root/ApiBot/free_proxies.json")
    ap.add_argument("--min", type=int, default=1,
                    help="fail unless at least this many survive")
    args = ap.parse_args()

    pool = collect()
    if not pool:
        sys.stderr.write("no candidates collected; leaving the file alone\n")
        return 1
    random.seed(args.seed)
    random.shuffle(pool)
    cand = pool[:args.sample]

    t0 = time.time()
    with cf.ThreadPoolExecutor(80) as ex:
        up = [p for p, ok in zip(cand, ex.map(tcp_ok, cand)) if ok]
    sys.stderr.write("stage 1: %d/%d accept TCP (%.0fs)\n"
                     % (len(up), len(cand), time.time() - t0))

    t0 = time.time()
    alive = []
    with cf.ThreadPoolExecutor(40) as ex:
        for p, ip in ex.map(works, up):
            if ip:
                alive.append((p, ip))
    sys.stderr.write("stage 2: %d/%d actually proxy (%.0fs)\n"
                     % (len(alive), len(cand), time.time() - t0))

    for p, ip in alive:
        sys.stderr.write("  %-22s %s\n" % (p, ip))

    if len(alive) < args.min:
        sys.stderr.write("only %d usable, below --min %d; keeping the old file\n"
                         % (len(alive), args.min))
        return 1
    with open(args.out, "w") as f:
        json.dump([p for p, _ in alive], f, indent=1)
    sys.stderr.write("wrote %d proxies to %s\n" % (len(alive), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
