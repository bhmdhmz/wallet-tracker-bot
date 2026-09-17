"""USD price lookup via the free Dexscreener API (no key required).

Covers both EVM tokens and Solana mints. Failures are non-fatal — the
notification just goes out without a USD figure.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation

import httpx

log = logging.getLogger(__name__)

CACHE_TTL = 120  # seconds
_cache: dict[str, tuple[float, Decimal | None]] = {}

# Fallback for native coins, which have no contract address.
NATIVE_PROXY = {
    "ETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",   # WETH
    "BNB": "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c",   # WBNB
    "POL": "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270",   # WPOL
    "AVAX": "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",  # WAVAX
    "SOL": "So11111111111111111111111111111111111111112",  # WSOL
}


async def usd_price(client: httpx.AsyncClient, token_address: str | None,
                    symbol: str | None = None) -> Decimal | None:
    key = token_address or NATIVE_PROXY.get((symbol or "").upper())
    if not key:
        return None

    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]

    price: Decimal | None = None
    try:
        r = await client.get(
            f"https://api.dexscreener.com/latest/dex/tokens/{key}", timeout=15
        )
        r.raise_for_status()
        pairs = r.json().get("pairs") or []
        best = max(
            pairs,
            key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0),
            default=None,
        )
        if best and best.get("priceUsd"):
            price = Decimal(str(best["priceUsd"]))
    except (httpx.HTTPError, ValueError, InvalidOperation) as exc:
        log.debug("Price lookup failed for %s: %s", key, exc)

    _cache[key] = (now, price)
    return price
