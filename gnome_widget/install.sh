#!/usr/bin/env bash
# My Work Log widget for GNOME — clock + workday countdown on the desktop and on the lock screen.
#   ./gnome_widget/install.sh           install + turn on (on Wayland it appears after logging out and in once)
#   ./gnome_widget/install.sh --remove  turn off + remove
set -e
UUID="my-work-log-widget@worklog.local"
SRC="$(cd "$(dirname "$0")" && pwd)/$UUID"
DST="$HOME/.local/share/gnome-shell/extensions/$UUID"
if [ "$1" = "--remove" ]; then
  gnome-extensions disable "$UUID" 2>/dev/null || true
  rm -rf "$DST"
  echo "Removed the My Work Log widget."
  exit 0
fi
mkdir -p "$(dirname "$DST")"
rm -rf "$DST"
ln -s "$SRC" "$DST"                       # linked: updates to the project reach the widget
if gnome-extensions enable "$UUID" 2>/dev/null; then
  echo "My Work Log widget is on."
else                                       # GNOME hasn't seen the new extension yet (Wayland): turn it on for the next login
  cur=$(gsettings get org.gnome.shell enabled-extensions)
  case "$cur" in *"$UUID"*) ;; "@as []") gsettings set org.gnome.shell enabled-extensions "['$UUID']";;
    *) gsettings set org.gnome.shell enabled-extensions "${cur%]*}, '$UUID']";; esac
  echo "Installed. Log out and back in once — then the widget shows on the desktop and the lock screen."
fi
