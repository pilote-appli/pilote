"""
notifications.py — Notifications Windows toast natives.

Utilise win10toast si dispo (pip install win10toast). Sur Mac, osascript
(fourni avec macOS) fait l'equivalent sans dependance ; sous Linux, notify-send
(docs/linux.md). Ailleurs, ou si la lib
manque, les fonctions deviennent des no-ops silencieux, pour ne jamais faire
crasher l'app.

Les preferences sont lues depuis storage.load_data()['notifs'] :
  - bigMove   : alerte cours qui bouge > +/- 5%
  - dividend  : dividende prevu aujourd'hui
  - yahooDown : Yahoo injoignable
"""
from __future__ import annotations

import sys
import shutil
import subprocess
import threading
import importlib.util
from pathlib import Path
from typing import Optional

# win10toast n'est importe qu'a la premiere notification : il charge
# pkg_resources, qui coutait a lui seul 2,2 s au lancement de Pilote (mesure
# du 16/11/2026, python -X importtime). Ici, on regarde seulement s'il est la.
_toaster = None
try:
    _AVAILABLE = (sys.platform == "darwin"
                  # Linux : notify-send (paquet libnotify-bin, dependance du .deb)
                  or (sys.platform.startswith("linux") and shutil.which("notify-send") is not None)
                  or importlib.util.find_spec("win10toast") is not None)
except Exception:
    _AVAILABLE = False


def _icon_path() -> Optional[str]:
    """Cherche l'icone .ico dans /assets pour les toasts (sinon icone par defaut)."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "assets" / "icon.ico", here / "icon.ico"):
        if candidate.exists():
            return str(candidate)
    return None


def _show_mac(title: str, msg: str) -> None:
    def chaine(s) -> str:   # chaine AppleScript : \ et " echappes
        return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'
    try:
        subprocess.run(["osascript", "-e",
                        f"display notification {chaine(msg)} with title {chaine(title)}"],
                       capture_output=True, timeout=10)
    except Exception as e:
        print(f"[notif] Echec osascript : {e}", flush=True)


def _show_linux(title: str, msg: str) -> None:
    try:
        subprocess.run(["notify-send", "--app-name=Pilote", "--icon=pilote", title, msg],
                       capture_output=True, timeout=10)
    except Exception as e:
        print(f"[notif] Echec notify-send : {e}", flush=True)


# win10toast ne supporte pas deux notifications a la fois (la seconde etait
# perdue, avec une erreur dans crash.log) : elles passent l'une apres l'autre
_verrou_toast = threading.Lock()


def _show(title: str, msg: str, duration: int = 6) -> None:
    global _toaster
    if sys.platform == "darwin":
        _show_mac(title, msg)
        return
    if sys.platform.startswith("linux"):
        if _AVAILABLE:
            _show_linux(title, msg)
        return
    if not _AVAILABLE:
        return
    icon = _icon_path()
    try:
        # Deja dans un fil a part (notify) : on attend ici la fin du toast
        # precedent au lieu de bloquer l'interface
        with _verrou_toast:
            if _toaster is None:
                from win10toast import ToastNotifier  # type: ignore
                _toaster = ToastNotifier()
            _toaster.show_toast(
                title, msg,
                icon_path=icon,
                duration=duration,
                threaded=False,
            )
    except Exception as e:
        print(f"[notif] Echec toast : {e}", flush=True)


# ─── API publique ─────────────────────────────────────────────────────────────

def notify(title: str, msg: str, kind: str, prefs: dict) -> None:
    """
    Affiche une notif si l'utilisateur l'a activee.
      kind : 'bigMove' | 'dividend' | 'yahooDown' | 'info'
      prefs : dict de preferences (depuis pea_data.json -> notifs)
    """
    if kind != "info" and not prefs.get(kind, False):
        return
    threading.Thread(target=_show, args=(title, msg), daemon=True).start()


def is_available() -> bool:
    return _AVAILABLE
