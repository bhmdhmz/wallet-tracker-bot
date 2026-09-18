# Deploying the tracker

The same code runs in three modes, selected by environment variables:

| Mode | Trigger | Use for |
|---|---|---|
| Loop | default | VM, background worker, Docker |
| Loop + health endpoint | `PORT` is set | Render / Koyeb / Cloud Run web services |
| One pass, then exit | `RUN_ONCE=1` | Cron jobs, GitHub Actions |

Wallets can come from `config.yaml` **or** from a `WALLETS_JSON` environment
variable. On any hosted platform use the env var — no addresses in your repo,
and changing the list doesn't need a redeploy:

```json
[{"label":"Whale ETH","chain":"ethereum","address":"0x..."},
 {"label":"SOL trader","chain":"solana","address":"7xKX..."}]
```

## The honest comparison

A tracker is only useful if it's running when the wallet trades, so the thing
to look at is whether a platform keeps a process alive for free.

| Platform | Always on | Cost | Trade-off |
|---|---|---|---|
| **Oracle Cloud Always Free** | Yes | $0 | Real ARM VM, free indefinitely. Card required for identity check; signup is the fiddliest of the bunch. Best free fit. |
| **GitHub Actions** | No — every 5 min | $0 | No infrastructure at all. Schedule is best-effort and often runs late; 5 min is the floor. |
| **Northflank** free plan | Yes | $0 | Managed, workers are first-class. Card required. |
| **Render** web service | No — sleeps at 15 min idle | $0 | Needs an external pinger; still misses trades during cold starts. |
| **Render** background worker | Yes | $7/mo | Cleanest managed option, no free worker tier. |
| **Any cheap VPS** (Hetzner etc.) | Yes | ~€4/mo | Full control, use the systemd unit in the README. |

My suggestion: **Oracle Cloud's always-free VM** if you want it free and
reliable, **GitHub Actions** if you want zero setup and can live with 5-minute
checks, **Render's $7 worker** if you'd rather pay a little than manage a box.

---

## Option 1 — Render

`render.yaml` in this repo is a Blueprint. Push the repo to GitHub, then go to
Render → Blueprints → New Blueprint Instance and point it at the repo.

It defaults to a **web service on the free plan**, because that's the only free
instance type Render offers. Fill in the secrets it prompts for
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `ETHERSCAN_API_KEY`,
`SOLANA_RPC_URL`, `WALLETS_JSON`) and deploy.

Two things to handle on the free plan:

1. **It sleeps after 15 minutes without inbound traffic.** Create a free monitor
   at cron-job.org or UptimeRobot hitting
   `https://<your-app>.onrender.com/healthz` every 10 minutes. That endpoint
   also reports uptime, last poll time and alerts sent.
2. **The filesystem is ephemeral.** `STATE_FILE` is set to `/tmp/state.json`;
   on restart the tracker resumes from the current chain head. You won't get
   duplicate alerts, but you may miss trades that happened while it was down
   — and any wallet you added or muted from Telegram since the last deploy is
   gone too, since it only lived in that wiped file. If you're actively
   managing wallets from the chat, Oracle Cloud's real disk (Option 2) or a
   paid Render instance with a persistent disk add-on avoids this.

For an always-on setup, edit `render.yaml`: change `type: web` to
`type: worker`, drop the `healthCheckPath` line, and set `plan: starter`
($7/month). No pinger needed then.

## Option 2 — Oracle Cloud Always Free (recommended if free matters)

Create an **Always Free** Ampere A1 instance (Ubuntu), then:

```bash
sudo apt update && sudo apt install -y python3-pip git
git clone <your-repo> /opt/wallet-tracker && cd /opt/wallet-tracker
pip3 install -r requirements.txt --break-system-packages
cp .env.example .env && nano .env       # fill in secrets
nano config.yaml                        # add your wallets
```

Then install the systemd unit from the README's "Running it continuously"
section. It restarts on crash and on reboot, state persists on real disk, and
nothing sleeps.

Docker works too if you prefer:

```bash
docker compose up -d      # uses Dockerfile + docker-compose.yml, named volume for state
docker compose logs -f
```

## Option 3 — GitHub Actions (no server at all)

`.github/workflows/track.yml` runs one pass every 5 minutes and commits
`state.json` back to the repo so the next run knows where it stopped.

1. Push this repo to GitHub (private is fine).
2. Settings → Secrets and variables → Actions → add `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, `ETHERSCAN_API_KEY`, `SOLANA_RPC_URL`, `WALLETS_JSON`.
3. Actions tab → enable workflows → trigger it once manually to verify.

Caveats: scheduled workflows are queued on a best-effort basis and frequently
run several minutes late, and private repos consume your monthly Actions
minutes (~2,000 free). A run takes a few seconds, so the budget is not the
issue — the delay is. Fine for following a swing trader, not for sniping.

## Option 4 — Northflank / Koyeb / Cloud Run / Fly

All of these consume the `Dockerfile` directly. Deploy it as a **worker /
background service** with no port if the platform allows it; otherwise deploy
as a web service and set `PORT`, and the health endpoint will bind for you.

## Notes that apply everywhere

- Keep `POLL_INTERVAL_SECONDS` at 20 or more on a free Etherscan key
  (~5 calls/second, shared across chains and wallets).
- The public Solana RPC rate-limits aggressively under continuous polling. A
  free Helius or QuickNode endpoint in `SOLANA_RPC_URL` is worth the two
  minutes it takes to sign up.
- Set `STARTUP_MESSAGE=0` to suppress the "tracker started" Telegram ping if
  your platform restarts the service often.
- Never commit `.env`. On PaaS, use the platform's secret storage.
