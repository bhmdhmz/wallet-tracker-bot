"""The list of tracked wallets, stored inside state.json.

Config/env only *seeds* this list on first run. After that, wallets are
added, removed, and muted through the Telegram bot itself and persist here —
so a redeploy that still ships the same WALLETS_JSON won't undo changes made
from the chat.
"""

from __future__ import annotations

from .models import get_chain
from .state import State


def wallet_key(chain: str, address: str) -> str:
    return f"{chain.lower()}:{address.lower()}"


def _short(address: str) -> str:
    return address[:6] + "…" + address[-4:] if len(address) > 12 else address


def seed(state: State, wallets_cfg: list[dict]) -> None:
    """Add any wallet from config/env not already tracked. Never touches an
    existing entry, so it won't resurrect one you removed from the chat."""
    for w in wallets_cfg:
        chain = get_chain(w["chain"]).name
        address = w["address"]
        key = wallet_key(chain, address)
        entry = state.get(key)
        entry.setdefault("chain", chain)
        entry.setdefault("address", address)
        entry.setdefault("label", w.get("label") or _short(address))
        entry.setdefault("muted", False)
    state.save()


def list_wallets(state: State) -> list[dict]:
    out = []
    for key, entry in state.data.items():
        if not isinstance(entry, dict) or "chain" not in entry or "address" not in entry:
            continue  # skips telegram_offset and any other non-wallet key
        out.append(
            {
                "key": key,
                "chain": entry["chain"],
                "address": entry["address"],
                "label": entry.get("label") or _short(entry["address"]),
                "muted": bool(entry.get("muted", False)),
            }
        )
    return sorted(out, key=lambda w: w["label"].lower())


def add_wallet(state: State, chain: str, address: str, label: str | None) -> str:
    """Raises ValueError if the chain name isn't recognised."""
    chain_info = get_chain(chain)
    key = wallet_key(chain_info.name, address)
    entry = state.get(key)
    entry["chain"] = chain_info.name
    entry["address"] = address
    entry["label"] = label or _short(address)
    entry.setdefault("muted", False)
    state.save()
    return key


def remove_wallet(state: State, key: str) -> bool:
    if key in state.data:
        del state.data[key]
        state.save()
        return True
    return False


def toggle_mute(state: State, key: str) -> bool | None:
    """Returns the new muted state, or None if the wallet doesn't exist."""
    entry = state.data.get(key)
    if not isinstance(entry, dict) or "chain" not in entry:
        return None
    entry["muted"] = not entry.get("muted", False)
    state.save()
    return entry["muted"]
