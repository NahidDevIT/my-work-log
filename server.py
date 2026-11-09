#!/usr/bin/env python3
"""My Work Log — local web dashboard.

Run:  python3 server.py        then open http://127.0.0.1:8765
Binds to localhost only: raw activity logs never leave this machine.
"""
import base64, hashlib, hmac, json, os, re, secrets, socket, subprocess, sys, threading, time, uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from common import HERE, IS_WIN, boot_time, boots, cfg, install_command, platform_name, read_json, \
    safety_nets_status, shutdown_hook_status

PORT = int(os.environ.get("WORKLOG_PORT", 8765))
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ORIGINS = (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}")


def formatted(d):
    x = datetime.strptime(d, "%Y-%m-%d")
    return f"{x:%A}, {x:%B} {x.day}, {x.year}"


# ---------------------------------------------------------------- summary model
def line_for(i, it):
    mod = it.get("module", "").strip()
    tag = mod if mod.startswith("[") else f"[{mod}]"
    body = it.get("details", "").strip() or it.get("action", "").strip()
    return f"{i}. {tag} --> {body}"


def build(d, items, approved=False):
    cats = sorted({it["module"] for it in items if it.get("module") and not it["module"].startswith("[")})
    return {"date": d, "formatted_date": formatted(d),
            "work_summary_text": "\n".join(line_for(i, it) for i, it in enumerate(items, 1)),
            "categories_involved": cats, "items": items, "approved": approved}


# ---------------------------------------------------------------- manual entries (meetings, visits …)
KINDS = ("Work", "Meeting", "Session", "Visit", "Training", "Other")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def manual_entries(d):
    return read_json(HERE / "manual" / f"{d}.json") or []


def save_manual(d, entries):
    (HERE / "manual").mkdir(exist_ok=True)
    (HERE / "manual" / f"{d}.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def t12s(hm):
    h, m = map(int, hm.split(":"))
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def manual_item(e):
    when = f" ({t12s(e['start'])}–{t12s(e['end'])})" if e.get("start") and e.get("end") else \
           f" ({t12s(e['start'])})" if e.get("start") else ""
    kind = e.get("kind") or "Work"
    text = e["text"].rstrip(".")
    prefix = f"{kind}: " if kind != "Work" and not text.lower().startswith(kind.lower()) else ""
    details = prefix + text + when + "."
    title = e.get("title") or (kind if kind != "Work" else text.split(".")[0][:60])
    return {"module": e.get("module") or kind, "action": title, "details": details,
            "status": e.get("status") or "Completed", "manual": True, "kind": kind,
            "start": e.get("start", ""), "end": e.get("end", ""), "id": e["id"]}


def merge_manual(d):
    """Put my manual entries (meetings, visits, offline work) into the day's summary — after the AI items,
    replacing any earlier copy — so an AI rewrite never loses them."""
    entries = manual_entries(d)
    p = HERE / "output" / f"{d}.json"
    o = read_json(p)
    if o is None and not entries:
        return None
    o = o or {}
    keep = [it for it in o.get("items", []) if not it.get("manual")]
    entries = sorted(entries, key=lambda e: e.get("start") or "99:99")
    new = build(d, keep + [manual_item(e) for e in entries], o.get("approved", False))
    for k, v in o.items():
        if k not in new:
            new[k] = v
    (HERE / "output").mkdir(exist_ok=True)
    p.write_text(json.dumps(new, indent=2, ensure_ascii=False), encoding="utf-8")
    return new


def draft(d):
    """Rule-based fallback draft (used when Claude is unavailable)."""
    raw = read_json(HERE / "raw" / f"{d}.json") or {"events": []}
    by = defaultdict(list)
    for e in raw["events"]:
        by[e["module"]].append(e)
    items = []
    for mod, evs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        mine = [e["text"].split(": ", 1)[1].split(" [")[0] for e in evs if e["src"] == "git" and e.get("mine")]
        sessions = sorted({m.group(1) for e in evs for m in [re.search(r"\[session: ([^\]]+)\]", e["text"])]
                           if m and not re.fullmatch(r"[0-9a-f]{8}", m.group(1))})
        parts = []
        if mine:
            parts.append("Delivered: " + "; ".join(mine[:6]))
        if sessions:
            parts.append("Worked on " + "; ".join(sessions[:4]))
        files = [e for e in evs if e["src"] in ("files-changed", "files-opened", "vscode")]
        if files:
            parts.append(f"Worked with {len(files)} file(s)")
        if not parts:
            continue
        items.append({"module": "[Unspecified Activity]" if mod == "[Unspecified]" else mod,
                      "action": "Development" if mine else "Activity",
                      "details": ". ".join(parts) + ".", "status": "Completed"})
    return build(d, items)


# ---------------------------------------------------------------- views
def day_state(o):
    if not o or not o.get("items"):
        return "empty"
    if o.get("pushed_text") and o.get("pushed_text") == o.get("work_summary_text"):
        return "synced"
    return "approved" if o.get("approved") else "draft"


def list_dates():
    dates = {f.stem for sub in ("raw", "output") for f in (HERE / sub).glob("*.json") if DATE_RE.match(f.stem)}
    out = []
    for d in sorted(dates, reverse=True):
        o = read_json(HERE / "output" / f"{d}.json")
        r = read_json(HERE / "raw" / f"{d}.json") or {}
        out.append({"date": d, "state": day_state(o), "source": (o or {}).get("source", ""),
                    "events": len(r.get("events", [])), "items": len((o or {}).get("items", []))})
    return out


def active_minutes(raw):
    tot = 0
    for b in (raw or {}).get("active_blocks", []):
        s, e = b.split("-")
        tm = lambda x: int(x[:2]) * 60 + int(x[3:])
        tot += max(tm(e) - tm(s), 1)
    return tot


def overview(end_date, days=7):
    end = datetime.strptime(end_date, "%Y-%m-%d")
    rows = []
    for i in range(days - 1, -1, -1):
        d = (end - timedelta(days=i)).strftime("%Y-%m-%d")
        raw = read_json(HERE / "raw" / f"{d}.json")
        o = read_json(HERE / "output" / f"{d}.json")
        items = (o or {}).get("items", [])
        rows.append({"date": d, "state": day_state(o), "collected": raw is not None,
                     "active_min": active_minutes(raw), "items": len(items),
                     "work_min": (hours_info(d) or {}).get("minutes", 0),
                     "completed": sum(1 for it in items if it.get("status", "").lower().startswith("complete")),
                     "commits": sum(1 for e in (raw or {}).get("events", []) if e["src"] == "git"),
                     "domains": sorted({it["module"] for it in items if not it["module"].startswith("[")})})
    dom = Counter(m for r in rows for m in r["domains"])
    return {"days": rows, "domain_days": dom.most_common()}


_collect_lock = threading.Lock()


def _collect_today(d):
    if _collect_lock.acquire(blocking=False):
        try:
            subprocess.run([sys.executable, str(HERE / "collect.py"), "--date", d], capture_output=True, timeout=120, cwd=HERE)
        except Exception:
            pass
        finally:
            _collect_lock.release()


def work_hours(d):
    """My working hours for a day → (start, end, start_source).
    start: PC turned on that day (sessions/ log or boot time), else my first activity.
    end:   today → now while I'm still active (e.g. at shutdown), otherwise my last activity;
           earlier days → when I shut the PC down, else my last activity."""
    now = datetime.now()
    blocks = (read_json(HERE / "raw" / f"{d}.json") or {}).get("active_blocks") or []
    ses = read_json(HERE / "sessions" / f"{d}.json") or {}
    at = lambda hm: datetime.strptime(f"{d} {hm}", "%Y-%m-%d %H:%M")
    start, src = None, None
    boot = boot_time()
    ons = [on for on, _ in boots() if on.strftime("%Y-%m-%d") == d]
    offs = [off for _, off in boots() if off and off.strftime("%Y-%m-%d") == d]
    if ses.get("pc_on"):
        start, src = datetime.fromisoformat(ses["pc_on"]), "pc_on"
    elif ons:
        start, src = min(ons), "pc_on"
    elif boot and boot.strftime("%Y-%m-%d") == d:
        start, src = boot, "pc_on"
    elif blocks:
        start, src = at(blocks[0][:5]), "first_activity"
    last = at(blocks[-1][-5:]) if blocks else None
    timed = [e for e in manual_entries(d) if e.get("start")]
    m_end = None
    if timed:                                   # meetings / visits away from the PC count as work time
        m_start = min(at(e["start"]) for e in timed)
        m_end = max(at(e.get("end") or e["start"]) for e in timed)
        if start is None or m_start < start:
            start, src = m_start, "manual"
        if d == now.strftime("%Y-%m-%d"):
            m_end = min(m_end, now)
        last = max(last, m_end) if last else m_end
    if d == now.strftime("%Y-%m-%d"):
        end = now if (last is None or now - last <= timedelta(minutes=30)) else last
    else:
        end = (datetime.fromisoformat(ses["pc_off"]) if ses.get("pc_off")
               else max(offs) if offs else last)
        if end and m_end and m_end > end:       # only my own entries (a visit after I switched the PC off)
            end = m_end
    if start and end and end < start:
        end = start
    return start, end, src


def hours_text(d):
    """Column C text: total / start / end / extra (beyond automation.workday_hours)."""
    start, end, _ = work_hours(d)
    if not start or not end:
        return ""
    mins = int((end - start).total_seconds() // 60)
    extra = max(0, mins - int(float(cfg().get("automation", {}).get("workday_hours", 8)) * 60))
    f = lambda m: f"{m // 60}h {m % 60:02d}m"
    t = lambda x: x.strftime("%I:%M %p").lstrip("0")
    return f"Total work hours: {f(mins)}\nStart: {t(start)}\nEnd: {t(end)}\nExtra: {f(extra)}"


def hours_info(d):
    """Working hours for the dashboard: start / end / total / extra (minutes), live = still running today."""
    start, end, src = work_hours(d)
    if not start or not end:
        return None
    mins = int((end - start).total_seconds() // 60)
    limit = int(float(cfg().get("automation", {}).get("workday_hours", 8)) * 60)
    live = d == datetime.now().strftime("%Y-%m-%d") and (datetime.now() - end).total_seconds() < 120
    return {"start": start.isoformat(timespec="seconds"), "end": end.isoformat(timespec="seconds"), "source": src,
            "minutes": mins, "extra": max(0, mins - limit), "limit": limit, "live": live}


def workday():
    """When my working day started (dashboard countdown)."""
    a = cfg().get("automation", {})
    d = datetime.now().strftime("%Y-%m-%d")
    info = {"hours": a.get("workday_hours", 8), "email_after": a.get("email_after", "16:00"), "start": None, "source": None}
    rp = HERE / "raw" / f"{d}.json"
    if not rp.exists():
        _collect_today(d)                                   # quick; gives today's first activity
    elif time.time() - rp.stat().st_mtime > 600:
        threading.Thread(target=_collect_today, args=(d,), daemon=True).start()
    start, _, src = work_hours(d)
    if start:
        info.update(start=start.isoformat(timespec="seconds"), source=src)
    return info


# ---------------------------------------------------------------- profile photo
AVATAR_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}


def avatar_file():
    for ext in ("png", "jpg", "webp"):
        f = HERE / "profile" / f"avatar.{ext}"
        if f.exists():
            return f
    return None


def status():
    c = cfg()
    sys.path.insert(0, str(HERE))
    from push import hook
    from summarize import claude_bin
    from mail import settings as mail_settings
    return {"owner": c["owner"], "automation": c.get("automation", {}), "sheet_url": c["sheet"].get("url", ""),
            "sheet_name": c["sheet"].get("name") or "My Work Log", "groups": c.get("groups", []),
            "domain_labels": [re.split(r"\s*\(", x)[0] for x in c.get("domain_labels", [])],
            "schedule_installed": safety_nets_status(), "workday": workday(), "shutdown_hook": shutdown_hook_status(),
            "project_dir": str(HERE), "platform": platform_name(), "install_command": install_command(),
            "avatar": int(avatar_file().stat().st_mtime) if avatar_file() else 0,
            "mail": mail_settings(), "script_version": (read_json(HERE / "sheet_webhook.json") or {}).get("script_version"),
            "claude_available": bool(claude_bin()), "sheet_sync": bool(hook()),
            "last_run": read_json(HERE / "last_run.json")}


def apps_script_code():
    tok = (read_json(HERE / "sheet_webhook.json") or {}).get("token", "")
    return (HERE / "apps_script" / "Code.template.gs").read_text(encoding="utf-8").replace("__TOKEN__", tok)


def auto_push(d):
    """Keep the sheet the same as the dashboard: push after an AI rewrite or my own edit."""
    sys.path.insert(0, str(HERE))
    from push import hook
    if not hook() or not cfg().get("automation", {}).get("auto_push", True):
        return {"ok": False, "status": "sheet_sync_off"}
    ok, log = run_py("push.py", "--date", d, timeout=120)
    try:
        return json.loads(log.splitlines()[-1])
    except Exception:
        return {"ok": False, "status": "push_failed", "error": log[-300:]}


def run_py(*args, timeout=900):
    kw = {"creationflags": 0x08000000} if IS_WIN else {}        # no console window flashes on Windows
    r = subprocess.run([sys.executable, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, cwd=HERE, **kw)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


# ---------------------------------------------------------------- http
# ---------------------------------------------------------------- open on my phone (other devices)
REMOTE = HERE / "remote.json"
_fails = defaultdict(list)
LOCAL_ONLY = {"/api/apps-script", "/api/webhook", "/api/remote", "/api/mail-settings", "/api/view-link"}


def view_url():
    """Read-only phone page served by the sheet's script (works when this PC is off)."""
    h = read_json(HERE / "sheet_webhook.json") or {}
    if h.get("url") and h.get("view_key") and int(h.get("script_version") or 0) >= 4:
        return f"{h['url']}?k={h['view_key']}"
    return ""


def remote_cfg():
    r = read_json(REMOTE) or {}
    if not r.get("secret"):
        r["secret"] = secrets.token_hex(32)
        save_remote(r)
    return r


def save_remote(r):
    REMOTE.write_text(json.dumps(r, indent=2), encoding="utf-8")
    try:
        os.chmod(REMOTE, 0o600)
    except OSError:
        pass


def hash_pw(pw, salt):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()


def _sig(r, exp):
    # the password hash is part of the signature: changing the password signs everybody out
    return hmac.new(bytes.fromhex(r["secret"]), f"{exp}.{r.get('hash', '')[:16]}".encode(), "sha256").hexdigest()


def new_session(r, days=30):
    exp = int(time.time()) + days * 86400
    return f"{exp}.{_sig(r, exp)}"


def session_ok(r, tok):
    try:
        exp, sig = tok.split(".", 1)
        return int(exp) > time.time() and hmac.compare_digest(sig, _sig(r, int(exp)))
    except Exception:
        return False


def lan_ips():
    ips = []
    try:                                     # the address this PC uses on the local network (no packet is sent)
        u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        u.connect(("10.255.255.255", 1))
        ips.append(u.getsockname()[0])
        u.close()
    except OSError:
        pass
    try:                                     # Tailscale (reachable from anywhere on my own tailnet)
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.split()
        ips += [ip for ip in out if ip.startswith("100.")]
    except Exception:
        pass
    return [ip for ip in dict.fromkeys(ips) if not ip.startswith("127.")]


def firewall_hint(ip):
    if IS_WIN:
        return "If Windows asks, allow Python on private networks."
    try:
        active = subprocess.run(["systemctl", "is-active", "ufw"], capture_output=True, text=True, timeout=5).stdout.strip() == "active"
    except Exception:
        active = False
    if active and ip:
        net = ".".join(ip.split(".")[:3]) + ".0/24"
        return f"sudo ufw allow from {net} to any port {PORT} proto tcp"
    return ""


def remote_status(local):
    r = remote_cfg()
    ips = lan_ips()
    return {"enabled": bool(r.get("enabled")), "has_password": bool(r.get("hash")), "viewer_local": local,
            "urls": [f"http://{ip}:{PORT}" for ip in ips] if r.get("enabled") else [],
            "listening_all": BIND_HOST == "0.0.0.0", "firewall": firewall_hint(ips[0] if ips else "") if local else ""}


def restart_server():
    """Re-start so the new listening address (this PC only / my network) takes effect."""
    time.sleep(0.8)
    me = [sys.executable, str(HERE / "server.py")]
    if IS_WIN:
        subprocess.Popen(me, cwd=HERE, creationflags=0x00000008 | 0x08000000)   # detached, no window
        os._exit(0)
    os.execv(sys.executable, me)


LOGIN_PAGE = (HERE / "ui" / "login.html")


# ---------------------------------------------------------------- PC on/off → the phone link (sheet script v5+)
_pub_ip = {"t": 0, "v": ""}


def public_ip():
    """This network's public address — lets the phone page notice "same Wi-Fi" and open the live dashboard."""
    if time.time() - _pub_ip["t"] > 1800:
        try:
            import urllib.request
            v = urllib.request.urlopen("https://api.ipify.org", timeout=6).read().decode().strip()
            _pub_ip["v"] = v if re.fullmatch(r"[\d.:a-fA-F]{3,45}", v) else ""
        except Exception:
            pass
        _pub_ip["t"] = time.time()
    return _pub_ip["v"]


def send_heartbeat(online=True):
    """Tell the sheet script whether this PC is on, and the live-dashboard link. Only for script v5+
    (older scripts would treat an unknown action as a sheet write)."""
    h = read_json(HERE / "sheet_webhook.json") or {}
    if not (h.get("url") and h.get("view_key") and int(h.get("script_version") or 0) >= 5):
        return None
    sys.path.insert(0, str(HERE))
    from push import call
    r = remote_cfg()
    urls = [f"http://{ip}:{PORT}" for ip in lan_ips()] if online and r.get("enabled") and r.get("hash") else []
    return call({"action": "heartbeat", "online": bool(online), "urls": urls, "ip": public_ip() if urls else ""}, timeout=20)


def heartbeat_loop():
    time.sleep(5)
    n = 0
    while True:
        try:
            if n % 30 == 0:                      # re-check the script version every hour
                sys.path.insert(0, str(HERE))
                from push import call, hook
                if hook():
                    v = int(call({"action": "ping"}).get("version") or 1)
                    h = read_json(HERE / "sheet_webhook.json") or {}
                    if h.get("script_version") != v:
                        h["script_version"] = v
                        (HERE / "sheet_webhook.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
            send_heartbeat(True)
        except Exception:
            pass
        n += 1
        time.sleep(120)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json", headers=None):
        b = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    # -- who is asking?
    def is_local(self):
        """This PC itself (not a phone, and not something forwarded through a tunnel)."""
        ip = self.client_address[0]
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]")
        forwarded = any(self.headers.get(h) for h in ("X-Forwarded-For", "CF-Connecting-IP", "X-Real-IP", "Forwarded"))
        return ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1") and host in ("127.0.0.1", "localhost") and not forwarded

    def cookie(self, name):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == name:
                return v
        return ""

    def authed(self):
        if self.is_local():
            return True
        r = remote_cfg()
        return bool(r.get("enabled") and r.get("hash") and session_ok(r, self.cookie("wl_session")))

    def gate(self, path):
        """True = carry on. Otherwise the reply (login page / 401 / 403) was already sent."""
        if self.authed():
            if path in LOCAL_ONLY and not self.is_local():
                self.send(403, {"error": "This can only be changed on the PC itself"})
                return False
            return True
        if path in ("/", "/index.html"):
            self.send(302, b"", "text/plain", {"Location": "/login"})
        else:
            self.send(401, {"error": "Sign in first"})
        return False

    def date_ok(self, d):
        if not d or not DATE_RE.match(d):
            self.send(400, {"error": "bad date"})
            return None
        return d

    def do_GET(self):
        path, _, qs = self.path.partition("?")
        q = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
        if path == "/login":
            if self.authed():
                return self.send(302, b"", "text/plain", {"Location": "/"})
            return self.send(200, LOGIN_PAGE.read_bytes(), "text/html")
        if not self.gate(path):
            return
        if path in ("/", "/index.html"):
            return self.send(200, (HERE / "ui" / "index.html").read_bytes(), "text/html")
        if path == "/api/dates":
            return self.send(200, list_dates())
        if path == "/api/status":
            local = self.is_local()
            return self.send(200, {**status(), "remote": remote_status(local), "view_url": view_url() if local else ""})
        if path == "/api/overview":
            d = self.date_ok(q.get("date"))
            return d and self.send(200, overview(d))
        if path == "/api/day":
            d = self.date_ok(q.get("date"))
            if not d:
                return
            dg = HERE / "digest" / f"{d}.md"
            return self.send(200, {"date": d, "formatted_date": formatted(d),
                                   "raw": read_json(HERE / "raw" / f"{d}.json"),
                                   "summary": read_json(HERE / "output" / f"{d}.json"),
                                   "digest": dg.read_text(encoding="utf-8") if dg.exists() else None,
                                   "hours": hours_info(d), "manual": manual_entries(d)})
        if path == "/avatar":
            f = avatar_file()
            if not f:
                return self.send(404, {"error": "no photo"})
            ctype = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}[f.suffix[1:]]
            return self.send(200, f.read_bytes(), ctype)
        if path == "/api/apps-script":
            return self.send(200, {"code": apps_script_code()})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        origin = self.headers.get("Origin", "")
        if origin and origin not in ORIGINS and urlparse(origin).netloc != self.headers.get("Host", ""):   # CSRF guard
            return self.send(403, {"error": "forbidden origin"})
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0) or 0), 8_000_000)) or b"{}")
        except Exception:
            return self.send(400, {"error": "bad json"})

        if self.path == "/api/login":
            r, ip = remote_cfg(), self.client_address[0]
            _fails[ip] = [t for t in _fails[ip] if t > time.time() - 300]
            if len(_fails[ip]) >= 5:
                return self.send(429, {"error": "Too many tries — wait 5 minutes"})
            if not (r.get("enabled") and r.get("hash")):
                return self.send(403, {"error": "Access from other devices is turned off on the PC"})
            if not hmac.compare_digest(hash_pw(str(body.get("password", "")), r["salt"]), r["hash"]):
                _fails[ip].append(time.time())
                return self.send(401, {"error": "Wrong password"})
            secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
            return self.send(200, {"ok": True}, headers={
                "Set-Cookie": f"wl_session={new_session(r)}; Path=/; Max-Age=2592000; HttpOnly; SameSite=Lax{secure}"})
        if self.path == "/api/logout":
            return self.send(200, {"ok": True}, headers={"Set-Cookie": "wl_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})
        if not self.gate(self.path):
            return

        if self.path == "/api/view-link":                   # create / replace the phone-view link (this PC only)
            sys.path.insert(0, str(HERE))
            from push import call, hook
            if not hook():
                return self.send(400, {"error": "Connect the Google Sheet first"})
            try:
                ver = int(call({"action": "ping"}).get("version") or 1)
            except Exception as e:
                return self.send(200, {"ok": False, "error": f"Could not reach the sheet script: {e}"})
            h = read_json(HERE / "sheet_webhook.json") or {}
            h["script_version"] = ver
            if ver < 4:
                (HERE / "sheet_webhook.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
                return self.send(200, {"ok": False, "error": "update_script", "version": ver})
            key = h.get("view_key") if h.get("view_key") and not body.get("rotate") else secrets.token_urlsafe(24)
            c = cfg()
            r = call({"action": "set_view_key", "key": key, "name": c["owner"].get("name", ""),
                      "role": c["owner"].get("role", ""), "workday_hours": c["automation"].get("workday_hours", 8)})
            if not r.get("ok"):
                return self.send(200, {"ok": False, "error": r.get("error") or "The sheet script refused the link"})
            h["view_key"] = key
            (HERE / "sheet_webhook.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
            try:
                os.chmod(HERE / "sheet_webhook.json", 0o600)
            except OSError:
                pass
            threading.Thread(target=send_heartbeat, daemon=True).start()     # tell the page right away
            return self.send(200, {"ok": True, "url": view_url()})

        if self.path == "/api/remote":                      # turn "open on my phone" on/off (this PC only)
            r = remote_cfg()
            pw = str(body.get("password", ""))
            if pw:
                if len(pw) < 6:
                    return self.send(400, {"error": "Use at least 6 characters"})
                r["salt"] = secrets.token_hex(16)
                r["hash"] = hash_pw(pw, r["salt"])
            want = bool(body.get("enabled", r.get("enabled")))
            if want and not r.get("hash"):
                return self.send(400, {"error": "Set a password first"})
            changed = want != bool(r.get("enabled"))
            r["enabled"] = want
            save_remote(r)
            if changed or (want and BIND_HOST != "0.0.0.0"):
                threading.Thread(target=restart_server, daemon=True).start()
            return self.send(200, {"ok": True, "restarting": changed, "remote": remote_status(True)})

        if self.path == "/api/avatar":
            data = str(body.get("data", ""))
            if body.get("remove"):
                for ext in ("png", "jpg", "webp"):
                    (HERE / "profile" / f"avatar.{ext}").unlink(missing_ok=True)
                return self.send(200, {"ok": True, "avatar": 0})
            m = re.match(r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)$", data)
            if not m:
                return self.send(400, {"error": "Choose a PNG, JPG or WebP picture"})
            raw = base64.b64decode(m.group(2))
            if len(raw) > 3_000_000:
                return self.send(400, {"error": "Picture is too large (max 3 MB)"})
            (HERE / "profile").mkdir(exist_ok=True)
            for ext in ("png", "jpg", "webp"):
                (HERE / "profile" / f"avatar.{ext}").unlink(missing_ok=True)
            f = HERE / "profile" / f"avatar.{AVATAR_TYPES[m.group(1)]}"
            f.write_bytes(raw)
            return self.send(200, {"ok": True, "avatar": int(f.stat().st_mtime)})
        if self.path == "/api/mail-settings":
            to = body.get("to", [])
            to = [t.strip() for t in (to.split(",") if isinstance(to, str) else to) if isinstance(t, str) and t.strip()]
            bad = [t for t in to if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", t)]
            if bad:
                return self.send(400, {"error": "Not an email address: " + ", ".join(bad)})
            sys.path.insert(0, str(HERE))
            from mail import save_settings
            return self.send(200, {"ok": True, "mail": save_settings(body.get("enabled", True), to)})
        if self.path == "/api/script-version":
            ok, log = run_py("push.py", "--ping", timeout=60)
            try:
                res = json.loads(log.splitlines()[-1])
            except Exception:
                res = {}
            ver = res.get("version", 1 if res.get("ok") else None)
            if ver:
                h = read_json(HERE / "sheet_webhook.json") or {}
                h["script_version"] = ver
                start_backfill = ver >= 3 and not h.get("hours_backfilled")
                if start_backfill:
                    h["hours_backfilled"] = True       # fill column C once for days already in the sheet
                (HERE / "sheet_webhook.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
                if start_backfill:
                    threading.Thread(target=run_py, args=("push.py", "--backfill-hours"), kwargs={"timeout": 600},
                                     daemon=True).start()
            return self.send(200, {"ok": bool(res.get("ok")), "version": ver})

        if self.path == "/api/webhook":
            url = str(body.get("url", "")).strip()
            if not url.startswith("https://script.google.com/"):
                return self.send(400, {"error": "Paste the Web app URL that starts with https://script.google.com/"})
            h = read_json(HERE / "sheet_webhook.json") or {}
            h["url"] = url
            (HERE / "sheet_webhook.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
            ok, log = run_py("push.py", "--ping", timeout=60)
            h["script_version"] = 2 if '"version": 2' in log else 1
            (HERE / "sheet_webhook.json").write_text(json.dumps(h, indent=2), encoding="utf-8")
            return self.send(200, {"ok": ok and '"ok": true' in log, "log": log[-500:]})

        d = self.date_ok(body.get("date"))
        if not d:
            return
        if self.path == "/api/collect":
            ok, log = run_py("collect.py", "--date", d)
            return self.send(200 if ok else 500, {"ok": ok, "log": log[-2000:]})
        if self.path == "/api/ai-summary":
            ok, log = run_py("summarize.py", "--date", d, "--save")
            if ok:
                merge_manual(d)
            pushed = auto_push(d) if ok else None
            return self.send(200 if ok else 500, {"ok": ok, "log": log[-2000:], "push": pushed,
                                                  "summary": read_json(HERE / "output" / f"{d}.json")})
        if self.path == "/api/run-day":
            ok, log = run_py("run_day.py", "--date", d, *(["--resummarize"] if body.get("resummarize") else []))
            return self.send(200 if ok else 500, {"ok": ok, "log": log[-2000:]})
        if self.path == "/api/push":
            ok, log = run_py("push.py", "--date", d, *(["--force"] if body.get("force") else []), timeout=120)
            res = {}
            try:
                res = json.loads(log.splitlines()[-1])
            except Exception:
                pass
            return self.send(200, {"ok": ok and res.get("ok", False), "result": res, "log": log[-800:]})
        if self.path == "/api/email":
            ok, log = run_py("mail.py", "--date", d, *(["--test"] if body.get("test") else []), timeout=120)
            try:
                res = json.loads(log.splitlines()[-1])
            except Exception:
                res = {"ok": False, "error": log[-300:]}
            return self.send(200, res)
        if self.path == "/api/manual/add":
            e = body.get("entry") or {}
            kind = str(e.get("kind", "Work")).strip()
            text = str(e.get("text", "")).strip()
            start, end = str(e.get("start", "")).strip(), str(e.get("end", "")).strip()
            if kind not in KINDS or not text:
                return self.send(400, {"error": "Type and what you did are required"})
            if (start and not TIME_RE.match(start)) or (end and not TIME_RE.match(end)) or (end and not start):
                return self.send(400, {"error": "Times must look like 10:00, and a To time needs a From time"})
            if start and end and end <= start:
                return self.send(400, {"error": "To must be after From"})
            entries = manual_entries(d)
            entries.append({"id": uuid.uuid4().hex[:10], "kind": kind, "module": str(e.get("module", "")).strip()[:60],
                            "text": text[:1000], "start": start, "end": end,
                            "status": "In Progress" if str(e.get("status")).lower().startswith("in") else "Completed"})
            save_manual(d, entries)
            merge_manual(d)
            return self.send(200, {"ok": True, "push": auto_push(d)})
        if self.path == "/api/manual/delete":
            entries = [x for x in manual_entries(d) if x.get("id") != body.get("id")]
            save_manual(d, entries)
            merge_manual(d)
            return self.send(200, {"ok": True, "push": auto_push(d)})
        if self.path == "/api/save":
            items = body.get("items")
            if not isinstance(items, list):
                return self.send(400, {"error": "items required"})
            clean = [{k: str(it.get(k, "")).strip() for k in ("module", "action", "details", "status")}
                     for it in items if isinstance(it, dict) and str(it.get("details", "")).strip()
                     and not it.get("manual")]
            prev = read_json(HERE / "output" / f"{d}.json") or {}
            out = build(d, clean, bool(body.get("approved")))
            out["source"] = "manual"
            for k in ("pushed_text", "pushed_row", "pushed_to_sheet", "pushed_at"):
                if k in prev:
                    out[k] = prev[k]
            (HERE / "output").mkdir(exist_ok=True)
            (HERE / "output" / f"{d}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
            merge_manual(d)
            pushed = auto_push(d)
            return self.send(200, {**(read_json(HERE / "output" / f"{d}.json") or out), "push": pushed})
        self.send(404, {"error": "not found"})


BIND_HOST = "0.0.0.0" if (read_json(REMOTE) or {}).get("enabled") else "127.0.0.1"

if __name__ == "__main__":
    for attempt in range(40):                 # after a restart the old process may still hold the port briefly
        try:
            srv = ThreadingHTTPServer((BIND_HOST, PORT), H)
            break
        except OSError:
            time.sleep(0.5)
    else:
        sys.exit(f"port {PORT} is busy")
    print(f"My Work Log → http://127.0.0.1:{PORT}" + ("  (also on my network)" if BIND_HOST == "0.0.0.0" else ""))
    if not os.environ.get("WORKLOG_PORT"):          # test copies on another port never report to the phone link
        threading.Thread(target=heartbeat_loop, daemon=True).start()
    srv.serve_forever()
