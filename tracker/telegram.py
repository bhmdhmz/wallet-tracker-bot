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


async def send_message(
    client: httpx.AsyncClient,
    token: str,
    chat_id: str,
    text: str,
    reply_markup: dict | None = None,
) -> bool:
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=20
        )
        if r.status_code != 200:
            log.error("Telegram rejected the message: %s", r.text[:300])
            return False
        return True
    except httpx.HTTPError as exc:
        log.error("Telegram request failed: %s", exc)
        return False


async def edit_message(
    client: httpx.AsyncClient,
    token: str,
    chat_id: str,
    message_id: int,
    text: str,
    reply_markup: dict | None = None,
) -> bool:
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = await client.post(
            f"https://api.telegram.org/bot{token}/editMessageText", json=payload, timeout=20
        )
        if r.status_code != 200:
            log.warning("editMessageText failed: %s", r.text[:300])
            return False
        return True
    except httpx.HTTPError as exc:
        log.warning("editMessageText error: %s", exc)
        return False


async def answer_callback(
    client: httpx.AsyncClient, token: str, callback_id: str, text: str | None = None
) -> None:
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    try:
        await client.post(
            f"https://api.telegram.org/bot{token}/answerCallbackQuery", json=payload, timeout=15
        )
    except httpx.HTTPError as exc:
        log.debug("answerCallbackQuery failed: %s", exc)


async def get_updates(
    client: httpx.AsyncClient, token: str, offset: int, timeout: int = 25
) -> list[dict]:
    """Long-poll for new messages / button taps since `offset`."""
    r = await client.get(
        f"https://api.telegram.org/bot{token}/getUpdates",
        params={
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": '["message","callback_query"]',
        },
        timeout=timeout + 10,
    )
    r.raise_for_status()
    data = r.json()
    return data.get("result", []) if data.get("ok") else []


def build_alert_keyboard(wallet_key: str, chain_name: str, token_address: str | None) -> dict:
    """Buttons attached to each trade alert: quick-mute plus a chart link."""
    buttons = [{"text": "🔇 Mute this wallet", "callback_data": f"muteone:{wallet_key}"}]
    if token_address:
        chain = get_chain(chain_name)
        if chain.dexscreener_slug:
            buttons.append(
                {
                    "text": "📈 Chart",
                    "url": f"https://dexscreener.com/{chain.dexscreener_slug}/{token_address}",
                }
            )
    return {"inline_keyboard": [buttons]}
