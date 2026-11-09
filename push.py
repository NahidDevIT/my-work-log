#!/usr/bin/env python3
"""My Work Log — write a day's summary (column B) and working hours (column C) into my Google Sheet.

Usage:  python3 push.py --date 2026-11-09 [--force]
        python3 push.py --ping            (test the connection)
Talks to the Apps Script webhook in your sheet (see apps_script/SETUP.md).
"""
import argparse, json, sys, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import now
HOOK = HERE / "sheet_webhook.json"


def hook():
    try:
        h = json.loads(HOOK.read_text(encoding="utf-8"))
    except Exception:
        return None
    return h if h.get("url", "").startswith("https://script.google.com/") and h.get("token") else None


def call(payload, timeout=60):
    h = hook()
    if not h:
        raise RuntimeError("Sheet sync is not set up yet — open the dashboard → Settings")
    body = json.dumps({**payload, "token": h["token"]}).encode()
    req = urllib.request.Request(h["url"], data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # Apps Script answers via a 302 redirect
        txt = r.read().decode()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        raise RuntimeError("Unexpected reply from Apps Script (is the web app deployed with access 'Anyone'?)")


def push(date, force=False):
    """Column B = the day's work, column C = working hours (total / start / end / extra)."""
    sys.path.insert(0, str(HERE))
    from server import hours_text
    p = HERE / "output" / f"{date}.json"
    if not p.exists():
        raise RuntimeError(f"no summary for {date}")
    s = json.loads(p.read_text(encoding="utf-8"))
    text = s.get("work_summary_text", "").strip()
    if not text:
        return {"ok": False, "status": "nothing_to_push"}
    hours = hours_text(date)
    if s.get("pushed_text") == text and s.get("pushed_hours", "") == hours and not force:
        return {"ok": True, "status": "already_up_to_date", "row": s.get("pushed_row")}
    res = call({"action": "write", "date": date, "formatted_date": s["formatted_date"], "text": text,
                "expected_previous": s.get("pushed_text", ""), "hours": hours,
                "expected_previous_hours": s.get("pushed_hours", ""), "force": force})
    changed = False
    if res.get("ok"):
        s.update(pushed_text=text, pushed_row=res.get("row"), pushed_to_sheet=f"Sheet1!B{res.get('row')}",
                 pushed_at=now().isoformat(timespec="seconds"),
                 approved=True)
        changed = True
    if res.get("hours_status") == "written":          # only scripts of version 3+ write column C
        s["pushed_hours"] = hours
        changed = True
    if changed:
        p.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding="utf-8")
    return res


def backfill_hours():
    """Fill column C for every day this app already wrote into the sheet."""
    sys.path.insert(0, str(HERE))
    from server import hours_text
    done = []
    for f in sorted((HERE / "output").glob("*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))
        if s.get("pushed_row") and s.get("pushed_text") and s.get("pushed_hours", "") != hours_text(f.stem):
            r = push(f.stem)
            done.append(f"{f.stem}: C {r.get('hours_status')}")
    return {"ok": True, "backfilled": done}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--ping", action="store_true")
    ap.add_argument("--backfill-hours", action="store_true")
    a = ap.parse_args()
    try:
        out = call({"action": "ping"}) if a.ping else backfill_hours() if a.backfill_hours else push(a.date, a.force)
        print(json.dumps(out, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)
