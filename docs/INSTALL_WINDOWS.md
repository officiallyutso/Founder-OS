# Founder OS — Windows self-host install guide

Run Founder OS 24/7 on your own Windows PC as a lightweight background service, with
vectors stored in a free **Qdrant Cloud** cluster. No credit card, no monthly bill —
just a machine that stays on.

> The bot uses Telegram **long-polling**, so it needs no public ports — only outbound
> internet. Memory footprint is ~300–500 MB (vectors live in the cloud; embeddings are
> computed locally).

---

## 1. Prerequisites

- **Windows 10/11** with **Python 3.11+** installed (`py --version` should work).
- A **Telegram bot token** from [@BotFather](https://t.me/BotFather).
- Your numeric **Telegram user ID** from [@userinfobot](https://t.me/userinfobot).
- At least one **LLM API key**: Groq, Google Gemini, or OpenAI.
- (Optional) `SERPER_API_KEY` / `TAVILY_API_KEY` for web search, Google/X creds, etc.

---

## 2. Get the code & configure `.env`

```powershell
git clone <your-repo-url> FOUDNER_OS
cd FOUDNER_OS
copy .env.example .env
notepad .env
```

Fill in at minimum:

```bash
TELEGRAM_BOT_TOKEN=...        # from BotFather
MY_TELEGRAM_USER_ID=...       # your numeric id

# any/all you have — the agent picks among them
GROQ_API_KEY=...
GOOGLE_GEMINI_API_KEY=...
OPENAI_API_KEY=...

# store vectors in the cloud (see step 3)
VECTOR_BACKEND=qdrant
QDRANT_URL=https://...:6333
QDRANT_API_KEY=...

# save memory: skip the local web panel (optional)
DASHBOARD_ENABLED=false
```

---

## 3. Create a free Qdrant Cloud cluster

1. Sign up at <https://cloud.qdrant.io> (no credit card).
2. **Create a cluster** → **Free** tier (1 GB RAM / 4 GB disk, ~1M vectors). Pick the
   nearest region.
3. When it's **healthy**, copy:
   - the **Endpoint URL** (keep the `:6333`), and
   - an **API key** (create one in the cluster's API Keys / Connect panel).
4. Paste both into `.env` (`QDRANT_URL`, `QDRANT_API_KEY`).

> Want to keep vectors **local** instead? Set `VECTOR_BACKEND=chroma` and skip this
> step — they'll be stored on disk under `data/chroma`.

---

## 4. First run (foreground test)

```powershell
.\founder_os.bat
```

The first run creates a `.venv` and installs dependencies (slow once). When you see
`Bot is running`, message your bot on Telegram — it should reply. Press `Ctrl+C` /
close the window to stop the test.

---

## 5. Run it 24/7 as a background service

This starts the bot **hidden** (no window), **auto-restarts** it on crash, and
**auto-starts** it every time you log in.

**a) Register auto-start at logon** (creates a shortcut in your Startup folder — no
admin needed). In PowerShell from the project folder:

```powershell
$startup = [Environment]::GetFolderPath('Startup')
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut("$startup\FounderOS.lnk")
$sc.TargetPath = "$PWD\start_hidden.vbs"
$sc.WorkingDirectory = "$PWD"
$sc.Save()
"Created $startup\FounderOS.lnk"
```

**b) Start it now without logging off:**

```powershell
wscript "$PWD\start_hidden.vbs"
```

> **Important:** never run `founder_os.bat` (foreground) at the same time as the
> service — two bots polling one token makes Telegram error (409). Use one or the
> other.

What the pieces do:
- `founder_os_service.bat` — runs the bot in a loop, relaunching within 10s if it exits.
- `start_hidden.vbs` — launches that loop with no visible window.
- `FounderOS.lnk` (in Startup) — runs `start_hidden.vbs` automatically at each logon.
- `stop_founder_os.bat` — stops the loop and the bot.

---

## 6. Keep the PC awake (so scheduled jobs fire) — needs admin

A sleeping PC freezes the bot, so the nightly backup (02:00), briefing (08:00),
follow-ups, etc. won't run while asleep. To prevent **automatic sleep while plugged
in**, open **PowerShell as Administrator** and run:

```powershell
powercfg /change standby-timeout-ac 0     # 0 = never sleep on AC
powercfg /change hibernate-timeout-ac 0
```

- This is a standard, reversible Windows power setting; your **screen can still turn
  off**. On a **laptop**, only plugged-in (AC) behavior changes — it still sleeps on
  battery.
- To restore normal sleep later: `powercfg /change standby-timeout-ac 30` (30 min).
- Optional: skip this if you're OK with the bot only doing proactive tasks while the
  PC is awake.

---

## 7. Test everything works

1. **Replies:** message the bot on Telegram → you get a response.
2. **Vectors flowing:** after a couple of messages, run:
   ```powershell
   .\.venv\Scripts\python.exe scripts\check_qdrant.py
   ```
   You should see collections (`conversations`, …) with climbing vector counts. You
   can also see them in the Qdrant Cloud dashboard → **Collections**.
3. **Running hidden:** confirm there's no console window, and the process is alive:
   ```powershell
   Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*main.py*' } |
     Select-Object ProcessId, ExecutablePath
   ```
   (On Windows a venv shows **two** processes — the `.venv` launcher + the base
   interpreter — that's one bot, not two.)
4. **Logs:** tail `data\logs\founder_os.log` — look for `Bot is running` and repeated
   `getUpdates ... 200 OK` with no `409 Conflict`.
5. **Survives reboot (the real test):** restart the PC, log in, wait ~30–60s, then
   message the bot — it should reply **without you starting anything**.

---

## 8. Managing it day-to-day

| Action | Command |
|---|---|
| Stop the bot | `.\stop_founder_os.bat` |
| Start manually (hidden) | `wscript "$PWD\start_hidden.vbs"` |
| Check Qdrant | `.\.venv\Scripts\python.exe scripts\check_qdrant.py` |
| View logs | open `data\logs\founder_os.log` |
| Update to latest code | `git pull` then stop & start |
| Disable auto-start | delete `…\Startup\FounderOS.lnk` |

---

## 9. Troubleshooting

- **`No module named 'qdrant_client'`** — your `.venv` predates the dependency.
  Reinstall: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.
- **Bot doesn't reply / `409 Conflict` in logs** — two instances are polling. Run
  `.\stop_founder_os.bat`, then start once.
- **`check_qdrant` says "no collections yet"** — normal until the bot handles its
  first write; message it, then re-run.
- **`powercfg` → "Access is denied"** — you must run PowerShell **as Administrator**.
- **Qdrant `[FAIL] Could not reach`** — check the URL keeps `:6333`, the API key is
  right, and the cluster is healthy in the dashboard.
- **Switching backends** — moving Chroma↔Qdrant starts the new store empty. To carry
  existing vectors: `python scripts\migrate_chroma_to_qdrant.py` before flipping
  `VECTOR_BACKEND`.
