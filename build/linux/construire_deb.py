"""Fabrique le paquet Linux de Pilote : Pilote_Linux.deb (docs/linux.md).

Pas de PyInstaller sous Linux : le paquet installe le code de Pilote dans
/opt/pilote et le lance avec le Python du systeme. La fenetre (GTK, WebKitGTK),
Pillow, le trousseau et les notifications viennent des paquets du systeme,
declares en dependances : apt les installe avec Pilote. Seules pywebview et
pypdf, ecrites entierement en Python, sont embarquees (/opt/pilote/lib). Le
paquet ne contient donc aucun code compile : un seul .deb (Architecture: all)
pour les PC x64 et les Chromebooks ARM.

Usage (sur Linux, avec dpkg-deb) : python3 build/linux/construire_deb.py [dossier de sortie]
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEPOT = Path(__file__).resolve().parents[2]
NOM_PAQUET = "Pilote_Linux.deb"     # cherche sous ce nom dans les releases

DEPENDANCES = ", ".join([
    "python3 (>= 3.9)",                                # pypdf 6 : Python 3.9 au moins
    "python3-gi", "gir1.2-gtk-3.0",
    "gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0",         # la fenetre de pywebview (GTK)
    "python3-pil",                                     # Pillow : icones, captures
    "libsecret-tools",                                 # secret-tool : codes chiffres
    "libnotify-bin",                                   # notify-send : notifications
    "xdg-utils",                                       # xdg-open : « Ouvrir le dossier »
    "ca-certificates",
])
# Le trousseau lui-meme (sans lui, Pilote refuse d'enregistrer un code) et
# udisks2 (ejection des cles USB) : presents sur un bureau, pas forcement
# dans le Linux d'un Chromebook
RECOMMANDES = "gnome-keyring, udisks2"

LANCEUR = """#!/bin/sh
# Pilote : lance l'app avec le Python du systeme (docs/linux.md)
export PYTHONPATH="/opt/pilote/lib${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 /opt/pilote/src/app.py "$@"
"""

BUREAU = """[Desktop Entry]
Type=Application
Name=Pilote
GenericName=Suivi personnel
Comment=Bourse, budget, sport et santé, 100 % sur ton ordinateur
Exec=pilote
Icon=pilote
Terminal=false
Categories=Office;Finance;
Keywords=PEA;bourse;budget;sport;santé;
StartupWMClass=pilote
"""

# Les .pyc s'ecrivent ici une fois pour toutes (/opt est en lecture seule pour
# l'utilisateur : sans eux, Python recompilerait tout a chaque lancement)
POSTINST = """#!/bin/sh
set -e
python3 -m compileall -q /opt/pilote/src /opt/pilote/lib > /dev/null 2>&1 || true
if command -v gtk-update-icon-cache > /dev/null; then gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true; fi
if command -v update-desktop-database > /dev/null; then update-desktop-database -q /usr/share/applications || true; fi
exit 0
"""

# Les donnees (~/.local/share/Pilote) ne sont jamais touchees
PRERM = """#!/bin/sh
set -e
find /opt/pilote -name __pycache__ -type d -prune -exec rm -rf {} + 2> /dev/null || true
exit 0
"""


def version() -> str:
    texte = (DEPOT / "src" / "app.py").read_text(encoding="utf-8")
    return re.search(r'^APP_VERSION\s*=\s*"([0-9.]+)"', texte, re.M).group(1)


def bibliotheques() -> list:
    """pywebview et pypdf aux versions de requirements.txt pour Linux."""
    voulues = []
    for ligne in (DEPOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if ligne.startswith("pywebview==") and 'sys_platform == "linux"' in ligne:
            voulues.append(ligne.split(";")[0].strip())
        if ligne.startswith("pypdf==") and '>= "3.9"' in ligne:
            voulues.append(ligne.split(";")[0].strip())
    if len(voulues) != 2:
        sys.exit("requirements.txt : pywebview (Linux) ou pypdf introuvable : %s" % voulues)
    return voulues


def icones(racine: Path) -> None:
    from PIL import Image
    with Image.open(DEPOT / "assets" / "icon.ico") as ico:
        ico.size = max(ico.info.get("sizes") or [ico.size])
        grande = ico.convert("RGBA")
    for cote in (48, 64, 128, 256):
        dossier = racine / ("usr/share/icons/hicolor/%dx%d/apps" % (cote, cote))
        dossier.mkdir(parents=True, exist_ok=True)
        grande.resize((cote, cote), Image.LANCZOS).save(dossier / "pilote.png")


def ecrire(chemin: Path, texte: str, mode: int = 0o644) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", encoding="utf-8", newline="\n") as f:   # LF, meme fabrique sous Windows
        f.write(texte)
    chemin.chmod(mode)


def construire(sortie: Path) -> Path:
    v = version()
    with tempfile.TemporaryDirectory(prefix="pilote-deb-") as tmp:
        racine = Path(tmp) / "pilote"
        opt = racine / "opt" / "pilote"
        shutil.copytree(DEPOT / "src", opt / "src",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "ocr_win.ps1"))
        (opt / "assets").mkdir(parents=True)
        shutil.copy2(DEPOT / "assets" / "icon.ico", opt / "assets" / "icon.ico")
        shutil.copy2(DEPOT / "THIRD-PARTY-NOTICES.txt", opt / "THIRD-PARTY-NOTICES.txt")

        # (proxy_tools, dependance de pywebview, n'existe qu'en sources : pas
        # de --only-binary ; la verification du code compile suit)
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--no-compile",
                        "--target", str(opt / "lib"), *bibliotheques()],
                       check=True)
        shutil.rmtree(opt / "lib" / "bin", ignore_errors=True)
        # pywebview livre aussi les DLL de WebView2 pour Windows : inutiles ici
        shutil.rmtree(opt / "lib" / "webview" / "lib", ignore_errors=True)
        compiles = [str(p.relative_to(opt)) for p in (opt / "lib").rglob("*")
                    if p.suffix in (".so", ".pyd", ".dll", ".dylib")]
        if compiles:
            # Un seul paquet pour toutes les puces : rien de compile n'y a sa place
            sys.exit("code compile dans lib/, le paquet ne serait plus « all » : %s" % compiles[:5])
        for p in list((opt / "lib").rglob("__pycache__")):
            shutil.rmtree(p, ignore_errors=True)

        ecrire(racine / "usr/bin/pilote", LANCEUR, 0o755)
        ecrire(racine / "usr/share/applications/pilote.desktop", BUREAU)
        icones(racine)
        doc = racine / "usr/share/doc/pilote"
        doc.mkdir(parents=True)
        shutil.copy2(DEPOT / "LICENSE", doc / "copyright")
        shutil.copy2(DEPOT / "THIRD-PARTY-NOTICES.txt", doc / "THIRD-PARTY-NOTICES.txt")

        for d in [p for p in racine.rglob("*") if p.is_dir()] + [racine]:
            d.chmod(0o755)
        for f in [p for p in racine.rglob("*") if p.is_file() and p.name != "pilote"]:
            f.chmod(0o644)

        taille = sum(p.stat().st_size for p in racine.rglob("*") if p.is_file()) // 1024 + 1
        control = "\n".join([
            "Package: pilote",
            "Version: " + v,
            "Architecture: all",
            "Maintainer: Pilote <pilote.appli@gmail.com>",
            "Installed-Size: %d" % taille,
            "Depends: " + DEPENDANCES,
            "Recommends: " + RECOMMANDES,
            "Section: utils",
            "Priority: optional",
            "Homepage: https://pilote-appli.github.io",
            "Description: Suivi personnel : bourse, budget, sport, santé",
            " PEA, comptes-titres, crypto, budget, sport, santé et patrimoine",
            " réunis dans une seule application. Tout reste sur l'ordinateur :",
            " pas de compte, pas de serveur, pas de télémétrie.",
            "",
        ])
        ecrire(racine / "DEBIAN/control", control)
        ecrire(racine / "DEBIAN/postinst", POSTINST, 0o755)
        ecrire(racine / "DEBIAN/prerm", PRERM, 0o755)

        sortie.mkdir(parents=True, exist_ok=True)
        deb = sortie / NOM_PAQUET
        subprocess.run(["dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(racine), str(deb)],
                       check=True)
    print("%s : version %s, %d Ko installes" % (deb, v, taille))
    return deb


if __name__ == "__main__":
    construire(Path(sys.argv[1] if len(sys.argv) > 1 else DEPOT / "dist"))
