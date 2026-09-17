"""Watch a Solana wallet with plain JSON-RPC.

Works against any RPC endpoint (Helius, QuickNode, Triton, or the public
mainnet node). Balance deltas are read from the transaction metadata, which
covers every AMM without needing per-DEX instruction parsing.
"""

from __future__ import annotations

import logging
from decimal import Decimal

import httpx

from .models import Activity, Transfer

log = logging.getLogger(__name__)

LAMPORTS = Decimal(10**9)
# Well-known mints, so messages show a symbol instead of a base58 blob.
KNOWN_MINTS = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "So11111111111111111111111111111111111111112": "SOL",
}


async def _rpc(client: httpx.AsyncClient, url: str, method: str, params: list):
    r = await client.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=30,
    )
    r.raise_for_status()
    payload = r.json()
    if "error" in payload:
        log.warning("Solana RPC error on %s: %s", method, payload["error"])
        return None
    return payload.get("result")


async def fetch_activities(
    client: httpx.AsyncClient,
    rpc_url: str,
    address: str,
    label: str,
    last_signature: str | None,
    limit: int = 25,
) -> tuple[list[Activity], str | None]:
    """Return new activities newer than `last_signature`, plus the newest sig."""
    params: list = [address, {"limit": limit}]
    if last_signature:
        params[1]["until"] = last_signature

    sigs = await _rpc(client, rpc_url, "getSignaturesForAddress", params) or []
    if not sigs:
        return [], last_signature

    newest = sigs[0]["signature"]
    activities: list[Activity] = []

    for entry in reversed(sigs):  # oldest first
        if entry.get("err"):
            continue
        tx = await _rpc(
            client,
            rpc_url,
            "getTransaction",
            [
                entry["signature"],
                {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
            ],
        )
        if not tx:
            continue
        activity = _parse(tx, entry["signature"], address, label)
        if activity and activity.transfers:
            activities.append(activity)

    return activities, newest


def _parse(tx: dict, signature: str, wallet: str, label: str) -> Activity | None:
    meta = tx.get("meta") or {}
    message = (tx.get("transaction") or {}).get("message") or {}
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in message.get("accountKeys", [])]

    activity = Activity(
        chain="solana",
        wallet=wallet,
        label=label,
        tx_hash=signature,
        timestamp=int(tx.get("blockTime") or 0),
    )

    # Native SOL delta (minus the fee we paid, so a plain transfer reads clean).
    if wallet in keys:
        idx = keys.index(wallet)
        pre = meta.get("preBalances") or []
        post = meta.get("postBalances") or []
        if len(pre) > idx and len(post) > idx:
            delta = Decimal(post[idx] - pre[idx]) / LAMPORTS
            if idx == 0:
                delta += Decimal(meta.get("fee", 0)) / LAMPORTS
            if abs(delta) > Decimal("0.000001"):
                activity.transfers.append(
                    Transfer("SOL", abs(delta), "in" if delta > 0 else "out", None, True)
                )

    # SPL token deltas for accounts owned by the wallet.
    def balances(key: str) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for bal in meta.get(key) or []:
            if bal.get("owner") != wallet:
                continue
            amount = Decimal((bal.get("uiTokenAmount") or {}).get("uiAmountString") or "0")
            out[bal["mint"]] = out.get(bal["mint"], Decimal(0)) + amount
        return out

    pre_tokens, post_tokens = balances("preTokenBalances"), balances("postTokenBalances")
    for mint in set(pre_tokens) | set(post_tokens):
        delta = post_tokens.get(mint, Decimal(0)) - pre_tokens.get(mint, Decimal(0))
        if delta == 0:
            continue
        activity.transfers.append(
            Transfer(
                symbol=KNOWN_MINTS.get(mint, mint[:4] + "…" + mint[-4:]),
                amount=abs(delta),
                direction="in" if delta > 0 else "out",
                address=mint,
            )
        )

    return activity
