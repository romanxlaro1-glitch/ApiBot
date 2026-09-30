#!/usr/bin/env python3
"""
Minimal SOCKS5 client for the /api/v1/ai/ask proxy fallback.

Some proxy vendors hand out SOCKS5H URLs (``socks5://user:pass@host:port``)
and stdlib urllib cannot speak SOCKS at all - it only does HTTP CONNECT. This
is the fewest lines that make a real SOCKS5 connection, so ApiBot can stay
dependency-free while still using a vendor that only offers SOCKS.

Handles: no-auth (method 0x00) and username/password (0x02, RFC 1929).
Remote hostname resolution (``socks5h``) is the default, which is what you want
for HTTPS traffic through a rotating exit.
"""

import base64
import socket
import ssl
import struct

SOCKS5 = 0x05
NO_AUTH = 0x00
USERPASS = 0x02
CMD_CONNECT = 0x01
ATYP_DOMAIN = 0x03
ATYP_IPV4 = 0x01
ATYP_IPV6 = 0x04


class SocksError(Exception):
    pass


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise SocksError("proxy closed the connection mid-handshake "
                             "(%d/%d bytes)" % (len(buf), n))
        buf += chunk
    return buf


def _socks5_connect(proxy_host, proxy_port, username, password, host, port,
                    timeout=30):
    """Open a SOCKS5 tunnel to (host, port). Returns a plain socket."""
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    sock.settimeout(timeout)
    try:
        # Greeting: offer no-auth and user/pass.
        methods = bytes([NO_AUTH, USERPASS]) if username else bytes([NO_AUTH])
        sock.sendall(bytes([SOCKS5, len(methods)]) + methods)

        ver, method = _recv_exact(sock, 2)
        if ver != SOCKS5:
            raise SocksError("not a SOCKS5 server (version byte %d)" % ver)
        if method == 0xFF:
            raise SocksError("proxy rejected every auth method offered")
        if method == USERPASS:
            if not username:
                raise SocksError("proxy demands a username but none was given")
            u = username.encode()
            p = (password or "").encode()
            sock.sendall(bytes([0x01, len(u)]) + u + bytes([len(p)]) + p)
            if _recv_exact(sock, 1)[0] != 0x00:
                raise SocksError("proxy rejected the username/password")
        elif method != NO_AUTH:
            raise SocksError("unsupported auth method 0x%02x" % method)

        # CONNECT. Always send the hostname (socks5h) so the exit resolves it.
        hb = host.encode("idna") if any(ord(c) > 127 for c in host) else host.encode()
        if len(hb) > 255:
            raise SocksError("hostname too long for SOCKS5")
        req = bytes([SOCKS5, CMD_CONNECT, 0x00, ATYP_DOMAIN, len(hb)]) + hb
        req += struct.pack(">H", port)
        sock.sendall(req)

        head = _recv_exact(sock, 4)
        if head[1] != 0x00:
            raise SocksError("SOCKS5 connect failed, reply code %d" % head[1])
        atyp = head[3]
        if atyp == ATYP_IPV4:
            _recv_exact(sock, 4)
        elif atyp == ATYP_IPV6:
            _recv_exact(sock, 16)
        elif atyp == ATYP_DOMAIN:
            ln = _recv_exact(sock, 1)[0]
            _recv_exact(sock, ln)
        else:
            raise SocksError("unknown address type %d in reply" % atyp)
        _recv_exact(sock, 2)  # bound port
        return sock
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        raise


def https_over_socks5(proxy_host, proxy_port, username, password, host, port,
                      server_hostname=None, timeout=30, ctx=None):
    """TLS-over-SOCKS5 socket ready for http.client / SSL wrap."""
    raw = _socks5_connect(proxy_host, proxy_port, username, password, host, port,
                          timeout=timeout)
    if ctx is None:
        ctx = ssl.create_default_context()
    return ctx.wrap_socket(raw, server_hostname=server_hostname or host)
