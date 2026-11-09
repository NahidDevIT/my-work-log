"""My Work Log — shared helpers: settings, time zone and Linux / Windows differences."""
import json, os, platform, re, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"
if IS_WIN:                                         # UTF-8 everywhere (summaries contain —, →, non-Latin text)
    os.environ.setdefault("PYTHONUTF8", "1")
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
IS_MAC = sys.platform == "darwin"
HOME = Path.home()

# Defaults for every setting, so an older or minimal config.yaml keeps working.
DEFAULTS = {
    "owner": {"name": "Me", "short_name": "", "role": "Engineer", "organization": "", "email": ""},
    "timezone_offset_hours": "auto",
    "idle_gap_minutes": 30,
    "my_git_names": [],
    "only_my_work": True,
    "automation": {"trigger": "shutdown", "email_after": "16:00", "workday_hours": 8, "fallback_at": "23:50",
                   "catchup_since": "2000-01-01", "work_days": "Sun–Thu", "ai_summary": True, "auto_push": True,
                   "ai_model": "sonnet"},
    "sheet": {"name": "My Work Log", "id": "", "url": ""},
    "projects_root": "~/Projects",
    "modules": {},
    "domain_labels": ["Development", "Testing & QA", "Documentation", "Meetings", "Research", "Workstation"],
    "groups": [
        {"name": "Development", "icon": "code", "match": "dev|code|feature|api|backend|frontend|deploy|release"},
        {"name": "Testing & QA", "icon": "shield", "match": "sqa|test|\\bqa\\b|playwright|selenium|cypress"},
        {"name": "Meetings", "icon": "users", "match": "meeting|session|visit|training|call"},
        {"name": "Docs & Other", "icon": "file", "match": ""},
    ],
    "vocabulary": [],
    "people": [],
    "file_scan_dirs": ["~/Desktop", "~/Documents", "~/Downloads"],
    "file_skip_dirs": ["node_modules", ".git", "build", "dist", "target", ".angular", ".next", "venv", ".venv",
                       "__pycache__", ".cache", "coverage", ".gradle", "bin", "obj", "vendor"],
    "browser": {"profiles": "auto", "block_domains": [], "drop_search_engines": True},
    "ignore_dirs": [],
}


def _merge(base, over):
    if not isinstance(base, dict) or not isinstance(over, dict):
        return over if over is not None else base
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(base.get(k), v) if isinstance(base.get(k), dict) else v
    return out


def cfg():
    p = HERE / "config.yaml"
    user = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    c = _merge(DEFAULTS, user or {})
    c["owner"]["short_name"] = c["owner"].get("short_name") or (c["owner"]["name"].split() or ["Me"])[0]
    c["ignore_dirs"] = list(c.get("ignore_dirs") or []) + [HERE.name]   # never log the work log itself
    return c


def tz():
    off = cfg().get("timezone_offset_hours", "auto")
    if off in (None, "auto", ""):
        return datetime.now().astimezone().tzinfo
    return timezone(timedelta(hours=float(off)))


def now():
    return datetime.now(tz())


def read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------- PC on / off
def boot_time():
    """When this PC was last switched on (naive local time)."""
    try:
        if IS_WIN:
            import ctypes
            ms = ctypes.windll.kernel32.GetTickCount64()
            return datetime.now() - timedelta(milliseconds=ms)
        if IS_MAC:
            out = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True).stdout
            return datetime.fromtimestamp(int(re.search(r"sec = (\d+)", out).group(1)))
        return datetime.fromtimestamp(next(int(l.split()[1]) for l in open("/proc/stat") if l.startswith("btime")))
    except Exception:
        return None


_boots = {"t": 0, "v": []}


def boots():
    """Past PC on/off times: [(on, off_or_None_for_current_boot)] — journalctl on Linux, event log on Windows."""
    if time.time() - _boots["t"] < 600:
        return _boots["v"]
    v = []
    try:
        if IS_WIN:
            ps = ("Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-Kernel-General';"
                  "Id=12,13} -MaxEvents 400 | Sort-Object TimeCreated | "
                  "ForEach-Object { '{0}|{1}' -f $_.Id, $_.TimeCreated.ToString('s') }")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True,
                                 timeout=20, creationflags=0x08000000).stdout
            on = None
            for line in out.splitlines():
                i, _, t = line.strip().partition("|")
                if not t:
                    continue
                t = datetime.fromisoformat(t)
                if i == "12":
                    on = t
                elif i == "13" and on:
                    v.append((on, t))
                    on = None
            if on:
                v.append((on, None))
        elif not IS_MAC:
            out = subprocess.run(["journalctl", "--list-boots", "--no-pager", "-o", "json"],
                                 capture_output=True, text=True, timeout=10).stdout
            v = [(datetime.fromtimestamp(b["first_entry"] / 1e6),
                  None if b["index"] == 0 else datetime.fromtimestamp(b["last_entry"] / 1e6))
                 for b in json.loads(out or "[]")]
    except Exception:
        v = []
    _boots.update(t=time.time(), v=v)
    return v


# ---------------------------------------------------------------- automation status
def _run(*a):
    try:
        kw = {"creationflags": 0x08000000} if IS_WIN else {}
        return subprocess.run(list(a), capture_output=True, text=True, timeout=15, **kw)
    except Exception:
        return None


def shutdown_hook_status():
    """Is "save my day when the PC shuts down" installed?"""
    if IS_WIN:
        ini = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/GroupPolicy/User/Scripts/scripts.ini"
        try:
            ok = "worklog_logoff.cmd" in ini.read_bytes().decode("utf-16", "ignore").lower()
        except Exception:
            ok = False
        return {"enabled": ok, "active": ok}
    if IS_MAC:
        return {"enabled": False, "active": False}
    try:                                           # the service must point at THIS folder
        mine = str(HERE / "session.py") in Path("/etc/systemd/system/my-work-log-shutdown.service").read_text()
    except OSError:
        mine = False
    q = lambda *a: (_run("systemctl", *a, "my-work-log-shutdown.service") or type("r", (), {"stdout": ""})).stdout.strip()
    return {"enabled": mine and q("is-enabled") == "enabled", "active": mine and q("is-active") == "active"}


def safety_nets_status():
    """Start-up catch-up + late-night fallback installed?"""
    if IS_WIN:
        r = _run("schtasks", "/Query", "/TN", "MyWorkLog Fallback")
        return bool(r and r.returncode == 0)
    r = _run("crontab", "-l")
    lines = [l for l in (r.stdout if r else "").splitlines() if str(HERE / "session.py") in l]
    return all(any(re.search(r"session\.py\W+" + m, l) for l in lines) for m in ("boot", "fallback"))


def install_command():
    if IS_WIN:
        return f'"{HERE / "install.bat"}"'
    return f'bash "{HERE / "install.sh"}"'


def platform_name():
    return "windows" if IS_WIN else "mac" if IS_MAC else "linux"
