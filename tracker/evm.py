"""Watch an EVM wallet through the Etherscan V2 multichain API.

One API key covers 60+ EVM chains; the target network is selected with the
`chainid` query parameter against https://api.etherscan.io/v2/api
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

import httpx

from .models import Activity, ChainInfo, Transfer

log = logging.getLogger(__name__)

API_URL = "https://api.etherscan.io/v2/api"
# Free tier allows ~5 calls/second across all chains.
_rate_limit = asyncio.Semaphore(2)


async def _call(client: httpx.AsyncClient, params: dict) -> list[dict]:
    async with _rate_limit:
        await asyncio.sleep(0.25)
        r = await client.get(API_URL, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if data.get("status") == "1" and isinstance(data.get("result"), list):
        return data["result"]
    message = str(data.get("result") or data.get("message") or "")
    if "No transactions found" in message or "No records found" in message:
        return []
    log.warning("Etherscan API said: %s", message[:200])
    return []


async def fetch_activities(
    client: httpx.AsyncClient,
    chain: ChainInfo,
    address: str,
    label: str,
    api_key: str,
    start_block: int,
) -> tuple[list[Activity], int]:
    """Return new activities since `start_block`, plus the newest block seen."""
    wallet = address.lower()
    base = {
        "chainid": chain.chain_id,
        "address": address,
        "startblock": start_block,
        "endblock": 99999999,
        "sort": "asc",
        "page": 1,
        "offset": 200,
        "apikey": api_key,
    }

    normal, tokens = await asyncio.gather(
        _call(client, {**base, "module": "account", "action": "txlist"}),
        _call(client, {**base, "module": "account", "action": "tokentx"}),
    )

    by_hash: dict[str, Activity] = {}
    highest = start_block

    def slot(tx: dict) -> Activity:
        h = tx["hash"]
        if h not in by_hash:
            by_hash[h] = Activity(
                chain=chain.name,
                wallet=address,
                label=label,
                tx_hash=h,
                timestamp=int(tx.get("timeStamp", 0)),
            )
        return by_hash[h]

    for tx in normal:
        highest = max(highest, int(tx["blockNumber"]))
        if tx.get("isError") == "1":
            continue
        value = Decimal(tx.get("value", "0")) / Decimal(10**18)
        if value <= 0:
            continue
        direction = "out" if tx.get("from", "").lower() == wallet else "in"
        slot(tx).transfers.append(
            Transfer(chain.native_symbol, value, direction, None, is_native=True)
        )

    for tx in tokens:
        highest = max(highest, int(tx["blockNumber"]))
        try:
            decimals = int(tx.get("tokenDecimal") or 18)
        except ValueError:
            decimals = 18
        amount = Decimal(tx.get("value", "0")) / Decimal(10**decimals)
        frm, to = tx.get("from", "").lower(), tx.get("to", "").lower()
        if wallet not in (frm, to):
            continue
        direction = "out" if frm == wallet else "in"
        slot(tx).transfers.append(
            Transfer(
                symbol=tx.get("tokenSymbol") or "???",
                amount=amount,
                direction=direction,
                address=tx.get("contractAddress"),
            )
        )

    activities = sorted(by_hash.values(), key=lambda a: a.timestamp)
    return [a for a in activities if a.transfers], highest


async def latest_block(client: httpx.AsyncClient, chain: ChainInfo, api_key: str) -> int:
    """Current head block, used to start watching from 'now' on first run."""
    async with _rate_limit:
        await asyncio.sleep(0.25)
        r = await client.get(
            API_URL,
            params={
                "chainid": chain.chain_id,
                "module": "proxy",
                "action": "eth_blockNumber",
                "apikey": api_key,
            },
            timeout=30,
        )
    r.raise_for_status()
    result = r.json().get("result")
    return int(result, 16) if isinstance(result, str) else 0
