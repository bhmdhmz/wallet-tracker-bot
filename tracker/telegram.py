"""Telegram delivery and message formatting."""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from .models import Activity, Transfer, get_chain

log = logging.getLogger(__name__)

EMOJI = {
    "BUY": "🟢",
    "SELL": "🔴",
    "SWAP": "🔄",
    "RECEIVE": "📥",
    "SEND": "📤",
    "OTHER": "•",
}


def fmt_amount(value: Decimal) -> str:
    if value == 0:
        return "0"
    if value >= 1000:
        return f"{value:,.2f}"
    if value >= 1:
        return f"{value:,.4f}".rstrip("0").rstrip(".")
    return f"{value:.8f}".rstrip("0").rstrip(".")


def fmt_usd(value: Decimal | None) -> str:
    if value is None:
        return ""
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:.6f}".rstrip("0").rstrip(".")


def _leg(t: Transfer, price: Decimal | None) -> str:
    text = f"{fmt_amount(t.amount)} {html.escape(t.symbol)}"
    if price is not None:
        text += f" (~{fmt_usd(t.amount * price)})"
    return text


def build_message(
    activity: Activity,
    main_price: Decimal | None = None,
    counter_price: Decimal | None = None,
) -> str:
    chain = get_chain(activity.chain)
    lines = [
        f"{EMOJI.get(activity.kind, '•')} <b>{activity.kind}</b> — "
        f"{html.escape(activity.label)} <i>({chain.name})</i>"
    ]

    if activity.kind in ("BUY", "SELL", "SWAP") and activity.main and activity.counter:
        got, paid = (
            (activity.main, activity.counter)
            if activity.kind in ("BUY", "SWAP")
            else (activity.counter, activity.main)
        )
        got_p = main_price if got is activity.main else counter_price
        paid_p = main_price if paid is activity.main else counter_price
        lines.append(f"Out: {_leg(paid, paid_p)}")
        lines.append(f"In: {_leg(got, got_p)}")
        if main_price is not None:
            lines.append(
                f"Price: {fmt_usd(main_price)} / {html.escape(activity.main.symbol)}"
            )
    elif activity.main:
        lines.append(f"Amount: {_leg(activity.main, main_price)}")

    if activity.main and activity.main.address:
        lines.append(f"<code>{html.escape(activity.main.address)}</code>")

    when = datetime.fromtimestamp(activity.timestamp or 0, tz=timezone.utc)
    lines.append(f"🕒 {when:%Y-%m-%d %H:%M:%S} UTC")
    lines.append(
        f"🔗 <a href=\"{chain.explorer_tx.format(hash=activity.tx_hash)}\">View transaction</a>"
    )
    return "\n".join(lines)


async def send_message(client: httpx.AsyncClient, token: str, chat_id: str, text: str) -> bool:
    try:
        r = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if r.status_code != 200:
            log.error("Telegram rejected the message: %s", r.text[:300])
            return False
        return True
    except httpx.HTTPError as exc:
        log.error("Telegram request failed: %s", exc)
        return False
