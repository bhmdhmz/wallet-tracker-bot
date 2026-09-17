"""Multi-chain wallet tracker -> Telegram notifications.

Run modes (all driven by environment variables, so the same image works
everywhere):

  python main.py            long-running poll loop        (VM, worker, Docker)
  PORT=10000 python main.py loop + HTTP health endpoint   (Render/Koyeb web svc)
  RUN_ONCE=1 python main.py one pass, then exit           (cron, GitHub Actions)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from decimal import Decimal

import httpx
from dotenv import load_dotenv

from tracker import evm, health, solana, telegram
from tracker.classify import classify
from tracker.models import Activity, get_chain
from tracker.prices import usd_price
from tracker.state import State

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s  %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("tracker")


def load_config() -> dict:
    """Wallets come from WALLETS_JSON if set, otherwise config.yaml.

    The env var is the better choice on hosted platforms: no wallet addresses
    committed to your repository, and no redeploy needed to change the list.
    """
    raw = os.getenv("WALLETS_JSON")
    if raw:
        try:
            wallets = json.loads(raw)
        except json.JSONDecodeError as exc:
            sys.exit(f"WALLETS_JSON is not valid JSON: {exc}")
        cfg = {"wallets": wallets}
    else:
        try:
            import yaml

            with open(os.getenv("CONFIG_FILE", "config.yaml")) as fh:
                cfg = yaml.safe_load(fh) or {}
        except FileNotFoundError:
            sys.exit("No WALLETS_JSON env var and no config.yaml found.")

    if not cfg.get("wallets"):
        sys.exit("No wallets configured.")

    cfg["poll_interval_seconds"] = int(
        os.getenv("POLL_INTERVAL_SECONDS", cfg.get("poll_interval_seconds", 30))
    )
    cfg["min_usd_value"] = Decimal(str(os.getenv("MIN_USD_VALUE", cfg.get("min_usd_value", 0))))
    cfg["state_file"] = os.getenv("STATE_FILE", cfg.get("state_file", "state.json"))
    return cfg


async def enrich_and_send(
    client: httpx.AsyncClient,
    activity: Activity,
    token: str,
    chat_id: str,
    min_usd: Decimal,
) -> None:
    classify(activity)
    if activity.kind == "OTHER" or not activity.main:
        return

    main_price = await usd_price(client, activity.main.address, activity.main.symbol)
    counter_price = None
    if activity.counter:
        counter_price = await usd_price(client, activity.counter.address, activity.counter.symbol)

    if min_usd > 0:
        value = None
        if main_price is not None:
            value = activity.main.amount * main_price
        elif counter_price is not None and activity.counter:
            value = activity.counter.amount * counter_price
        if value is not None and value < min_usd:
            log.info("Skipping %s (~$%.2f below threshold)", activity.tx_hash[:12], value)
            return

    text = telegram.build_message(activity, main_price, counter_price)
    if await telegram.send_message(client, token, chat_id, text):
        health.STATUS["alerts_sent"] += 1
        log.info("Notified: %s %s on %s", activity.kind, activity.main.symbol, activity.chain)


async def poll_wallet(
    client: httpx.AsyncClient,
    wallet_cfg: dict,
    state: State,
    secrets: dict,
    min_usd: Decimal,
) -> None:
    chain = get_chain(wallet_cfg["chain"])
    address = wallet_cfg["address"]
    label = wallet_cfg.get("label") or address[:6] + "…" + address[-4:]
    key = f"{chain.name}:{address.lower()}"
    entry = state.get(key)

    if chain.kind == "evm":
        api_key = secrets["etherscan"]
        if not entry["last_block"]:
            head = await evm.latest_block(client, chain, api_key)
            entry["last_block"] = max(head - 1, 0)
            log.info("[%s] starting at block %s on %s", label, entry["last_block"], chain.name)
            state.save()
            return
        activities, newest = await evm.fetch_activities(
            client, chain, address, label, api_key, entry["last_block"] + 1
        )
        entry["last_block"] = max(entry["last_block"], newest)
    else:
        activities, newest = await solana.fetch_activities(
            client, secrets["solana_rpc"], address, label, entry["last_signature"]
        )
        if not entry["last_signature"]:
            entry["last_signature"] = newest
            log.info("[%s] starting from signature %s", label, (newest or "")[:12])
            state.save()
            return
        entry["last_signature"] = newest or entry["last_signature"]

    for activity in activities:
        if state.mark_seen(key, activity.tx_hash):
            await enrich_and_send(
                client, activity, secrets["bot_token"], secrets["chat_id"], min_usd
            )

    state.save()


async def poll_all(client, wallets, state, secrets, min_usd) -> None:
    for wallet_cfg in wallets:
        try:
            await poll_wallet(client, wallet_cfg, state, secrets, min_usd)
        except Exception as exc:  # never let one wallet kill the loop
            health.STATUS["errors"] += 1
            log.exception("Error polling %s: %s", wallet_cfg.get("address"), exc)
    health.STATUS["last_poll"] = int(time.time())


async def main() -> None:
    load_dotenv()
    cfg = load_config()

    secrets = {
        "bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        "etherscan": os.getenv("ETHERSCAN_API_KEY", ""),
        "solana_rpc": os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
    }
    if not secrets["bot_token"] or not secrets["chat_id"]:
        sys.exit("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.")

    wallets = cfg["wallets"]
    if any(get_chain(w["chain"]).kind == "evm" for w in wallets) and not secrets["etherscan"]:
        sys.exit("An EVM wallet is configured but ETHERSCAN_API_KEY is missing.")

    run_once = os.getenv("RUN_ONCE", "").lower() in ("1", "true", "yes")
    port = os.getenv("PORT")
    interval = cfg["poll_interval_seconds"]
    min_usd = cfg["min_usd_value"]

    health.STATUS["wallets"] = len(wallets)
    if port and not run_once:
        await health.start(int(port))

    async with httpx.AsyncClient(headers={"User-Agent": "wallet-tracker/1.0"}) as client:
        state = State(cfg["state_file"])

        if not run_once and os.getenv("STARTUP_MESSAGE", "1") != "0":
            await telegram.send_message(
                client,
                secrets["bot_token"],
                secrets["chat_id"],
                f"✅ Wallet tracker started — watching {len(wallets)} wallet(s).",
            )

        if run_once:
            log.info("Single pass over %d wallet(s)", len(wallets))
            await poll_all(client, wallets, state, secrets, min_usd)
            return

        log.info("Watching %d wallet(s), polling every %ss", len(wallets), interval)
        while True:
            await poll_all(client, wallets, state, secrets, min_usd)
            await asyncio.sleep(interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Stopped.")
