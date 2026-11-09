#!/usr/bin/env python3
"""My Work Log — first-run setup (used by install.sh and install.ps1).

Detects what it can (name + email from git, the projects folder and its repositories,
time zone) and asks only to confirm. Creates:
  config.yaml          personal settings (from config.example.yaml)
  sheet_webhook.json   private key for the Google Sheet script (web-app URL is added later)
  mail_settings.json   daily email on/off + recipient

Usage:  python setup_config.py [--yes] [--reconfigure]
"""
import argparse, json, os, re, secrets, subprocess, sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home()
IS_WIN = os.name == "nt"


def git_conf(key):
    try:
        return subprocess.run(["git", "config", "--global", key], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def os_full_name():
    if IS_WIN:
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command",
                                  "([adsi]\"WinNT://$env:USERDOMAIN/$env:USERNAME,user\").FullName"],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
            return out
        except Exception:
            return ""
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_gecos.split(",")[0]
    except Exception:
        return ""


def find_projects_root():
    """The folder (among the usual places) that holds the most git repositories."""
    cands = [HOME / p for p in ("Projects", "projects", "Code", "code", "dev", "Dev", "workspace", "Workspace",
                                "src", "repos", "git", "GitHub", "Documents/GitHub", "source/repos",
                                "Desktop", "Documents", "Desktop/Projects", "Documents/Projects")]
    cands += [p for p in (HOME / "Desktop").glob("*") if p.is_dir()] if (HOME / "Desktop").exists() else []
    best, score = HOME / "Projects", -1
    for c in cands:
        if not c.is_dir():
            continue
        try:
            n = sum(1 for _ in c.glob("*/.git")) + sum(1 for _ in c.glob("*/*/.git"))
        except OSError:
            continue
        if n > score:
            best, score = c, n
    return best, max(score, 0)


def repos_in(root):
    out = []
    for g in list(root.glob("*/.git")) + list(root.glob("*/*/.git")):
        name = g.parent.name
        if name.startswith(".") or name == HERE.name or (g.parent / "setup_config.py").exists():
            continue                                      # skip My Work Log itself (any copy)
        out.append(name)
    return sorted(set(out), key=str.lower)[:40]


def pretty(name):
    words = re.split(r"[-_ .]+", name)
    return " ".join(w if w.isupper() and len(w) > 1 else w.capitalize() for w in words if w) or name


def ask(label, default, yes):
    if yes or not sys.stdin.isatty():
        return default
    v = input(f"  {label} [{default}]: ").strip()
    return v or default


def q(s):
    return json.dumps(str(s), ensure_ascii=False)          # a safe double-quoted YAML string


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="accept detected values without asking")
    ap.add_argument("--reconfigure", action="store_true", help="rewrite config.yaml even if it exists")
    a = ap.parse_args()

    cfg_path = HERE / "config.yaml"
    if cfg_path.exists() and not a.reconfigure:
        print("  config.yaml already exists — kept (use --reconfigure to start over)")
    else:
        print("\n  A few questions (press Enter to accept the value in brackets):")
        name = ask("Your name", git_conf("user.name") or os_full_name() or os.environ.get("USER") or os.environ.get("USERNAME") or "Me", a.yes)
        role = ask("Your role", "Software Engineer", a.yes)
        org = ask("Organization (optional)", "", a.yes)
        email = ask("Email for the daily report", git_conf("user.email"), a.yes)
        gitname = git_conf("user.name") or name
        root, n = find_projects_root()
        root = Path(os.path.expanduser(ask(f"Projects folder ({n} git repos found)", str(root), a.yes)))
        hours = ask("Working hours per day", "8", a.yes)
        workdays = ask("Work days", "Mon–Fri", a.yes)

        repos = repos_in(root) if root.exists() else []
        modules = "\n".join(f"  {q(r)}: {q(pretty(r))}" for r in repos) or '  # "my-repo-folder": "My Project"'
        labels = [pretty(r) for r in repos][:15] + ["Testing & QA", "Documentation", "Meetings", "Research", "Workstation"]
        labels = "\n".join(f"  - {q(x)}" for x in dict.fromkeys(labels))
        try:
            root_str = "~/" + root.relative_to(HOME).as_posix()
        except ValueError:
            root_str = str(root)

        t = (HERE / "config.example.yaml").read_text(encoding="utf-8")
        for k, v in {"__NAME__": name, "__SHORT__": name.split()[0] if name.split() else name, "__ROLE__": role,
                     "__ORG__": org, "__EMAIL__": email, "__TODAY__": date.today().isoformat(),
                     "__WORKDAYS__": workdays, "__PROJECTS__": root_str}.items():
            t = t.replace(k, str(v).replace('"', "'"))
        t = t.replace("__GITNAMES__", json.dumps([gitname], ensure_ascii=False))
        t = t.replace("__HOURS__", str(float(hours) if "." in hours else int(hours or 8)))
        t = t.replace("__MODULES__", modules).replace("__LABELS__", labels)
        cfg_path.write_text(t, encoding="utf-8")
        print(f"  ✓ config.yaml written ({len(repos)} projects found in {root_str})")

    hook = HERE / "sheet_webhook.json"
    h = {}
    if hook.exists():
        try:
            h = json.loads(hook.read_text(encoding="utf-8"))
        except Exception:
            h = {}
    if not h.get("token"):
        h = {"url": h.get("url", ""), "token": secrets.token_urlsafe(32)}
        hook.write_text(json.dumps(h, indent=2), encoding="utf-8")
        try:
            os.chmod(hook, 0o600)
        except OSError:
            pass
        print("  ✓ private sheet key created (sheet_webhook.json)")

    mail = HERE / "mail_settings.json"
    if not mail.exists():
        import yaml
        email = (yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}).get("owner", {}).get("email", "")
        mail.write_text(json.dumps({"enabled": bool(email), "to": [email] if email else []}, indent=2), encoding="utf-8")
        print(f"  ✓ daily email {'to ' + email if email else 'off (add a recipient in the dashboard)'}")


if __name__ == "__main__":
    main()
