"""Turn raw in/out transfers into a human notion of BUY / SELL / SWAP."""

from __future__ import annotations

from .models import Activity, Transfer

# Assets treated as "money" rather than as the thing being traded.
QUOTE_ASSETS = {
    "ETH", "WETH", "BNB", "WBNB", "POL", "MATIC", "WMATIC", "AVAX", "WAVAX",
    "SOL", "WSOL", "USDC", "USDC.E", "USDT", "USDT.E", "DAI", "FRAX", "BUSD",
    "USDBC", "USDE", "TUSD", "USDS",
}


def _is_quote(t: Transfer) -> bool:
    return t.symbol.upper() in QUOTE_ASSETS


def _largest(transfers: list[Transfer]) -> Transfer | None:
    return max(transfers, key=lambda t: t.amount, default=None)


def classify(activity: Activity) -> Activity:
    """Set activity.kind / .main / .counter based on the transfer list."""
    # Drop dust and zero-value legs (routers often emit them).
    moves = [t for t in activity.transfers if t.amount > 0]
    ins = [t for t in moves if t.direction == "in"]
    outs = [t for t in moves if t.direction == "out"]

    if ins and outs:
        token_in = [t for t in ins if not _is_quote(t)]
        token_out = [t for t in outs if not _is_quote(t)]

        if token_in and not token_out:
            activity.kind = "BUY"
            activity.main = _largest(token_in)
            activity.counter = _largest(outs)
        elif token_out and not token_in:
            activity.kind = "SELL"
            activity.main = _largest(token_out)
            activity.counter = _largest(ins)
        elif token_in and token_out:
            # Token-for-token: treat what came in as the buy side.
            activity.kind = "SWAP"
            activity.main = _largest(token_in)
            activity.counter = _largest(token_out)
        else:
            # Stable <-> stable, ETH <-> USDC, etc.
            activity.kind = "SWAP"
            activity.main = _largest(ins)
            activity.counter = _largest(outs)
    elif ins:
        activity.kind = "RECEIVE"
        activity.main = _largest(ins)
    elif outs:
        activity.kind = "SEND"
        activity.main = _largest(outs)
    else:
        activity.kind = "OTHER"

    return activity
