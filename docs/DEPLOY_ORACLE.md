# Deploying Founder OS on Oracle Cloud Always Free (ARM)

This guide hosts the **entire** agent — the always-on Telegram bot, the APScheduler
jobs (heartbeat, daily briefing, follow-ups, monitors, nightly backups), the SQLite
brain and the vector store — on a single **Oracle Cloud Always Free** Ampere A1 (ARM)
VM for **$0/month**.

The bot uses Telegram **long-polling**, so it needs **no public inbound port** —
only outbound internet (Telegram + your LLM/API providers). That makes it ideal for
a locked-down free VM.

---

## Why Oracle Always Free (and the caveats)

**What you get (free forever):** a pool of 3,000 OCPU-hours + 18,000 GB-hours/month
= up to **4 OCPUs / 24 GB RAM** running 24×7, **200 GB** block storage, 10 TB/month
egress.

**Caveats to know up front:**
- **ARM64 only.** Every image/wheel must be arm64. This project's base image
  (`python:3.11-slim`) is multi-arch and all dependencies have arm64 wheels, so a
  build on the VM "just works" — it's only a bit slower the first time.
- **Idle reclamation.** Oracle may reclaim an Always-Free VM if, over 7 days, CPU,
  network *and* memory 95th-percentile are all under 20%. A chatty cofounder + a
  small keep-alive (Step 8) stays comfortably above the line.
- **Capacity.** "Out of host capacity" errors are common when creating A1 shapes —
  retry in another Availability Domain, ask for a smaller shape (1–2 OCPU is plenty
  for this app), or retry over a few hours.

> Prefer zero quirks? Any ~$5/mo VPS (Hetzner / DigitalOcean / Linode) runs the exact
> same steps from **Step 3** onward, without ARM or reclamation concerns.

---

## Prerequisites

- An Oracle Cloud account (free tier).
- Your secrets ready: `TELEGRAM_BOT_TOKEN`, at least one LLM key
  (`GROQ_API_KEY` / `GOOGLE_GEMINI_API_KEY` / `OPENAI_API_KEY`), and your
  `MY_TELEGRAM_USER_ID`. See the main README for the full `.env` reference.

---

## Step 1 — Create the VM

In the OCI console: **Compute → Instances → Create instance**.

- **Image:** Canonical **Ubuntu 22.04 (aarch64)**.
- **Shape:** `VM.Standard.A1.Flex` → **2 OCPU / 12 GB** is a comfortable, free-tier
  size for this app (1 OCPU / 6 GB also works). Leave headroom in your free pool.
- **Boot volume:** 50 GB is fine (leaves ~150 GB of your 200 GB for data if you ever
  attach a data disk).
- **SSH keys:** upload your public key (you'll SSH in as user `ubuntu`).
- Create, and note the **public IP**.

## Step 2 — Networking (no inbound needed)

Because the bot polls Telegram, you do **not** need to open any inbound ports. Keep
the default security list (SSH/22 only). **Do not** expose the dashboard port (8787)
publicly — you'll reach it via an SSH tunnel later if you want it.

## Step 3 — Install Docker

SSH in and install Docker + the Compose plugin:

```bash
ssh ubuntu@<your-public-ip>

sudo apt-get update && sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# log out/in (or: newgrp docker) so the group change takes effect
exit
```

## Step 4 — Get the code and configure

```bash
ssh ubuntu@<your-public-ip>

git clone <your-repo-url> founder-os && cd founder-os
cp .env.example .env
nano .env            # fill in tokens/keys; set MY_TELEGRAM_USER_ID
```

Leave `VECTOR_BACKEND=chroma` (the default) to keep vectors local on the VM's disk.
To use managed vectors instead, see **Step 7**.

## Step 5 — Run it 24/7

```bash
docker compose up -d --build     # first ARM build takes a few minutes
docker compose logs -f           # watch it boot; Ctrl-C to stop watching
```

`docker-compose.yml` mounts `./data`, so the SQLite brain + Chroma vectors + nightly
backups persist across rebuilds and reboots. `restart: unless-stopped` brings it back
after a crash or VM reboot.

## Step 6 — Verify

Message your bot on Telegram. You should get a reply. Check health anytime with:

```bash
docker compose ps
docker compose logs --tail=100
```

---

## Step 7 — (Optional) Use Qdrant Cloud free for vectors

Useful if you'd rather keep vectors in a managed cluster (or move to a host without a
good persistent disk). The free Qdrant Cloud cluster (1 GB RAM, 4 GB disk, ~1M
768-dim vectors) is free forever; it only auto-suspends after a *week of inactivity*,
which won't happen for a live bot.

1. Create a free cluster at <https://cloud.qdrant.io>, then copy its **URL** and an
   **API key**.
2. In `.env`:
   ```bash
   VECTOR_BACKEND=qdrant
   QDRANT_URL=https://xxxx.cloud.qdrant.io:6333
   QDRANT_API_KEY=your-key
   ```
3. `docker compose up -d --build` to restart.

Embeddings are still computed locally with the same model, so Chroma and Qdrant are
interchangeable. To carry your **existing** vectors over (instead of starting empty),
run the one-shot migration **before** flipping the backend — with `QDRANT_URL` /
`QDRANT_API_KEY` set in `.env`:

```bash
docker compose run --rm founder-os python scripts/migrate_chroma_to_qdrant.py
```

It copies the stored embeddings directly (no re-embedding). The SQLite knowledge
graph, CRM and notes are unaffected since they live in SQLite, not the vector store.

---

## Step 8 — (Oracle only) Keep the VM from being reclaimed

A light, polite keep-alive that nudges CPU for 60s every 5 min keeps utilization above
Oracle's idle threshold without wasting the box:

```bash
sudo apt-get install -y stress-ng
( crontab -l 2>/dev/null; echo '*/5 * * * * /usr/bin/stress-ng --cpu 1 --timeout 60s >/dev/null 2>&1' ) | crontab -
```

## Step 9 — Updates, backups, dashboard

**Update to latest code:**
```bash
cd founder-os && git pull && docker compose up -d --build
```

**Backups:** the app already zips the whole brain into `data/backups/` nightly (last
14 kept); trigger one anytime by telling the bot "back up now". For off-box safety,
periodically copy `data/backups/` elsewhere, e.g.:
```bash
scp ubuntu@<your-public-ip>:~/founder-os/data/backups/*.zip ./
```

**Dashboard (optional):** it binds to localhost inside the container for safety. To
view it, enable host networking and tunnel in:
1. Uncomment `network_mode: host` in `docker-compose.yml`, then
   `docker compose up -d`.
2. From your laptop: `ssh -L 8787:localhost:8787 ubuntu@<your-public-ip>` and open
   <http://localhost:8787>.

---

## Other hosting options (quick reference)

| Host | Cost | Notes |
|---|---|---|
| **Oracle Always Free ARM** | $0 | This guide. ARM + idle-reclamation caveats. |
| **VPS** (Hetzner/DO/Linode) | ~$5/mo | Same steps from Step 3. Most reliable, no quirks. |
| **Railway Hobby** | ~$5/mo | PaaS; attach a 5 GB volume at `/app/data`. |
| **Render** | free worker is ephemeral | Needs a paid disk (~$7/mo) **or** move state off-box (Qdrant + Postgres). |
| **Fly.io** | ~$5/mo | No free tier since 2024. |
