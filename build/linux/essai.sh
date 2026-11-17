#!/bin/bash
# Essai du paquet Linux sur une machine de GitHub (build-linux.yml, docs/linux.md) :
# installe Pilote_Linux.deb par apt, comme un double-clic sur un Chromebook,
# lance Pilote dans un ecran virtuel (Xvfb) et une session D-Bus avec un
# trousseau deverrouille, puis relit ce qu'il a fait. Constats en annotations
# (10 au plus par etape GitHub : 9 ici), lisibles sans compte par
# tests/lire_tests.py.
#
# Usage : bash build/linux/essai.sh <Pilote_Linux.deb>
#         bash build/linux/essai.sh <Pilote_Linux.deb> --maj   (mise a jour par Pilote)
#         bash build/linux/essai.sh <Pilote_Linux.deb> --ecrans "<ecrans>"
#         (captures des ecrans de tests/ecrans.txt, sur les donnees d'exemple)

set -u
annot() { echo "::$1 title=$2::$(echo "$3" | tr '\n' ' ' | head -c 3000)"; }
DONNEES="${XDG_DATA_HOME:-$HOME/.local/share}/Pilote/Donnees"

# ─── Dans la session D-Bus : trousseau, puis Pilote ──────────────────────────
if [ "${1:-}" = "--session" ]; then
  shift
  # Trousseau deverrouille, comme apres l'ouverture de session d'un bureau
  echo -n "essai" | gnome-keyring-daemon --unlock --components=secrets > /dev/null 2>&1 || true
  if [ "${1:-}" = "--ecrans" ]; then
    PILOTE_ECRANS="$2" pilote > ecrans.log 2>&1 &
    PID=$!
    FAITES=0
    for i in $(seq 1 300); do
      N=$(grep -c "\[ecran\] [0-9]* pret" ecrans.log || true)
      while [ "$FAITES" -lt "$N" ]; do
        FAITES=$((FAITES+1))
        import -window root "$(printf "ecran-%02d" $((${DEBUT:-0}+FAITES))).png" || echo "capture $FAITES impossible"
      done
      grep -q "\[ecran\] fin" ecrans.log && break
      sleep 1
    done
    kill $PID 2>/dev/null || true
    echo "$FAITES" > ecrans.nombre
    exit 0
  fi

  if [ "${1:-}" = "--maj" ]; then
    # Mise a jour faite par Pilote lui-meme (updater._installer_linux) : une
    # « version 99.0.0 » (le meme paquet plus un fichier temoin) servie en
    # local comme une release ; Pilote doit l'installer par apt et se relancer
    PILOTE_DIAG=1 PILOTE_MAJ_ESSAI="http://127.0.0.1:8765/Pilote_Linux.deb|99.0.0" pilote > maj.log 2>&1 &
    PID=$!
    FIN="toujours ouvert apres 150 s"
    for i in $(seq 1 150); do
      if ! kill -0 $PID 2>/dev/null; then FIN="ferme apres $i s"; break; fi
      sleep 1
    done
    # Relancee par le script de l'updater (journal update_sh.log), pas
    # l'ancien processus encore la
    JOURNAL="${XDG_STATE_HOME:-$HOME/.local/state}/Pilote"
    RELANCE="pas relance"
    for i in $(seq 1 40); do
      if grep -q relancee "$JOURNAL/update_sh.log" 2>/dev/null && pgrep -f "/opt/pilote/src/app.py" > /dev/null; then RELANCE="relance"; break; fi
      sleep 1
    done
    PING="aucun port de 7438 a 7445 apres 60 s"
    for i in $(seq 1 60); do
      for P in 7438 7439 7440 7441 7442 7443 7444 7445; do
        if curl -fsS http://127.0.0.1:$P/ping > /dev/null 2>&1; then PING="200 sur $P en $i s"; break 2; fi
      done
      sleep 1
    done
    VERSION=$(dpkg-query -W -f '${Version}' pilote)
    TEMOIN=$(test -f /opt/pilote/temoin-maj.txt && echo "nouvelle version en place" || echo "ancienne version")
    annot notice "Mise a jour" "$FIN ; $RELANCE (ping $PING) ; paquet $VERSION ; $TEMOIN ; $(grep "\[maj\]" maj.log)"
    annot notice "Mise a jour (journaux)" "$(grep "INSTALL" "$JOURNAL/update.log" 2>/dev/null | tail -n 6) | $(tail -c 400 "$JOURNAL/update_sh.log" 2>/dev/null)"
    pkill -f "/opt/pilote/src/app.py" 2>/dev/null || true
    [ "$VERSION" = "99.0.0" ] || { annot error "Mise a jour" "le paquet n'a pas ete installe : $(tail -n 20 maj.log)"; exit 1; }
    case "$FIN" in toujours*) annot error "Mise a jour" "l'ancien Pilote ne s'est pas ferme"; exit 1;; esac
    [ "$RELANCE" = "relance" ] || { annot error "Mise a jour" "Pilote n'a pas ete relance"; exit 1; }
    exit 0
  fi

  PILOTE_DIAG=1 pilote > pilote.log 2>&1 &
  PID=$!
  # 1. Le serveur local repond
  UP=""
  for i in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:7438/ping > /dev/null 2>&1; then UP="$i"; break; fi
    sleep 1
  done
  # 2. L'interface a fini de demarrer (ligne ecrite par reveal_main_window)
  for i in $(seq 1 40); do
    grep -q "fenetre ouverte" pilote.log && break
    sleep 1
  done
  sleep 5
  import -window root capture.png 2>/dev/null || echo "capture impossible"
  # Capture noire au 17/11/2026 : la fenetre est-elle affichee, ou la capture
  # rate-t-elle ? Les fenetres X, la luminosite, et une seconde methode (xwd)
  xwd -root -silent > capture.xwd 2>/dev/null && convert xwd:capture.xwd capture-xwd.png 2>/dev/null
  annot notice "Ecran X" "$(xwininfo -root -tree 2>/dev/null | grep -iE 'pilote|[0-9]+x[0-9]+\+' | head -8) | import : $(convert capture.png -format '%[fx:mean] %[channels] %wx%h' info: 2>&1) | xwd : $(convert capture-xwd.png -format '%[fx:mean] %[channels]' info: 2>&1) | $(xwininfo -name Pilote 2>&1 | grep -E 'Map State|Depth|Visual Class|Width|Height' | tr -s ' ')"
  VENDOR=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:7438/vendor/chart.umd.js || true)
  OUVERTE=$(grep -o "fenetre ouverte ([a-z]*)" pilote.log || echo "pas de ligne")
  annot notice Serveur "ping ${UP:-KO} s - /vendor/chart.umd.js HTTP $VENDOR - $OUVERTE"
  annot notice Donnees "$DONNEES : $(ls "$DONNEES" 2>/dev/null || echo absent)"
  # 3. Journal de demarrage de la page (30 s apres le lancement)
  for i in $(seq 1 40); do grep -q "\[diag\]" pilote.log && break; sleep 1; done
  annot notice Diag "$(grep "\[diag\]" pilote.log | head -c 3000 || echo absent)"
  # 4. HTTPS (Yahoo, Gmail, GitHub) et bibliotheques, essayes par app.py a 16 s
  for i in $(seq 1 60); do grep -q "\[https\] cours" pilote.log && break; sleep 1; done
  annot notice HTTPS "$(grep -E "\[https\]|\[module\]" pilote.log || echo absent)"
  # 5. Trousseau, rapport, lecture d'images (app.py, _diag_mac_divers a 30 s)
  for i in $(seq 1 30); do grep -q "\[rapport\]" pilote.log && break; sleep 1; done
  annot notice Divers "$(grep -E "\[(ocr|trousseau|rapport|usb)\]" pilote.log || echo absent)"
  # 6. Fenetre et fermeture (_diag_fenetre a 45 s) : une ecriture laissee en
  #    attente, puis la croix ; Pilote doit l'ecrire et se fermer seul
  for i in $(seq 1 60); do grep -qE "\[fenetre\] (Quitter|KO)" pilote.log && break; sleep 1; done
  FIN="encore ouvert apres 20 s"
  for i in $(seq 1 20); do
    if ! kill -0 $PID 2>/dev/null; then FIN="ferme seul en $i s"; break; fi
    sleep 1
  done
  ECRIT=$(grep -l "ecrit avant de quitter" "$DONNEES"/users/*/pea_data.json 2>/dev/null | wc -l)
  annot notice Fenetre "$(grep -E "\[fenetre\]|\[app\] fermeture" pilote.log)"
  annot notice Fermeture "$FIN ; ecriture en attente retrouvee dans $ECRIT pea_data.json"
  kill $PID 2>/dev/null || true
  sleep 1
  # Echecs bloquants : serveur muet, page qui n'a pas demarre, erreur
  # JavaScript au demarrage, donnees ailleurs que dans le dossier personnel
  test -n "$UP" || { annot error Serveur "le serveur local ne repond pas : $(tail -n 30 pilote.log)"; exit 1; }
  grep -q "fenetre ouverte (page)" pilote.log || { annot error Interface "la page n'a pas fini de demarrer : $(grep -iE "error|erreur|traceback" pilote.log | head -c 2500)"; exit 1; }
  if grep "\[diag\]" pilote.log | grep -q "ERREUR "; then annot error Diag "erreur JavaScript au demarrage"; exit 1; fi
  test -d "$DONNEES" || { annot error Donnees "dossier absent"; exit 1; }
  case "$FIN" in ferme*) ;; *) annot error Fermeture "Pilote ne s'est pas ferme apres la croix"; exit 1;; esac
  [ "$ECRIT" -ge 1 ] || { annot error Fermeture "l'ecriture en attente a ete perdue"; exit 1; }
  test ! -e /opt/pilote/Donnees || { annot error Donnees "ecrit dans /opt/pilote"; exit 1; }
  exit 0
fi

# ─── Installation, puis la session ───────────────────────────────────────────
SUDO=""
[ "$(id -u)" -ne 0 ] && SUDO="sudo"
export DEBIAN_FRONTEND=noninteractive
OUTILS="xvfb xauth dbus dbus-x11 gnome-keyring imagemagick curl procps x11-utils x11-apps"
DEB="$(readlink -f "$1")"
shift
$SUDO apt-get update -qq > apt.log 2>&1
if ! $SUDO apt-get install -y -qq "$DEB" $OUTILS >> apt.log 2>&1; then
  annot error Installation "$(tail -n 25 apt.log)"
  exit 1
fi
if [ "${1:-}" = "--maj" ]; then
  # La fausse release 99.0.0, servie en local
  rm -rf maj99 srv && mkdir srv
  dpkg-deb -R "$DEB" maj99
  sed -i 's/^Version: .*/Version: 99.0.0/' maj99/DEBIAN/control
  echo "version d'essai" > maj99/opt/pilote/temoin-maj.txt
  dpkg-deb --root-owner-group --build maj99 srv/Pilote_Linux.deb > /dev/null
  python3 -m http.server 8765 --bind 127.0.0.1 --directory srv > http.log 2>&1 &
  sleep 1
elif [ "${1:-}" != "--ecrans" ]; then
  annot notice Installation "$(. /etc/os-release; echo "$PRETTY_NAME") $(uname -m) ; $(dpkg-query -W -f '${Package} ${Version}' pilote) ; $(python3 --version) ; WebKit : $(dpkg-query -W -f '${Package} ${Version} ' 'libwebkit2gtk-4.*' 2>/dev/null) ; $(du -sh /opt/pilote | cut -f1) dans /opt/pilote"
fi

Xvfb :99 -screen 0 1366x768x24 > /dev/null 2>&1 &
XVFB=$!
export DISPLAY=:99
sleep 2
dbus-run-session -- bash "$0" --session "$@"
CODE=$?
kill $XVFB 2>/dev/null || true
exit $CODE
