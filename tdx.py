"""Minimal TDX client (stdlib only). Reads TDX_CLIENT_ID / TDX_CLIENT_SECRET from .env.

Usage:
    from tdx import get
    buses = get("/api/basic/v2/Bus/RealTimeByFrequency/InterCity/5250")
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = "https://tdx.transportdata.tw"
TOKEN_URL = f"{BASE}/auth/realms/TDXConnect/protocol/openid-connect/token"
TOKEN_CACHE = ROOT / ".tdx_token.json"  # gitignored; avoids spending calls on new tokens
# Some Taiwanese government certificates lack a Subject Key Identifier, which Python 3.13+'s
# strict X.509 mode rejects; keep normal chain/hostname verification, drop only the strict flag.
SSL_CTX = ssl.create_default_context()
SSL_CTX.verify_flags &= ~ssl.VERIFY_X509_STRICT


def _load_env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def token() -> str:
    if TOKEN_CACHE.exists():
        cached = json.loads(TOKEN_CACHE.read_text())
        if cached["expires_at"] > time.time() + 300:
            return cached["access_token"]
    _load_env()
    body = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": os.environ["TDX_CLIENT_ID"],
        "client_secret": os.environ["TDX_CLIENT_SECRET"],
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(TOKEN_URL, data=body), context=SSL_CTX) as r:
        tok = json.load(r)
    TOKEN_CACHE.write_text(json.dumps({"access_token": tok["access_token"],
                                       "expires_at": time.time() + tok["expires_in"]}))
    TOKEN_CACHE.chmod(0o600)
    return tok["access_token"]


def request(path: str, params: dict | None = None) -> tuple[int, dict, bytes]:
    """Raw call: returns (status, headers, body). Does not raise on HTTP errors."""
    params = {"$format": "JSON", **(params or {})}
    url = f"{BASE}{path}?{urllib.parse.urlencode(params, safe='$,~')}"
    req = urllib.request.Request(url, headers={"authorization": f"Bearer {token()}",
                                               "Accept-Encoding": "identity"})
    try:
        with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def get(path: str, params: dict | None = None):
    status, _, body = request(path, params)
    if status != 200:
        raise RuntimeError(f"TDX {status}: {body[:300]!r}")
    return json.loads(body)
