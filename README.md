# Multi-chain wallet tracker → Telegram

Watches any number of wallets across EVM chains and Solana, detects buys, sells
and swaps, and pushes a formatted alert to your Telegram chat.

## What you get per alert

```
🟢 BUY — Whale ETH (ethereum)
Out: 2.5 WETH (~$7,750.00)
In: 15,000,000 PEPE (~$18.00)
Price: $0.0000012 / PEPE
0x6982508145454ce325ddbe47a25d4ec3d2311933
🕒 2026-09-17 14:03:11 UTC
🔗 View transaction
```

## Setup

### 1. Create the bot and find your chat id

- Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
- Send any message to your new bot, then open
  `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser and read
  `result[0].message.chat.id`. That's your `TELEGRAM_CHAT_ID`.

### 2. Get API keys

- **EVM chains:** one free key at <https://etherscan.io/apis>. Etherscan's V2 API
  covers 60+ EVM chains with a single key, selected per request via `chainid` —
  no separate BscScan/Basescan/Arbiscan keys needed. Free tier is ~5 calls/sec.
- **Solana:** any RPC URL. The public `api.mainnet-beta.solana.com` works for
  testing but rate-limits hard; a free Helius or QuickNode endpoint is much
  better for continuous polling.
- **Prices:** Dexscreener is used for USD values and needs no key.

### 3. Install and configure

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in your token, chat id, API key
# edit config.yaml with the wallets you want to follow
python main.py
```

## Configuration

`config.yaml`:

| Field | Meaning |
|---|---|
| `poll_interval_seconds` | How often each wallet is checked. 30s is a good default on a free key. |
| `min_usd_value` | Skip trades below this USD value. `0` notifies everything. |
| `wallets[].chain` | `ethereum`, `base`, `arbitrum`, `optimism`, `bsc`, `polygon`, `avalanche`, `solana` |
| `wallets[].label` | Name shown in the alert. |
| `wallets[].address` | The wallet to follow. |

On hosted platforms you can skip `config.yaml` entirely and pass the wallet list
as a `WALLETS_JSON` environment variable instead — see DEPLOY.md.

On first run each wallet is recorded at the current head, so you only get
alerts for what happens from that moment on. Progress is stored in
`state.json`, so restarts don't replay old transactions.

## How buy/sell detection works

Rather than decoding each DEX's contracts, the bot looks at what actually
entered and left the wallet in a transaction:

- **EVM:** normal transactions (native coin) plus ERC-20 transfers are fetched
  from Etherscan, grouped by tx hash, and tagged as in/out relative to the wallet.
- **Solana:** pre/post SOL and SPL token balances from the transaction metadata
  give the same picture, which works for every AMM without per-DEX parsing.

Then: a quote asset out + a token in = **BUY**; a token out + a quote asset in =
**SELL**; token for token = **SWAP**. Quote assets are the stablecoins and
native/wrapped coins listed in `tracker/classify.py` — add anything else you
treat as money there (e.g. a chain's dominant LST).

## Deploying

See **DEPLOY.md** for hosting options (Render, Oracle Cloud always-free VM,
GitHub Actions, Docker) and the trade-offs of each.

## Running it continuously

On a small VPS, systemd is the simplest option:

```ini
# /etc/systemd/system/wallet-tracker.service
[Unit]
Description=Wallet tracker telegram bot
After=network-online.target

[Service]
WorkingDirectory=/opt/wallet-tracker
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10
User=tracker

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now wallet-tracker
journalctl -u wallet-tracker -f
```

## Where to take it next

- **Faster alerts:** replace polling with webhooks — Alchemy Address Activity on
  EVM, Helius webhooks on Solana. Your server gets pushed the transaction within
  a block or two instead of waiting for the next poll. The parsing and
  formatting code here carries over unchanged.
- **Bot commands:** add a `getUpdates` listener to support `/add <chain> <addr>`,
  `/remove`, and `/list` so you can manage wallets from Telegram instead of
  editing `config.yaml`.
- **Per-wallet filters:** `min_usd_value` per entry, or an ignore-list of tokens.
- **More context:** append the token's market cap, liquidity and pair age from
  the Dexscreener response already being fetched in `tracker/prices.py`.

## Notes and limits

- Etherscan's free tier is shared across chains; with many wallets, raise
  `poll_interval_seconds` or upgrade the key.
- Contract interactions that move nothing in or out of the wallet (approvals,
  staking claims with no transfer) are classified `OTHER` and skipped.
- Prices come from DEX liquidity and can be wrong or missing for very new or
  very illiquid tokens — treat the USD figures as indicative.
