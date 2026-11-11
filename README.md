# My Work Log

**Your work day, written up for you.** My Work Log quietly collects what *you* did on your PC —
commits, files, browser work, VS Code, Claude Code / OpenCode sessions, terminal commands — and
when you shut the PC down it:

1. writes a polished summary of the day with **Claude Code** (e.g. `2. [Billing API] --> Fixed the invoice
   rounding bug and verified the monthly report totals.`),
2. puts it into your **Google Sheet** (A = Date, B = Work, C = Total Working Hours),
3. **emails** you the day's report (total hours, start / end / extra time, every task, last 7 days).

A local dashboard shows a live clock, your workday countdown (which turns into **Extra time** after 8 h),
today's summary, hours for every day, and lets you add meetings, visits and other offline work.

Works on **Linux** and **Windows 10 / 11**. Everything runs on your own PC.

---

## Install

You need **Python 3.9+** and (for AI summaries) **[Claude Code](https://docs.anthropic.com/en/docs/claude-code)**
signed in once (`npm install -g @anthropic-ai/claude-code`, then run `claude`). Without Claude Code it still
works and writes a simpler rule-based summary.

### Linux

```bash
git clone https://github.com/NahidDevIT/my-work-log.git
cd my-work-log
bash install.sh
```

### Windows

```powershell
git clone https://github.com/NahidDevIT/my-work-log.git
cd my-work-log
.\install.bat
```
(or download the ZIP from GitHub, unzip, and double-click **install.bat**)

### What the installer does — automatically

| Step | Linux | Windows |
|---|---|---|
| Python + PyYAML | uses system Python, else a `.venv`, else `apt` | finds Python (installs it with `winget` if missing) + `pip install pyyaml` |
| Detects | git, Claude Code, Chrome / Edge / Brave / Chromium / Firefox, VS Code | same |
| Your settings | asks name, role, email, projects folder (pre-filled from git) → `config.yaml`; every git repo in your projects folder becomes a project label | same |
| Dashboard on start-up | `@reboot` cron | Task Scheduler "MyWorkLog Dashboard" at sign-in |
| Save my day at **shutdown** | a small systemd service (asks your password once) | a sign-out script via local Group Policy (asks for admin once) |
| Safety nets | catch-up of a missed day after boot · 23:50 run if the PC is still on | catch-up after sign-in · 23:50 task |
| Opens | http://127.0.0.1:8765 | http://127.0.0.1:8765 |

Run it again any time — it is safe to repeat. `bash install.sh --yes` / `install.bat -Yes` skip the questions.

### Last step: connect your Google Sheet (2 minutes)

Dashboard → **Settings & help** → *Set up sheet sync*:

1. Create a sheet at **[sheets.new](https://sheets.new)** (the script adds the header row itself).
2. **Extensions → Apps Script** → paste the script from **Copy script** → **Save**.
3. **Deploy → New deployment → Web app** · Execute as **Me** · Who has access **Anyone** → **Deploy** → allow access.
4. Paste the Web-app URL into the dashboard → **Connect**. Then **Send test** in *Daily email*.

The script only accepts requests carrying your private key (made by the installer) and never
overwrites text you typed into the sheet yourself. The email is sent from your own Gmail by the same script.

---

## Daily use

* **Nothing to do.** Work as usual; shut down in the evening. After `email_after` (16:00 by default) the
  shutdown saves the day to the sheet **and** emails it; an earlier restart only saves to the sheet.
* **Dashboard** (http://127.0.0.1:8765):
  * clock + **workday countdown** from when you switched the PC on; after `workday_hours` it counts **Extra time**
  * **Overall summary** — highlight, *Total work hours · Start · End · Extra*, tasks, *View full summary*, *Regenerate*
  * week strip with hours per day; pick any day to see its hours and work
  * **Add work** — work done, or a **Meeting / Session / Visit / Training / Other** with a time.
    Inside your working day it is not counted twice; before you switched the PC on or after you
    shut it down it extends your hours (and Extra).
  * **Edit**, **Save my day now**, profile photo, light / dark theme
* **Column C** of the sheet: `Total work hours: 7h 33m · Start: 8:58 AM · End: 4:32 PM · Extra: 0h 00m`.

## Apps — PC and phone

**PC app.** The installer adds **My Work Log** to the app menu (Linux) / Start menu + Desktop (Windows):
it starts the dashboard if needed and opens it in its own window. Run `python3 desktop_app.py` to add it
later, `--remove` to take it away. Chrome / Edge also offer **Install My Work Log** on http://127.0.0.1:8765.

**Phone app.** Settings & help → **Open on my phone** → scan the QR code → **Install** / **Add to Home screen**.
The app (https://nahiddevit.github.io/my-work-log/, source in [`phone_app/`](phone_app)) keeps your private
link only on the phone (it arrives in the `#…` part of the address, which browsers never send to a website):

* **PC on + same Wi-Fi** → it opens your live dashboard by itself.
* **Mobile data / PC off** → your saved work from the Google Sheet; an open live dashboard comes back to
  the app within ~10 s when the PC can no longer be reached.

Needs the sheet script **version 6**.

## Desktop + lock-screen widget (Linux, GNOME)

`./gnome_widget/install.sh` adds a GNOME Shell extension that shows the clock and the workday countdown
on the desktop (top right, under the windows) and under the clock on the lock screen. On Wayland it
appears after logging out and in once. When the PC is left alone it locks itself after the usual
*Screen Blank* time, but the screen stays on so the countdown stays visible. `./gnome_widget/install.sh --remove`
takes it away again.

## Open on my phone — one link

Dashboard → **Settings & help** → **Open on my phone** → **Create my phone link**. You get **one private
link and one QR code**:

* **PC on** → the page shows *“My PC is on”* and opens your **live dashboard** (by itself when the phone is on
  the same network as the PC — otherwise one tap on **Open live dashboard**).
* **PC off** → a read-only page of your saved work from the Google Sheet: last-7-days totals and, for every
  day, *Total · Start · End · Extra* and all tasks — from any network.

How it knows: while the dashboard runs it tells the sheet's script “I'm on” every 2 minutes (and “I'm off”
at shutdown), with its live link. To notice “same network”, the phone page and the PC each look up their
public internet address (api.ipify.org) and compare them. Only people with the link can open it;
**New link** replaces it (the old one stops working). Needs the sheet script **version 5** — the card
shows the 1-minute update if yours is older.

**Live dashboard when the PC is on** (inside the same card): choose a password → **Turn on**.

* Works on the same Wi-Fi / office network. If Ubuntu's firewall is on, the card shows the one command
  that allows the port from your local network; on Windows click **Allow** when asked.
* Live view **from anywhere**: install [Tailscale](https://tailscale.com/download) on the PC and the phone.
  Nothing is opened to the public internet.
* This PC never needs the password. Phones get a 30-day sign-in; changing the password signs every
  device out; 5 wrong tries block that device for 5 minutes. The sheet key, sheet link, email recipients
  and phone settings can only be changed on the PC.
* **Turn off** puts the live dashboard back to *this PC only* (the link still shows the saved work).

## Settings — `config.yaml`

Created by the installer from [`config.example.yaml`](config.example.yaml). The useful bits:

| Key | What it does |
|---|---|
| `owner` | name, role, organization, email (default report recipient) |
| `automation.email_after` | shutdown after this time = end of day → sheet + email |
| `automation.workday_hours` | countdown length and the "Extra" threshold |
| `projects_root`, `modules` | where your repos live; folder/keyword → project label |
| `domain_labels`, `ai_extra_rules`, `vocabulary`, `people` | guide the AI's wording |
| `groups` | how the dashboard groups projects (regex → group) |
| `browser.block_domains` | personal sites that are never logged |

## Commands

```bash
python3 run_day.py                        # whole pipeline for today (add --email to also email)
python3 run_day.py --date 2026-11-09      # …for another day
python3 collect.py --date 2026-11-09      # only collect
python3 push.py --ping                    # test the sheet connection
python3 mail.py --date 2026-11-09 --test  # send a test email
python3 session.py shutdown|boot|fallback # what the automation runs
```
(on Windows use `py` instead of `python3`)

## Uninstall

```bash
bash install.sh --uninstall        # Linux
install.bat -Uninstall             # Windows
```
Removes the automation; your data and settings stay in the folder.

## Privacy

* Raw activity (`raw/`, `digest/`) never leaves your PC. The dashboard listens on `127.0.0.1` only.
* Only the final summary goes to your sheet / email; the AI step sends the day's *filtered* digest to Claude.
* Teammates' commits, blocked personal sites, plain web searches, passwords, tokens and account details are left out.
* `config.yaml`, `sheet_webhook.json`, `mail_settings.json` and all logs are git-ignored.

## How it works

```
 shutdown / sign-out ─┐   (or: next boot catch-up · 23:50 if still on)
                      ▼
 collect.py ─ browsers · git · files · VS Code · Claude Code · OpenCode · terminal → raw/ + digest/
                      ▼
 summarize.py ─ Claude Code (headless, no tools) → output/<date>.json  (+ your manual entries)
                      ▼
 push.py ─ Apps Script web app → sheet column B (work) + C (hours)
                      ▼
 mail.py ─ same script → HTML report from your Gmail
```

| File | Purpose |
|---|---|
| `install.sh`, `install.ps1` / `install.bat` | one-command setup, update and uninstall |
| `setup_config.py`, `config.example.yaml` | first-run settings wizard |
| `common.py` | settings, time zone, Linux / Windows differences |
| `collect.py`, `summarize.py`, `push.py`, `mail.py`, `run_day.py`, `session.py` | the pipeline |
| `server.py`, `ui/index.html` | the dashboard |
| `apps_script/Code.template.gs` | the sheet-side script (your key is filled in by *Copy script*) |
| `install_shutdown_hook.sh` | Linux shutdown service (called by `install.sh`) |
| `start.sh`, `start.bat` | start the dashboard by hand |

## Status

Built and used daily on Ubuntu (GNOME). The Windows installer and Windows-specific collectors are
written for Windows 10 / 11 but have **not yet been tested on a real Windows PC** — issues and fixes welcome.

## License

MIT — see [LICENSE](LICENSE).
