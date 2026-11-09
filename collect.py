#!/usr/bin/env python3
"""My Work Log — Step 1-3: collect, filter and group activity for one day.

Usage:  python3 collect.py --date 2026-11-09
Output: raw/<date>.json      full filtered timeline
        digest/<date>.md     compact per-module digest used to write the summary
Read-only: databases are copied to a temp dir before reading. Works on Linux, Windows and macOS;
sources that do not exist on this PC are simply skipped.
"""
import argparse, json, os, re, shutil, sqlite3, subprocess, sys, tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, unquote

from common import HERE, HOME, IS_MAC, IS_WIN, cfg, tz

CFG = cfg()
TZ = tz()
PROJ_ROOT = Path(os.path.expanduser(CFG["projects_root"]))
APPDATA = Path(os.environ.get("APPDATA", HOME / "AppData/Roaming"))
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", HOME / "AppData/Local"))
TMP = Path(tempfile.mkdtemp(prefix="worklog-"))

NOISE_CMDS = re.compile(r"^\s*(ls|ll|cd|pwd|clear|exit|history|cat|less|echo|whoami|date)\b")


def day_window(d):
    start = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=TZ)
    return start, start + timedelta(days=1)


def ms(dt):
    return int(dt.timestamp() * 1000)


def local(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, TZ).strftime("%H:%M")


def module_for(text):
    """Map a path/URL/text to a module label via config."""
    t = text or ""
    if any(i in t for i in CFG["ignore_dirs"]):
        return None
    # Longest key first so a specific folder name beats a shorter keyword
    for key in sorted(CFG["modules"], key=len, reverse=True):
        # hyphen, slash, space count as boundaries (Claude Code folders look like '-home-me-Projects-myapp')
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(key)}(?![A-Za-z0-9])", t, re.I):
            return CFG["modules"][key]
    return "[Unspecified]"


def short_path(path):
    """Path relative to the projects folder (VS Code edits)."""
    p = str(path)
    root = str(PROJ_ROOT).rstrip("/\\")
    return p[len(root):].lstrip("/\\") if p.startswith(root + os.sep) or p.startswith(root + "/") else home_path(p)


def home_path(path):
    """~/… form for folders under my home folder."""
    p = str(path)
    h = str(HOME)
    return "~" + p[len(h):].replace("\\", "/") if p.startswith(h) else p


def file_from_uri(uri):
    path = unquote(uri).replace("file://", "")
    if IS_WIN and re.match(r"^/[A-Za-z]:", path):
        path = path[1:]
    return path


def copy_db(p):
    dst = TMP / (str(abs(hash(str(p)))) + ".db")
    shutil.copy(p, dst)
    for ext in ("-wal", "-shm"):
        if Path(str(p) + ext).exists():
            shutil.copy(str(p) + ext, str(dst) + ext)
    return sqlite3.connect(dst)


# ---------------------------------------------------------------- sources
def vscode(start, end):
    out = []
    if IS_WIN:
        roots = [APPDATA / "Code/User/History", APPDATA / "Code - Insiders/User/History"]
    elif IS_MAC:
        roots = [HOME / "Library/Application Support/Code/User/History"]
    else:
        roots = [HOME / ".config/Code/User/History", HOME / ".config/Code - OSS/User/History"]
    for d in (e for r in roots for e in r.glob("*/entries.json")):
        try:
            j = json.loads(d.read_text(encoding="utf-8"))
        except Exception:
            continue
        res = unquote(j.get("resource", ""))
        if res.startswith("vscode-userdata:"):
            continue
        stamps = [e["timestamp"] for e in j.get("entries", []) if ms(start) <= e["timestamp"] < ms(end)]
        if not stamps:
            continue
        path = file_from_uri(res)
        mod = module_for(path)
        if mod is None:
            continue
        rel = short_path(path)
        out.append({"t": min(stamps), "t_end": max(stamps), "src": "vscode", "module": mod,
                    "text": f"edited {rel} ({len(stamps)} saves)"})
    return out


def git(start, end):
    out = []
    for g in PROJ_ROOT.glob("**/.git"):
        if len(g.relative_to(PROJ_ROOT).parts) > 3:
            continue
        repo = g.parent
        try:
            log = subprocess.run(
                ["git", "-C", str(repo), "log", "--all", "--no-merges",
                 # --since/--until filter on commit date; widen and post-filter on author date
                 f"--since={(start - timedelta(days=7)).isoformat()}", f"--until={(end + timedelta(days=7)).isoformat()}",
                 "--format=%at|%an|%s", "--shortstat"],
                capture_output=True, text=True, timeout=30).stdout
        except Exception:
            continue
        cur = None
        for line in log.splitlines():
            if "|" in line and line.split("|")[0].isdigit():
                ts, an, subj = line.split("|", 2)
                if not (ms(start) <= int(ts) * 1000 < ms(end)):
                    cur = None
                    continue
                mine = an in CFG["my_git_names"]
                if not mine and CFG.get("only_my_work"):
                    cur = None
                    continue
                cur = {"t": int(ts) * 1000, "src": "git", "module": module_for(str(repo)),
                       "text": f"{'MY commit' if mine else 'commit by ' + an}: {subj}", "mine": mine}
                out.append(cur)
            elif line.strip() and cur:
                cur["text"] += f" [{line.strip()}]"
    return out


def git_actions(start, end):
    """My local git actions from the reflog: checkout, pull, merge, rebase, reset, clone."""
    out = []
    for g in PROJ_ROOT.glob("**/.git"):
        if len(g.relative_to(PROJ_ROOT).parts) > 3:
            continue
        repo = g.parent
        try:
            log = subprocess.run(["git", "-C", str(repo), "log", "-g", "--all", "--date=unix", "--format=%gd|%gs"],
                                 capture_output=True, text=True, timeout=30).stdout
        except Exception:
            continue
        seen = set()
        for line in log.splitlines():
            m = re.match(r".*@\{(\d+)\}\|(.*)", line)
            if not m:
                continue
            t, action = int(m.group(1)) * 1000, m.group(2)
            if not (ms(start) <= t < ms(end)) or action.startswith(("commit", "update by push", "fetch")):
                continue
            # automated detached-HEAD checkouts (build scripts) are noise; keep switches to named branches
            if action.startswith("checkout:") and re.search(r"to [0-9a-f]{7,40}$", action):
                continue
            if re.search(r"moving from (\S+) to \1$", action):
                continue
            key = (t // 60000, action)
            if key in seen:
                continue
            seen.add(key)
            out.append({"t": t, "src": "git-action", "module": module_for(str(repo)),
                        "text": f"{repo.name}: {action[:160]}"})
    return out


def terminal(start, end):
    """Shell history with timestamps: bash (needs HISTTIMEFORMAT in ~/.bashrc) and zsh (EXTENDED_HISTORY).
    Windows PowerShell keeps no timestamps, so it is not used."""
    out, last = [], None
    lines = []
    p = HOME / ".bash_history"
    if p.exists():
        t = None
        for line in p.read_text(errors="ignore").splitlines():
            if line.startswith("#") and line[1:].isdigit():
                t = int(line[1:]) * 1000
            elif t is not None:
                lines.append((t, line))
    z = HOME / ".zsh_history"
    if z.exists():
        for line in z.read_text(errors="ignore").splitlines():
            m = re.match(r"^: (\d+):\d+;(.*)$", line)
            if m:
                lines.append((int(m.group(1)) * 1000, m.group(2)))
    for t, line in sorted(lines):
        if not (ms(start) <= t < ms(end)) or NOISE_CMDS.match(line) or line == last:
            continue
        last = line
        out.append({"t": t, "src": "terminal", "module": "[Unspecified]", "text": f"ran: {line[:200]}"})
    return out


def _module_for_file(path):
    m = module_for(Path(path).name)
    return m if m not in ("[Unspecified]", "Workstation/Config") else module_for(str(path))


def recent_files(start, end):
    """Files opened in any desktop app (GNOME recently-used list; Windows "Recent" folder)."""
    import xml.etree.ElementTree as ET
    out = []
    if IS_WIN:
        for lnk in (APPDATA / "Microsoft/Windows/Recent").glob("*.lnk"):
            try:
                mt = lnk.stat().st_mtime
            except OSError:
                continue
            if not (start.timestamp() <= mt < end.timestamp()):
                continue
            name = lnk.stem
            mod = _module_for_file(name)
            if mod is not None and "." in name:
                out.append({"t": int(mt * 1000), "src": "files-opened", "module": mod, "text": f"opened {name}"})
        return out
    p = HOME / ".local/share/recently-used.xbel"
    if not p.exists():
        return out
    shots = []
    for b in ET.parse(p).getroot().iter("bookmark"):
        stamps = []
        for attr in ("added", "modified", "visited"):
            v = b.get(attr)
            if v:
                try:
                    stamps.append(int(datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() * 1000))
                except ValueError:
                    pass
        stamps = [s for s in stamps if ms(start) <= s < ms(end)]
        if not stamps:
            continue
        path = file_from_uri(b.get("href", ""))
        if re.search(r"/Pictures/Screenshots/|/Videos/Screencasts/", path):
            shots.append(min(stamps))
            continue
        mod = _module_for_file(path)
        if mod is None:
            continue
        apps = sorted({a.get("name") for a in b.iter() if a.tag.endswith("application") and a.get("name")})
        out.append({"t": min(stamps), "src": "files-opened", "module": mod,
                    "text": f"opened {Path(path).name}" + (f" ({', '.join(apps)})" if apps else "")
                            + f" — {home_path(Path(path).parent)}"})
    if shots:
        out.append({"t": min(shots), "t_end": max(shots), "src": "files-opened", "module": "[Unspecified]",
                    "text": f"took {len(shots)} screenshot(s)/screencast(s)"})
    return out


def files_changed(start, end):
    """Files created/changed on the day. Inside a git repo: one summary line per repo."""
    out, per_repo = [], defaultdict(list)
    skip = set(CFG.get("file_skip_dirs", []))
    lo, hi = start.timestamp(), end.timestamp()
    for root in CFG.get("file_scan_dirs", []):
        root = Path(os.path.expanduser(root))
        for dirpath, dirnames, filenames in os.walk(root):
            if any(i in dirpath for i in CFG["ignore_dirs"]):
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
            repo = next((p for p in [Path(dirpath), *Path(dirpath).parents] if (p / ".git").exists()), None)
            for f in filenames:
                fp = Path(dirpath) / f
                try:
                    mt = fp.stat().st_mtime
                except OSError:
                    continue
                if not (lo <= mt < hi) or f.startswith("."):
                    continue
                if repo:
                    per_repo[repo].append((mt, str(fp.relative_to(repo))))
                else:
                    verb = "downloaded/saved" if "Downloads" in dirpath else "created/edited"
                    out.append({"t": int(mt * 1000), "src": "files-changed", "module": _module_for_file(fp),
                                "text": f"{verb} {f} — {home_path(dirpath)}"})
    for repo, files in per_repo.items():
        files.sort()
        sample = ", ".join(sorted({Path(f).name for _, f in files})[:6])
        out.append({"t": int(files[0][0] * 1000), "t_end": int(files[-1][0] * 1000), "src": "files-changed",
                    "module": module_for(str(repo)),
                    "text": f"changed {len(files)} file(s) in {repo.name} (e.g. {sample})"})
    return out


def opencode(start, end):
    out = []
    db = next((p for p in (HOME / ".local/share/opencode/opencode.db", LOCALAPPDATA / "opencode/opencode.db",
                           HOME / "Library/Application Support/opencode/opencode.db") if p.exists()), None)
    if not db:
        return out
    c = copy_db(db)
    q = """select m.type, m.time_created, m.data, s.directory, s.title
           from session_message m join session_v2 s on s.id=m.session_id
           where m.time_created>=? and m.time_created<? and m.type in ('user','assistant')
           order by m.time_created"""
    for typ, t, data, directory, title in c.execute(q, (ms(start), ms(end))):
        mod = module_for(directory)
        if mod is None:
            continue
        try:
            d = json.loads(data)
        except Exception:
            continue
        if typ == "user" and d.get("text"):
            out.append({"t": t, "src": "opencode", "module": mod,
                        "text": f"[session: {title}] prompt: {d['text'][:400]}"})
        elif typ == "assistant":
            for part in d.get("content", []) or []:
                if part.get("type") in ("tool", "tool-call", "tool_use"):
                    inp = part.get("input") or part.get("state", {}).get("input") or {}
                    cmd = inp.get("command") if isinstance(inp, dict) else None
                    if cmd and not NOISE_CMDS.match(cmd):
                        out.append({"t": t, "src": "opencode-cmd", "module": mod, "text": f"ran: {cmd[:200]}"})
    return out


def claude(start, end):
    out = []
    enc = lambda p: re.sub(r"[^A-Za-z0-9]", "-", str(p))      # how Claude Code names its project folders
    for f in (HOME / ".claude/projects").glob("*/*.jsonl"):
        if f.stat().st_mtime < start.timestamp():
            continue
        folder = f.parent.name
        for prefix in (enc(PROJ_ROOT) + "-", enc(HOME) + "-"):
            if folder.startswith(prefix):
                folder = folder[len(prefix):]
                break
        mod = module_for(folder)
        if mod is None:
            continue
        title = None
        with f.open(errors="ignore") as fh:
            for line in fh:
                if '"type":"user"' not in line and '"ai-title"' not in line and '"Bash"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if o.get("type") == "ai-title":
                    title = o.get("title") or o.get("aiTitle") or title
                ts = o.get("timestamp")
                if not ts:
                    continue
                t = int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() * 1000)
                if not (ms(start) <= t < ms(end)):
                    continue
                msg = o.get("message") or {}
                content = msg.get("content")
                if o.get("type") == "user" and not o.get("isMeta"):
                    text = content if isinstance(content, str) else " ".join(
                        p.get("text", "") for p in content or [] if isinstance(p, dict) and p.get("type") == "text")
                    text = re.sub(r"<[^>]+>[\s\S]*?</[^>]+>", "", text).strip()
                    if text and not text.startswith(("[Request interrupted", "Caveat:")):
                        out.append({"t": t, "src": "claude", "module": mod,
                                    "text": f"[session: {title or f.stem[:8]}] prompt: {text[:500]}"})
                elif o.get("type") == "assistant" and isinstance(content, list):
                    for p in content:
                        if p.get("type") == "tool_use" and p.get("name") == "Bash":
                            cmd = (p.get("input") or {}).get("command", "")
                            if cmd and not NOISE_CMDS.match(cmd):
                                out.append({"t": t, "src": "claude-cmd", "module": mod, "text": f"ran: {cmd[:200]}"})
    return out


def browser_profiles():
    """(kind, profile name, history file) for every browser profile on this PC."""
    if IS_WIN:
        bases = {"chrome": LOCALAPPDATA / "Google/Chrome/User Data", "edge": LOCALAPPDATA / "Microsoft/Edge/User Data",
                 "brave": LOCALAPPDATA / "BraveSoftware/Brave-Browser/User Data", "chromium": LOCALAPPDATA / "Chromium/User Data"}
        fox = [APPDATA / "Mozilla/Firefox/Profiles"]
    elif IS_MAC:
        sup = HOME / "Library/Application Support"
        bases = {"chrome": sup / "Google/Chrome", "edge": sup / "Microsoft Edge", "brave": sup / "BraveSoftware/Brave-Browser",
                 "chromium": sup / "Chromium"}
        fox = [sup / "Firefox/Profiles"]
    else:
        bases = {"chrome": HOME / ".config/google-chrome", "chromium": HOME / ".config/chromium",
                 "edge": HOME / ".config/microsoft-edge", "brave": HOME / ".config/BraveSoftware/Brave-Browser"}
        snap = HOME / "snap/chromium/common/chromium"
        if snap.exists():
            bases["chromium-snap"] = snap
        fox = [HOME / ".mozilla/firefox", HOME / "snap/firefox/common/.mozilla/firefox"]
    found = []
    for kind, base in bases.items():
        for prof in sorted([base / "Default", *base.glob("Profile *")]):
            if (prof / "History").exists():
                found.append((kind.replace("-snap", ""), prof.name, prof / "History"))
    for root in fox:
        for db in root.glob("*/places.sqlite"):
            found.append(("firefox", db.parent.name, db))
    wanted = CFG["browser"].get("profiles", "auto")
    if isinstance(wanted, list):                    # e.g. ["chrome:Default", "firefox"]
        keep = lambda k, n: any(w == k or w == f"{k}:{n}" for w in wanted)
        found = [f for f in found if keep(f[0], f[1])]
    return found


def browser(start, end):
    out = []
    block = CFG["browser"].get("block_domains") or []
    rows = []
    base = datetime(1601, 1, 1, tzinfo=timezone.utc)
    to_c = lambda dt: int((dt - base).total_seconds() * 1_000_000)
    for kind, name, db in browser_profiles():
        try:
            c = copy_db(db)
            if kind == "firefox":
                for vd, url, title in c.execute(
                        "select v.visit_date,p.url,p.title from moz_historyvisits v join moz_places p on p.id=v.place_id "
                        "where v.visit_date>=? and v.visit_date<?", (ms(start) * 1000, ms(end) * 1000)):
                    rows.append((vd / 1000, url, title, kind))
            else:
                for vt, url, title in c.execute(
                        "select v.visit_time,u.url,u.title from visits v join urls u on u.id=v.url "
                        "where v.visit_time>=? and v.visit_time<?", (to_c(start), to_c(end))):
                    rows.append(((base + timedelta(microseconds=vt)).timestamp() * 1000, url, title, f"{kind}:{name}"))
        except Exception:
            continue                                 # locked / unreadable profile — skip it
    seen = set()
    for t, url, title, prof in sorted(rows):
        host = (urlparse(url).hostname or "").removeprefix("www.")
        if not host and not url.startswith("file:"):
            continue
        if any(host == b or host.endswith("." + b) for b in block):
            continue
        if CFG["browser"].get("drop_search_engines", True) and (
                re.match(r"(google|bing)\.", host) and "/search" in url or host in ("google.com", "accounts.google.com")):
            continue
        key = (host, (title or "")[:80])
        if key in seen:
            continue
        seen.add(key)
        mod = module_for(f"{url} {title}") or "[Unspecified]"
        tid = re.search(r"app\.clickup\.com/t/(?:\d+/)?([\w-]+)", url)
        out.append({"t": int(t), "src": "browser", "module": mod,
                    "text": f"{title or '(no title)'} — {host}{urlparse(url).path[:60]}"
                            + (f" [ClickUp task {tid.group(1)}]" if tid else "")})
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(TZ).strftime("%Y-%m-%d"))
    a = ap.parse_args()
    start, end = day_window(a.date)

    events, errors = [], {}
    for name, fn in [("vscode", vscode), ("git", git), ("opencode", opencode), ("claude", claude), ("browser", browser),
                     ("git-actions", git_actions), ("files-opened", recent_files), ("files-changed", files_changed), ("terminal", terminal)]:
        try:
            events += fn(start, end)
        except Exception as e:  # keep going if one source fails
            errors[name] = repr(e)
    events.sort(key=lambda e: e["t"])

    # dedupe identical consecutive commands
    clean, last = [], None
    for e in events:
        k = (e["src"], e["text"])
        if k == last:
            continue
        last = k
        clean.append(e)

    # active blocks + idle gaps
    gap = CFG["idle_gap_minutes"] * 60_000
    blocks = []
    for e in clean:
        if blocks and e["t"] - blocks[-1][1] <= gap:
            blocks[-1][1] = max(blocks[-1][1], e.get("t_end", e["t"]))
        else:
            blocks.append([e["t"], e.get("t_end", e["t"])])

    (HERE / "raw").mkdir(exist_ok=True)
    (HERE / "digest").mkdir(exist_ok=True)
    raw = {"date": a.date, "errors": errors,
           "active_blocks": [f"{local(s)}-{local(e)}" for s, e in blocks],
           "events": [{**e, "time": local(e["t"])} for e in clean]}
    (HERE / "raw" / f"{a.date}.json").write_text(json.dumps(raw, indent=1, ensure_ascii=False), encoding="utf-8")

    by_mod = defaultdict(list)
    for e in clean:
        by_mod[e["module"]].append(e)
    people = sorted({p for e in clean for p in CFG.get("people", []) if re.search(rf"\b{p}\b", e["text"], re.I)})
    md = [f"# Digest {a.date}", f"Active blocks: {', '.join(raw['active_blocks']) or 'none'}",
          f"People mentioned: {', '.join(people) or 'none'}", f"Source errors: {errors or 'none'}", ""]
    for mod, evs in sorted(by_mod.items(), key=lambda kv: -len(kv[1])):
        md.append(f"## {mod}  ({len(evs)} events, {local(evs[0]['t'])}-{local(evs[-1]['t'])})")
        for e in evs:
            md.append(f"- {local(e['t'])} [{e['src']}] {e['text']}".replace("\n", " "))
        md.append("")
    (HERE / "digest" / f"{a.date}.md").write_text("\n".join(md), encoding="utf-8")
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"{len(clean)} events, {len(by_mod)} modules -> digest/{a.date}.md ; errors: {errors or 'none'}")


if __name__ == "__main__":
    main()
