"""Tiny JSON-backed store.

Each wallet's entry (identity + mute flag + polling progress) lives under a
single "chain:address" key, so tracker/registry.py can manage wallets and
tracker/{evm,solana}.py can track polling progress through the same object
without a second data structure to keep in sync. "telegram_offset" is the
one non-wallet key at the top level.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)


class State:
    def __init__(self, path: str | Path = "state.json"):
        self.path = Path(path)
        self.data: dict = {}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except (OSError, json.JSONDecodeError) as exc:
                log.warning("Could not read %s (%s), starting fresh", self.path, exc)

    def get(self, key: str) -> dict:
        return self.data.setdefault(key, {"last_block": 0, "last_signature": None, "seen": []})

    def mark_seen(self, key: str, tx_hash: str) -> bool:
        """Return True if this is the first time we see the hash."""
        entry = self.get(key)
        if tx_hash in entry["seen"]:
            return False
        entry["seen"].append(tx_hash)
        entry["seen"] = entry["seen"][-300:]  # keep the file small
        return True

    def save(self) -> None:
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2))
            tmp.replace(self.path)
        except OSError as exc:
            log.error("Could not save state: %s", exc)
