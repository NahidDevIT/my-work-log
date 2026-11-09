#!/usr/bin/env python3
"""My Work Log — PC on/off triggers.

  python3 session.py shutdown   PC is shutting down (system service, see install_shutdown_hook.sh):
                                after automation.email_after (16:00) → collect → AI → sheet → email;
                                earlier (a restart in the day)        → collect → AI → sheet only.
  python3 session.py boot       after boot (@reboot cron): catch up the last work day if its
                                sheet sync or email did not happen (e.g. power cut, forced off).
  python3 session.py fallback   23:50 cron: the PC is still on — save + email today if not done yet.

Every event is appended to sessions.log.
"""
import json, socket, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import HERE, boot_time, cfg, tz

CFG = cfg()
AUTO = CFG.get("automation", {})
TZ = tz()
LOG = HERE / "sessions.log"


def log(msg):
    line = f"{datetime.now(TZ):%F %T}  {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def run_day(date, *args, timeout=140):
    try:
        r = subprocess.run([sys.executable, str(HERE / "run_day.py"), "--date", date, *args],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, cwd=HERE)
        for line in (r.stdout + r.stderr).strip().splitlines():
            log("   " + line)
    except subprocess.TimeoutExpired:
        log("   run_day timed out — the next boot will catch up")


def online(timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        try:
            socket.create_connection(("script.google.com", 443), timeout=5).close()
            return True
        except OSError:
            time.sleep(3)
    return False


def done(date):
    o = read(HERE / "output" / f"{date}.json") or {}
    if not o.get("items"):
        return True
    text = o.get("work_summary_text")
    return o.get("pushed_text") == text and o.get("emailed_text") == text


def mark(d, key, when):
    """sessions/<date>.json: first pc_on and last pc_off of the day (used for work hours)."""
    p = HERE / "sessions" / f"{d}.json"
    p.parent.mkdir(exist_ok=True)
    s = read(p) or {}
    if key == "pc_on" and s.get("pc_on") and s["pc_on"] <= when:
        return
    s[key] = when
    p.write_text(json.dumps(s, indent=2), encoding="utf-8")


def shutdown():
    now = datetime.now(TZ)
    d = now.strftime("%Y-%m-%d")
    mark(d, "pc_off", now.replace(tzinfo=None).isoformat(timespec="seconds"))
    try:                                          # the phone link switches to "PC is off" right away
        from server import send_heartbeat
        send_heartbeat(False)
    except Exception:
        pass
    end_of_day = now.strftime("%H:%M") >= AUTO.get("email_after", "16:00")
    log(f"PC shutting down — {'end of day: sheet + email' if end_of_day else 'before ' + AUTO.get('email_after', '16:00') + ': sheet only'}")
    run_day(d, *(["--email"] if end_of_day else []))


def boot():
    try:
        bt = boot_time()
        mark(bt.strftime("%Y-%m-%d"), "pc_on", bt.isoformat(timespec="seconds"))
    except Exception:
        pass
    log("PC started — checking for a day that was not finished")
    if not online():
        return log("   no internet — skipped catch-up")
    today = datetime.now(TZ).date()
    since = str(AUTO.get("catchup_since", "2000-01-01"))
    for back in range(1, 6):                      # the most recent earlier day with my activity
        d = (today - timedelta(days=back)).strftime("%Y-%m-%d")
        if d < since:
            break
        raw = read(HERE / "raw" / f"{d}.json")
        if raw is None:
            subprocess.run([sys.executable, str(HERE / "collect.py"), "--date", d], capture_output=True, cwd=HERE)
            raw = read(HERE / "raw" / f"{d}.json") or {}
        if not raw.get("events"):
            continue
        if done(d):
            log(f"   {d}: already in the sheet and emailed")
        else:
            log(f"   {d}: finishing it now")
            run_day(d, "--email", "--keep-summary", timeout=300)
        break


def fallback():
    d = datetime.now(TZ).strftime("%Y-%m-%d")
    log("Late-night check — the PC is still on")
    run_day(d, "--email")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    {"shutdown": shutdown, "boot": boot, "fallback": fallback}.get(mode, lambda: sys.exit(__doc__))()
