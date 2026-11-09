#!/usr/bin/env python3
"""My Work Log — email the day's work report (sent by the Apps Script in my sheet, from my Gmail).

Usage:  python3 mail.py --date 2026-11-09            send the report for that day
        python3 mail.py --date 2026-11-09 --test     same, subject marked [Test]
        python3 mail.py --date 2026-11-09 --preview out.html   write the HTML only, send nothing
Recipients live in mail_settings.json (editable from the dashboard → Settings & help).
"""
import argparse, html, json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import cfg as _cfg, now
SETTINGS = HERE / "mail_settings.json"
DEFAULT = {"enabled": True, "to": [e for e in [_cfg()["owner"].get("email", "")] if e]}
sys.path.insert(0, str(HERE))


def settings():
    try:
        s = {**DEFAULT, **json.loads(SETTINGS.read_text(encoding="utf-8"))}
    except Exception:
        s = dict(DEFAULT)
    s["to"] = [t.strip() for t in s.get("to", []) if isinstance(t, str) and "@" in t]
    return s


def save_settings(enabled, to):
    s = {"enabled": bool(enabled), "to": [t.strip() for t in to if t.strip()]}
    SETTINGS.write_text(json.dumps(s, indent=2), encoding="utf-8")
    return s


def _read(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


def hm(m):
    return f"{m // 60}h {m % 60}m" if m >= 60 else f"{m}m"


STATE = {"synced": ("In sheet", "#059669"), "approved": ("Saved", "#0369a1"),
         "draft": ("Draft", "#b45309"), "empty": ("No entry", "#7a8391")}


def build(date):
    """Returns (subject, html, text) for the day's report."""
    from server import cfg, formatted, overview, work_hours
    c = cfg()
    o = _read(HERE / "output" / f"{date}.json") or {}
    raw = _read(HERE / "raw" / f"{date}.json") or {}
    items = o.get("items", [])
    done = sum(1 for it in items if it.get("status", "").lower().startswith("complete"))
    doms = sorted({it["module"] for it in items if it.get("module") and not it["module"].startswith("[")})
    prog = len(items) - done
    start, end, _ = work_hours(date)
    worked = int((end - start).total_seconds() // 60) if start and end else 0
    wd_h = c.get("automation", {}).get("workday_hours", 8)
    extra = max(0, worked - int(float(wd_h) * 60))
    t12 = lambda t: t.strftime("%I:%M %p").lstrip("0") if t else "—"
    week = overview(date)["days"]
    e = html.escape
    owner = c["owner"]

    subject = f"My work — {formatted(date)} · {len(items)} task{'s' if len(items) != 1 else ''}"

    # ── grouped items
    groups = {}
    for it in items:
        groups.setdefault(it.get("module") or "Other", []).append(it)
    n, blocks = 0, []
    for mod, its in groups.items():
        rows = []
        for it in its:
            n += 1
            st = it.get("status", "") or "Noted"
            col = "#059669" if st.lower().startswith("complete") else "#b45309" if "progress" in st.lower() else "#0369a1"
            rows.append(f"""<tr><td style="padding:8px 0;vertical-align:top;color:#667080;font-weight:600;width:24px">{n}.</td>
              <td style="padding:8px 0"><div style="font-weight:600;color:#14171c">{e(it.get('action') or mod)}</div>
              <div style="color:#3d4552;margin-top:2px">{e(it.get('details', ''))}</div>
              <div style="margin-top:4px"><span style="font-size:12px;font-weight:600;color:{col}">● {e(st)}</span></div></td></tr>""")
        blocks.append(f"""<tr><td style="padding:16px 0 4px;font-size:13px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:#1f7fc4">{e(mod)}</td></tr>
          <tr><td><table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="font-size:14px;line-height:1.5">{''.join(rows)}</table></td></tr>""")
    body = "".join(blocks) or """<tr><td style="padding:16px 0;color:#667080">No work was logged for this day.</td></tr>"""

    stat = lambda v, l, c="#14171c": f"""<td style="padding:10px 4px;background:#f3f5f8;border-radius:10px;text-align:center;width:33%">
      <div style="font-size:20px;font-weight:700;color:{c};line-height:1.25">{v}</div><div style="font-size:12px;color:#667080">{l}</div></td>"""
    stats = f"""<table role="presentation" width="100%" cellspacing="6" cellpadding="0" style="table-layout:fixed">
      <tr>{stat(hm(worked) if worked else "—", "total work hours", "#059669")}{stat(t12(start), "start time")}{stat(t12(end), "end time")}</tr>
      <tr>{stat(f"{extra // 60}h {extra % 60:02d}m", f"extra time (over {wd_h}h)", "#b45309" if extra else "#7a8391")}{stat(f"{done}/{len(items)}", "tasks completed" + (f" · {prog} in progress" if prog else ""))}{stat(len(doms), "projects", "#0369a1")}</tr></table>"""

    hours = {}
    for d in week:
        s0, e0, _ = work_hours(d["date"])
        hours[d["date"]] = (s0, e0, int((e0 - s0).total_seconds() // 60) if s0 and e0 else 0)

    def span(dd):
        s0, e0, m = hours[dd]
        x = max(0, m - int(float(wd_h) * 60))
        ex = f" <span style='color:#b45309;font-weight:600'>+{hm(x)} extra</span>" if x else ""
        return f"{hm(m)}{ex}<br><span style='font-size:11px;color:#667080'>{t12(s0)}–{t12(e0)}</span>" if m else "—"

    wk_rows = []
    for d in week:
        od = _read(HERE / "output" / f"{d['date']}.json") or {}
        titles = "; ".join(it.get("action") or it.get("module", "") for it in od.get("items", [])) or "—"
        lab, col = STATE[d["state"]]
        x = datetime.strptime(d["date"], "%Y-%m-%d")
        bold = "font-weight:700;" if d["date"] == date else ""
        wk_rows.append(f"""<tr style="{bold}"><td style="padding:6px 8px 6px 0;white-space:nowrap;color:#14171c">{x:%a} {x.day} {x:%b}</td>
          <td style="padding:6px 8px;color:#3d4552">{e(titles)}</td>
          <td style="padding:6px 8px;white-space:nowrap;color:#3d4552;text-align:right">{span(d['date'])}</td>
          <td style="padding:6px 0 6px 8px;white-space:nowrap;color:{col};font-size:12px;font-weight:600">{lab}</td></tr>""")
    week_mins = sum(h[2] for h in hours.values())
    week_items = sum(d["items"] for d in week)

    page = f"""<!doctype html><html><body style="margin:0;background:#eef1f6;font-family:Inter,Segoe UI,Roboto,Arial,sans-serif">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:640px;background:#ffffff;border-radius:14px;border:1px solid #e2e6ec">
<tr><td style="padding:22px 24px 6px">
  <div style="font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:#059669">Daily work report</div>
  <div style="font-size:22px;font-weight:700;color:#14171c;margin-top:4px">{e(formatted(date))}</div>
  <div style="font-size:13px;color:#667080;margin-top:2px">{e(owner['name'])} · {e(owner['role'])} · {e(owner['organization'])}</div>
</td></tr>
<tr><td style="padding:10px 18px 0">{stats}</td></tr>
<tr><td style="padding:4px 24px 8px"><table role="presentation" width="100%" cellspacing="0" cellpadding="0">{body}</table></td></tr>
<tr><td style="padding:8px 24px 0"><div style="border-top:1px solid #e2e6ec"></div></td></tr>
<tr><td style="padding:14px 24px 4px"><div style="font-size:15px;font-weight:700;color:#14171c">Last 7 days</div>
  <div style="font-size:12.5px;color:#667080">{week_items} task(s) · {hm(week_mins)} worked</div></td></tr>
<tr><td style="padding:4px 24px 18px"><table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="font-size:13px;line-height:1.45">{''.join(wk_rows)}</table></td></tr>
<tr><td style="padding:12px 24px 20px;background:#f6f7f9;border-radius:0 0 14px 14px;font-size:12px;color:#667080">
  Sheet: <a href="{e(c['sheet'].get('url', ''))}" style="color:#1f7fc4">{e(c['sheet'].get('name') or 'My Work Log')}</a> · sent automatically by My Work Log</td></tr>
</table></td></tr></table></body></html>"""

    text = [f"Daily work report — {formatted(date)}", f"{owner['name']} · {owner['role']} · {owner['organization']}", "",
            f"Tasks completed {done}/{len(items)}{f' ({prog} in progress)' if prog else ''} · projects {len(doms)}",
            f"Work hours {hm(worked) if worked else '-'} · start {t12(start)} · end {t12(end)} · extra {hm(extra)}", "",
            o.get("work_summary_text") or "No work was logged for this day.", "", "Last 7 days:"]
    for d in week:
        s0, e0, m = hours[d["date"]]
        text.append(f"  {d['date']}  {d['items']} task(s)  {hm(m) + ' (' + t12(s0) + '-' + t12(e0) + ')' if m else '-'}  {STATE[d['state']][0]}")
    text += ["", f"Sheet: {c['sheet']['url']}"]
    return subject, page, "\n".join(text)


def send(date, test=False, to=None):
    from push import call
    s = settings()
    rcpt = to or s["to"]
    if not rcpt:
        raise RuntimeError("No recipient — add one in the dashboard → Settings & help")
    # An older script (v1) would treat "email" as a sheet write, so check the version first.
    if int(call({"action": "ping"}).get("version") or 1) < 2:
        raise RuntimeError("The script in the sheet is an older version — Settings & help → Copy script, "
                           "paste it into Apps Script, then Deploy → Manage deployments → edit → New version")
    subject, page, text = build(date)
    prev = (_read(HERE / "output" / f"{date}.json") or {}).get("emailed_text")
    if test:
        subject = "[Test] " + subject
    elif prev:
        subject += " (updated)"
    res = call({"action": "email", "to": rcpt, "subject": subject, "html": page, "text": text,
                "from_name": "My Work Log"})
    if res.get("ok") and not test:
        p = HERE / "output" / f"{date}.json"
        o = _read(p)
        if o is not None:
            o["emailed_at"] = now().isoformat(timespec="seconds")
            o["emailed_to"] = rcpt
            o["emailed_text"] = o.get("work_summary_text", "")
            p.write_text(json.dumps(o, indent=2, ensure_ascii=False), encoding="utf-8")
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=now().strftime("%Y-%m-%d"))
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--preview")
    a = ap.parse_args()
    try:
        if a.preview:
            subject, page, _ = build(a.date)
            Path(a.preview).write_text(page, encoding="utf-8")
            print(json.dumps({"ok": True, "subject": subject, "preview": a.preview}))
        else:
            print(json.dumps(send(a.date, a.test), ensure_ascii=False))
    except Exception as ex:
        print(json.dumps({"ok": False, "error": str(ex)}))
        sys.exit(1)
