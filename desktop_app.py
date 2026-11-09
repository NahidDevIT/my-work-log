#!/usr/bin/env python3
"""My Work Log — install the desktop app (an app icon that opens the dashboard in its own window).

  python3 desktop_app.py            add "My Work Log" to the app menu (Linux) / Start menu + Desktop (Windows)
  python3 desktop_app.py --remove   remove it again

Linux: ~/.local/share/applications/my-work-log.desktop (+ icon) — opens in Chrome/Chromium/Edge/Brave app mode,
starting the dashboard first if it is not running. Windows: shortcuts that start the dashboard and open it
in Edge/Chrome app mode.
"""
import os, shutil, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8765"
IS_WIN = os.name == "nt"
NAME = "My Work Log"


def browser():
    """A Chromium-based browser that can open a page as an app window (or None)."""
    if IS_WIN:
        for p in (r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe", r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
                  r"%ProgramFiles%\Google\Chrome\Application\chrome.exe", r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
                  r"%LocalAppData%\Google\Chrome\Application\chrome.exe", r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"):
            p = os.path.expandvars(p)
            if os.path.exists(p):
                return p
        return None
    for b in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"):
        p = shutil.which(b)
        if p:
            return p
    return None


def python_exe():
    f = HERE / ".python"
    if f.exists() and Path(f.read_text().strip()).exists():
        return f.read_text().strip()
    return sys.executable


# ---------------------------------------------------------------- Linux
def linux_paths():
    apps = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "applications"
    icon = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "icons/hicolor/512x512/apps/my-work-log.png"
    return apps / "my-work-log.desktop", icon, HERE / "open_app.sh"


def install_linux():
    desk, icon, launcher = linux_paths()
    icon.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / "ui/icons/icon-512.png", icon)
    b = browser()
    open_cmd = f'"{b}" --app={URL} --class=MyWorkLog --user-data-dir="$HOME/.config/my-work-log-app"' if b else f"xdg-open {URL}"
    launcher.write_text(f"""#!/usr/bin/env bash
# My Work Log desktop app: start the dashboard if needed, then open it in its own window.
"{HERE}/start.sh" --no-open >/dev/null 2>&1
for i in 1 2 3 4 5 6 7 8 9 10; do curl -s -o /dev/null {URL}/api/ping && break; sleep 0.5; done
exec {open_cmd}
""", encoding="utf-8")
    launcher.chmod(0o755)
    desk.parent.mkdir(parents=True, exist_ok=True)
    desk.write_text(f"""[Desktop Entry]
Type=Application
Name={NAME}
Comment=My day, hours and work — written up automatically
Exec="{launcher}"
Icon=my-work-log
Terminal=false
Categories=Office;Utility;
StartupWMClass=MyWorkLog
Keywords=work;log;timesheet;hours;
""", encoding="utf-8")
    desk.chmod(0o755)
    for cmd in (["update-desktop-database", str(desk.parent)], ["gtk-update-icon-cache", "-q", "-t", str(icon.parents[2])]):
        try:
            subprocess.run(cmd, capture_output=True, timeout=20)
        except Exception:
            pass
    print(f"  ✓ desktop app installed: '{NAME}' in the app menu ({'own window via ' + Path(b).name if b else 'opens in the browser'})")


def remove_linux():
    for p in linux_paths():
        p.unlink(missing_ok=True)
    print("  ✓ desktop app removed")


# ---------------------------------------------------------------- Windows
def win_shortcuts():
    appdata = Path(os.environ.get("APPDATA", ""))
    desktop = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
    return [appdata / "Microsoft/Windows/Start Menu/Programs/My Work Log.lnk", desktop / "My Work Log.lnk"]


def install_windows():
    py = python_exe()
    pyw = str(Path(py).with_name("pythonw.exe")) if Path(py).with_name("pythonw.exe").exists() else py
    b = browser()
    ico = HERE / "ui/icons/app.ico"
    try:
        from PIL import Image
        Image.open(HERE / "ui/icons/icon-512.png").save(ico, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    except Exception:
        ico = None
    launcher = HERE / "open_app.cmd"
    open_cmd = f'start "" "{b}" --app={URL}' if b else f'start "" {URL}'
    launcher.write_text(f"""@echo off
rem My Work Log desktop app: start the dashboard if needed, then open it in its own window.
netstat -an | find ":8765" | find "LISTENING" >nul || start "" /b "{pyw}" "{HERE / 'server.py'}"
timeout /t 2 /nobreak >nul
{open_cmd}
""".replace("\n", "\r\n"), encoding="ascii", errors="ignore")
    for lnk in win_shortcuts():
        lnk.parent.mkdir(parents=True, exist_ok=True)
        ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');$s.TargetPath='{launcher}';"
              f"$s.WorkingDirectory='{HERE}';$s.WindowStyle=7;$s.Description='{NAME}';"
              + (f"$s.IconLocation='{ico}';" if ico else "") + "$s.Save()")
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=30)
    print(f"  [ok] desktop app installed: '{NAME}' in the Start menu and on the Desktop")


def remove_windows():
    for lnk in win_shortcuts():
        lnk.unlink(missing_ok=True)
    print("  [ok] desktop app removed")


if __name__ == "__main__":
    remove = "--remove" in sys.argv
    if IS_WIN:
        remove_windows() if remove else install_windows()
    elif sys.platform == "darwin":
        print("  macOS: open http://127.0.0.1:8765 in Chrome/Edge and choose Install My Work Log")
    else:
        remove_linux() if remove else install_linux()
