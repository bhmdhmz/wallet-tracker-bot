"""Shared data models and the chain registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

Direction = Literal["in", "out"]
Kind = Literal["BUY", "SELL", "SWAP", "RECEIVE", "SEND", "OTHER"]


@dataclass
class Transfer:
    """One asset movement in or out of the watched wallet."""

    symbol: str
    amount: Decimal
    direction: Direction
    address: str | None = None  # token contract / mint, None for native coin
    is_native: bool = False


@dataclass
class Activity:
    """One on-chain transaction, seen from the watched wallet's point of view."""

    chain: str
    wallet: str
    label: str
    tx_hash: str
    timestamp: int  # unix seconds
    transfers: list[Transfer] = field(default_factory=list)
    kind: Kind = "OTHER"
    # Filled in by the classifier:
    main: Transfer | None = None  # the "interesting" token (what was bought/sold)
    counter: Transfer | None = None  # what it was paid with / received for


@dataclass
class ChainInfo:
    name: str
    kind: Literal["evm", "solana"]
    native_symbol: str
    explorer_tx: str  # format string with {hash}
    chain_id: int | None = None  # EVM only
    dexscreener_slug: str | None = None


CHAINS: dict[str, ChainInfo] = {
    "ethereum": ChainInfo("ethereum", "evm", "ETH", "https://etherscan.io/tx/{hash}", 1, "ethereum"),
    "base": ChainInfo("base", "evm", "ETH", "https://basescan.org/tx/{hash}", 8453, "base"),
    "arbitrum": ChainInfo("arbitrum", "evm", "ETH", "https://arbiscan.io/tx/{hash}", 42161, "arbitrum"),
    "optimism": ChainInfo("optimism", "evm", "ETH", "https://optimistic.etherscan.io/tx/{hash}", 10, "optimism"),
    "bsc": ChainInfo("bsc", "evm", "BNB", "https://bscscan.com/tx/{hash}", 56, "bsc"),
    "polygon": ChainInfo("polygon", "evm", "POL", "https://polygonscan.com/tx/{hash}", 137, "polygon"),
    "avalanche": ChainInfo("avalanche", "evm", "AVAX", "https://snowscan.xyz/tx/{hash}", 43114, "avalanche"),
    "solana": ChainInfo("solana", "solana", "SOL", "https://solscan.io/tx/{hash}", None, "solana"),
}


def get_chain(name: str) -> ChainInfo:
    key = name.strip().lower()
    if key not in CHAINS:
        raise ValueError(f"Unsupported chain '{name}'. Known: {', '.join(CHAINS)}")
    return CHAINS[key]
