#!/usr/bin/env python3
"""My Work Log — the end-of-day pipeline (what the 17:30 schedule runs).

  1. collect   — gather the day's activity from every source on this PC
  2. summarize — Claude writes polished accomplishment statements
                 (a summary you edited by hand is never replaced)
  3. push      — write it into my Google Sheet (if sheet sync is set up)
  4. email     — mail the day's work report (only with --email; once per day, again only if the text changed)

Run by session.py when I shut down the PC (after 16:00 with --email), on the next boot (catch-up)
and at 23:50 if the PC is still on.

Usage:  python3 run_day.py [--date YYYY-MM-DD] [--no-push] [--resummarize] [--keep-summary] [--email]
"""
import argparse, hashlib, json, subprocess, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common import HERE, cfg, tz

CFG = cfg()
TZ = tz()
STATUS = HERE / "last_run.json"


def log(msg):
    print(f"{datetime.now(TZ):%H:%M:%S}  {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(TZ).strftime("%Y-%m-%d"))
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--resummarize", action="store_true", help="replace even a hand-edited summary")
    ap.add_argument("--email", action="store_true", help="also email the day's work report (skipped if already sent)")
    ap.add_argument("--keep-summary", action="store_true", help="don't rewrite an existing summary (catch-up runs)")
    a = ap.parse_args()
    d, auto = a.date, CFG.get("automation", {})
    run = {"date": d, "started": datetime.now(TZ).isoformat(timespec="seconds"), "steps": {}}

    # 1. collect
    r = subprocess.run([sys.executable, str(HERE / "collect.py"), "--date", d], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=HERE)
    run["steps"]["collect"] = (r.stdout + r.stderr).strip().splitlines()[-1] if (r.stdout + r.stderr).strip() else "?"
    log("collect: " + run["steps"]["collect"])

    # 2. summarize
    sys.path.insert(0, str(HERE))
    from summarize import summarize
    p = HERE / "output" / f"{d}.json"
    existing = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    dg = HERE / "digest" / f"{d}.md"
    sha = hashlib.sha256(dg.read_bytes()).hexdigest()[:16] if dg.exists() else None
    if existing and existing.get("source") == "manual" and not a.resummarize:
        run["steps"]["summary"] = "kept your hand-edited summary"
    elif existing and existing.get("items") and a.keep_summary:
        run["steps"]["summary"] = "kept the existing summary"
    elif existing and existing.get("items") and existing.get("digest_sha") == sha and not a.resummarize:
        run["steps"]["summary"] = "no new activity since the last summary — kept it"
    elif auto.get("ai_summary", True):
        out, note = summarize(d, save=True)
        run["steps"]["summary"] = f"{note} — {len(out['items'])} item(s)"
        if p.exists():
            o = json.loads(p.read_text(encoding="utf-8"))
            o["digest_sha"] = sha
            p.write_text(json.dumps(o, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        run["steps"]["summary"] = "AI summary disabled in config"
    from server import merge_manual
    merge_manual(d)                               # my meetings / visits / offline work stay in the summary
    log("summary: " + run["steps"]["summary"])

    # 3. push
    from push import hook, push
    if a.no_push or not auto.get("auto_push", True):
        run["steps"]["push"] = "auto-push off"
    elif not hook():
        run["steps"]["push"] = "sheet sync not set up yet (dashboard → Settings)"
    else:
        try:
            res = push(d)
            run["steps"]["push"] = f"{res.get('status', res)} (row {res.get('row', '?')})"
            if res.get("status") == "cell_not_empty":
                run["steps"]["push"] = f"skipped — row {res.get('row')} already has text you wrote by hand"
        except Exception as e:
            run["steps"]["push"] = f"failed: {e}"
    log("push: " + run["steps"]["push"])

    # 4. email
    if a.email:
        from mail import send, settings
        if not settings()["enabled"]:
            run["steps"]["email"] = "daily email is off (dashboard → Settings)"
        elif not hook():
            run["steps"]["email"] = "needs the sheet script set up first (dashboard → Settings)"
        elif not (cur := json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}).get("items"):
            run["steps"]["email"] = "nothing logged — no email"
        elif cur.get("emailed_text") == cur.get("work_summary_text"):
            run["steps"]["email"] = f"already emailed at {cur.get('emailed_at', '?')[11:16]}"
        else:
            try:
                res = send(d)
                run["steps"]["email"] = (f"sent to {', '.join(res.get('to', []))}" if res.get("ok")
                                         else f"failed: {res.get('error') or res}")
            except Exception as e:
                run["steps"]["email"] = f"failed: {e}"
        log("email: " + run["steps"]["email"])

    run["finished"] = datetime.now(TZ).isoformat(timespec="seconds")
    STATUS.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
