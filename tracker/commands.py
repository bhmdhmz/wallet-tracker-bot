"""Long-polls Telegram for commands and button taps.

This is what makes the bot two-way: /menu, /list, /add, and the inline
buttons on wallet rows and trade alerts are all handled here. Only messages
from the configured chat id are acted on.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from . import telegram
from .models import get_chain
from .registry import add_wallet, list_wallets, remove_wallet, toggle_mute
from .state import State

log = logging.getLogger(__name__)

HELP_TEXT = (
    "<b>Commands</b>\n"
    "/list — tracked wallets, with mute/remove buttons\n"
    "/add &lt;chain&gt; &lt;address&gt; [label] — start tracking a wallet\n"
    "/menu — show the button menu\n\n"
    "Supported chains: ethereum, base, arbitrum, optimism, bsc, polygon, "
    "avalanche, solana\n\n"
    "Only <b>BUY</b> and <b>SELL</b> trigger a message — plain transfers and "
    "token-for-token swaps are tracked but not notified."
)

ADD_PROMPT = (
    "Send it as <code>chain address [label]</code>\n"
    "Example: <code>base 0xAbC123... MyWallet</code>"
)


def _menu_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "📋 List wallets", "callback_data": "list"}],
            [{"text": "➕ Add wallet", "callback_data": "add"}],
            [{"text": "❓ Help", "callback_data": "help"}],
        ]
    }


def _list_view(state: State) -> tuple[str, dict]:
    wallets = list_wallets(state)
    if not wallets:
        return "No wallets tracked yet. Tap Add wallet to start.", _menu_keyboard()

    lines = ["<b>Tracked wallets</b>"]
    rows = []
    for w in wallets:
        status = "🔇 muted" if w["muted"] else "🟢 active"
        lines.append(f"• {w['label']} — {w['chain']} ({status})")
        rows.append(
            [
                {
                    "text": "🔊 Unmute" if w["muted"] else "🔇 Mute",
                    "callback_data": f"mute:{w['key']}",
                },
                {"text": "🗑 Remove", "callback_data": f"remove:{w['key']}"},
            ]
        )
    rows.append([{"text": "⬅️ Menu", "callback_data": "menu"}])
    return "\n".join(lines), {"inline_keyboard": rows}


async def _try_add(client: httpx.AsyncClient, token: str, chat_id: str, state: State, text: str) -> None:
    parts = text.split(maxsplit=2)
    if len(parts) < 2:
        await telegram.send_message(client, token, chat_id, ADD_PROMPT)
        return
    chain, address = parts[0], parts[1]
    label = parts[2] if len(parts) > 2 else None
    try:
        get_chain(chain)
    except ValueError as exc:
        await telegram.send_message(client, token, chat_id, f"⚠️ {exc}")
        return
    add_wallet(state, chain, address, label)
    await telegram.send_message(
        client, token, chat_id, f"✅ Now tracking <b>{label or address}</b> on {chain}."
    )


async def run(client: httpx.AsyncClient, token: str, allowed_chat_id: str, state: State) -> None:
    """Runs forever, dispatching commands and button taps. Call alongside the
    poll loop with asyncio.gather — this coroutine never returns on its own.
    """
    offset = int(state.data.get("telegram_offset", 0))
    awaiting_add = False

    while True:
        try:
            updates = await telegram.get_updates(client, token, offset, timeout=25)
        except httpx.HTTPError as exc:
            log.warning("getUpdates failed, retrying: %s", exc)
            await asyncio.sleep(5)
            continue

        for update in updates:
            offset = update["update_id"] + 1
            state.data["telegram_offset"] = offset
            callback = update.get("callback_query")
            msg = update.get("message")

            if callback:
                chat_id = str(callback["message"]["chat"]["id"])
                if chat_id != str(allowed_chat_id):
                    continue
                message_id = callback["message"]["message_id"]
                data = callback.get("data", "")
                cid = callback["id"]

                if data == "menu":
                    await telegram.edit_message(
                        client, token, chat_id, message_id, "What would you like to do?", _menu_keyboard()
                    )
                elif data == "list":
                    text, kb = _list_view(state)
                    await telegram.edit_message(client, token, chat_id, message_id, text, kb)
                elif data == "help":
                    await telegram.edit_message(client, token, chat_id, message_id, HELP_TEXT, _menu_keyboard())
                elif data == "add":
                    awaiting_add = True
                    await telegram.answer_callback(client, token, cid)
                    await telegram.send_message(client, token, chat_id, ADD_PROMPT)
                elif data.startswith("mute:"):
                    muted = toggle_mute(state, data.split(":", 1)[1])
                    await telegram.answer_callback(
                        client, token, cid, "Muted" if muted else "Unmuted" if muted is not None else "Not found"
                    )
                    text, kb = _list_view(state)
                    await telegram.edit_message(client, token, chat_id, message_id, text, kb)
                elif data.startswith("remove:"):
                    remove_wallet(state, data.split(":", 1)[1])
                    await telegram.answer_callback(client, token, cid, "Removed")
                    text, kb = _list_view(state)
                    await telegram.edit_message(client, token, chat_id, message_id, text, kb)
                elif data.startswith("muteone:"):
                    muted = toggle_mute(state, data.split(":", 1)[1])
                    await telegram.answer_callback(
                        client, token, cid, "Wallet muted" if muted else "Wallet unmuted"
                    )
                else:
                    await telegram.answer_callback(client, token, cid)
                continue

            if not msg or "text" not in msg:
                continue
            chat_id = str(msg["chat"]["id"])
            if chat_id != str(allowed_chat_id):
                continue
            text = msg["text"].strip()

            if text in ("/start", "/menu"):
                awaiting_add = False
                await telegram.send_message(client, token, chat_id, "What would you like to do?", _menu_keyboard())
            elif text == "/help":
                await telegram.send_message(client, token, chat_id, HELP_TEXT, _menu_keyboard())
            elif text == "/list":
                list_text, kb = _list_view(state)
                await telegram.send_message(client, token, chat_id, list_text, kb)
            elif text.startswith("/add"):
                awaiting_add = False
                await _try_add(client, token, chat_id, state, text[len("/add"):].strip())
            elif awaiting_add:
                awaiting_add = False
                await _try_add(client, token, chat_id, state, text)
            else:
                await telegram.send_message(client, token, chat_id, "Not sure what that means — try /menu.")

        if updates:
            state.save()
