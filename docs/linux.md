# Pilote sous Linux et sur Chromebook

Fiche détaillée tirée de `CLAUDE.md`. Commencé le 17/11/2026, à la demande
d'Arthur (« rendre possible l'installation sur Linux aujourd'hui »), pour
couvrir aussi les Chromebooks, qui font tourner Linux.

## Décisions (17/11/2026)

* **Même application**, comme pour le Mac : même code, même numéro de version,
  même format de données. Ce qui diffère passe par `sys.platform.startswith("linux")`
  ou `plateforme.py` ; le chemin Windows reste celui d'avant.
* **Un paquet .deb, sans PyInstaller** (`build/linux/construire_deb.py`). Le
  paquet installe le code dans `/opt/pilote` et le lance avec le Python du
  système (`/usr/bin/pilote`). GTK, WebKitGTK, Pillow, `secret-tool` et
  `notify-send` sont des dépendances du paquet : apt les installe avec Pilote.
  Seules pywebview 6.2.1 et pypdf, écrites entièrement en Python, sont
  embarquées (`/opt/pilote/lib`). Conséquence voulue : **aucun code compilé,
  un seul `Pilote_Linux.deb` (Architecture: all) pour x64 et ARM**. Le script
  refuse de fabriquer le paquet si un fichier compilé arrive dans `lib/`.
  Pourquoi pas PyInstaller : WebKitGTK lance ses propres processus depuis des
  chemins du système ; le figer dans un exe est fragile, et il faudrait un
  paquet par puce.
* **.deb plutôt qu'AppImage** : c'est ce qu'un Chromebook installe d'un
  double-clic (application Fichiers → Installer), et il déclare ses
  dépendances. Fedora et Arch : plus tard, si quelqu'un le demande.
* **Tests sur les machines Linux de GitHub** (`build-linux.yml`, branche
  `mac` comme les deux autres) : Ubuntu 24.04 x64, Ubuntu 24.04 ARM,
  Ubuntu 22.04, Debian 12 (le Linux d'un Chromebook, en conteneur). Gratuit
  pour un dépôt public. Personne n'a de Chromebook sous la main.

## Étapes

| # | Étape | État |
|---|---|---|
| 1 | Socle : données, fenêtre, fermeture, notifications, paquet .deb | fait (17/11/2026) |
| 2 | Codes chiffrés dans le trousseau de Linux | fait (17/11/2026) |
| 3 | Rapport, PDF du bilan, clés USB, lecture des captures coupée | fait (17/11/2026) |
| 4 | Paquet joint à chaque release (`release.yml`, job `linux`), README, notes de release | fait (17/11/2026) |
| 5 | Mise à jour installée par Pilote (`updater._installer_linux`) | fait (17/11/2026) : voir « Mise à jour » |
| 6 | Règle « Mac, Windows et Linux avant le tag » dans `CLAUDE.md`, `tests/lire_tests.py` | fait (17/11/2026) |

## Ce qui est en place

* **Données** : `~/.local/share/Pilote/Donnees` (ou `$XDG_DATA_HOME`) quand
  Pilote tourne depuis le paquet (`plateforme.paquet_linux()` : le code est
  sous `/opt/pilote/`, en lecture seule). En dev, `Donnees/` à la racine du
  dépôt, comme ailleurs. `scan_orphan_data()` rend `[]` pour le paquet.
* **Fenêtre** : barre de titre du système (`frameless` seulement sous
  Windows), comme sur Mac. La page le sait par `EST_LINUX` (agent WebKitGTK,
  « Linux » sans « Android ») et la classe `html.os-linux` : pas de barre
  maison, pas de marge de 36 px. Raccourcis en Ctrl et textes « ce PC »
  comme sous Windows ; `.txt-windows` (un texte qui nomme Windows) cède la
  place à `.txt-lin`, et `.win-seul` est caché. Ouverte agrandie par le
  gestionnaire de fenêtres (`maximized`) ; l'état est suivi par les
  évènements GTK `maximized` et `restored`. `GLib.set_prgname("pilote")`
  rattache la fenêtre au lanceur `pilote.desktop` (`StartupWMClass=pilote`).
* **Pont JS ↔ Python** : WebKitGTK applique la CSP de la page comme WebKit sur
  Mac. `plateforme.adapter_pont_mac` (pas de `new Function`, `run_js` au lieu
  d'`evaluate_js`) est donc appliqué aussi sous Linux. Ne jamais ajouter
  `'unsafe-eval'` à la CSP.
* **Fermeture** : le chemin du Mac (`_on_closing`) : la croix du système est
  annulée une première fois, la page écrit ce qui attend, puis Pilote se
  ferme. Filet de 5 s, puis `os._exit` 3 s après la fin de `webview.start()`.
  **Piège (vu sur le test du 17/11/2026)** : sous GTK, `destroy()` repasse
  par l'évènement `closing`, dans le fil principal de GTK (pas sur Mac). Y
  relire la taille de la fenêtre (`_sauver_fenetre`) attend ce même fil :
  Pilote ne quittait plus, et la relance après une mise à jour attendait pour
  toujours. `_on_closing` ne la relit donc pas une seconde fois hors Windows.
* **Rendu** : `WEBKIT_DISABLE_DMABUF_RENDERER=1` (posé par `main()`, sauf si
  déjà réglé). Avec le rendu DMA-BUF de WebKitGTK, la fenêtre restait noire
  sur les captures du test (écran virtuel) ; le même défaut est connu sur des
  cartes NVIDIA et des machines virtuelles.
* **Codes chiffrés** (Actus, Agenda, Garmin, Coros, clé des sauvegardes) :
  trousseau de la session (Secret Service : GNOME Keyring, KWallet), par
  `secret-tool` (`actus._secret_tool`). Le fichier garde `secret:<compte>`. Le
  code passe par l'entrée standard, jamais en argument. **Sans trousseau,
  Pilote refuse d'enregistrer le code** avec un message (« installe
  gnome-keyring »). Jusqu'au 17/11/2026, hors Windows et Mac, le code était
  seulement encodé en base64, autant dire en clair. Le préfixe `b64:` reste
  lisible pour ne rien casser.
* **Notifications** : `notify-send` (paquet `libnotify-bin`), icône `pilote`.
* **Rapport annuel et bilan de la semaine** : ouverts dans le navigateur
  (Ctrl+P), comme sur Mac. L'impression d'une iframe par WebKitGTK n'a pas été
  essayée.
* **PDF du bilan joint à la notification** : Chromium, Chrome, Edge ou Brave
  s'il y en a un (`plateforme._chromium`), snap compris.
* **Clés USB** : `lsblk` (volumes montés d'un disque amovible, branché à
  chaud ou en USB), suivis par l'UUID de leur volume ; éjection par
  `udisksctl unmount` puis `power-off`. Sur un Chromebook, une clé partagée
  avec Linux apparaît sous `/mnt/chromeos/removable/<nom>`, sans bloc visible
  ni UUID : on la suit par son nom, et l'éjection se fait depuis ChromeOS.
* **Lecture des captures** (Santé, relevés en image) : coupée, avec le
  message « pas encore disponible sous Linux ». La saisie à la main marche.
  Piste : Tesseract, mais il alourdit le paquet.
* **Mise à jour** : voir plus bas.
* **« Signaler un problème »** : système lu dans `/etc/os-release`
  (« Linux Debian GNU/Linux 12 (bookworm) (aarch64) »).

## Paquet

* `python3 build/linux/construire_deb.py [dossier]` (sur Linux, `dpkg-deb`
  requis) : version lue dans `src/app.py`, pywebview et pypdf aux versions des
  lignes Linux de `requirements.txt`. `postinst` compile les `.pyc` une fois
  (sans eux, Python recompilerait à chaque lancement : `/opt` n'est pas
  modifiable par l'utilisateur), `prerm` les retire. Les données de
  l'utilisateur ne sont jamais touchées par la désinstallation.
* Dépendances : `python3 (>= 3.9)` (pypdf 6), `python3-gi`, `gir1.2-gtk-3.0`,
  `gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0`, `python3-pil`, `libsecret-tools`,
  `libnotify-bin`, `xdg-utils`, `ca-certificates`. Recommandés :
  `gnome-keyring`, `udisks2`.
* Pillow vient du système : 9.0 sur Ubuntu 22.04. `Image.Resampling` (Pillow
  9.1) n'est utilisé que par `appicon.py`, qui ne tourne pas sous Linux.
* **Ne pas renommer `Pilote_Linux.deb`** : la future mise à jour (étape 5) le
  cherchera sous ce nom dans chaque release, comme `Pilote_Mac.zip`.

## Mise à jour (étape 5, 17/11/2026)

* `updater.py` cherche `Pilote_Linux.deb` (`LINUX_ASSET`) dans la release,
  par l'API ou la page publique, comme le Setup. Proposée seulement depuis le
  paquet (`plateforme.paquet_linux()`), jamais en dev.
* `_installer_linux` : téléchargement, taille et SHA-256 comparés à ceux de
  l'API (`_conforme`), puis `dpkg-deb -f` : le paquet doit s'appeler `pilote`
  et porter la version annoncée. Installation par `apt-get install` du
  fichier, avec les droits d'administrateur, dans l'ordre : déjà root
  (conteneur), `sudo -n` (sans mot de passe : le Linux d'un Chromebook),
  `pkexec` (Linux demande le mot de passe dans une fenêtre). Puis un script
  attend la fin de Pilote et le relance (`/usr/bin/pilote`).
* Sans `sudo` ni `pkexec` qui aboutissent (mot de passe refusé, pas d'agent
  polkit) : le paquet est copié dans Téléchargements (`xdg-user-dir`), ouvert
  par `xdg-open` (l'installeur du système), et l'écran dit de double-cliquer
  dessus. Les données ne bougent jamais.
* Journal : `~/.local/state/Pilote/update.log` (avant, hors Windows et Mac,
  `updater` aurait créé un dossier `~/Pilote`).
* Test : `essai.sh --maj` sert en local une version 99.0.0 (le même paquet et
  un fichier témoin) avec `PILOTE_MAJ_ESSAI` (`updater._essai`, Mac et Linux) ;
  Pilote doit l'installer et se relancer.

## Test (`build-linux.yml`)

* Job `paquet` : tests unitaires sous Linux, fabrication, contenu vérifié
  (`ui/vendor`, `nouveautes.json`, pywebview, lanceur, icône).
* Job `essai` (4 machines) : `build/linux/essai.sh` installe le paquet par
  apt, lance Pilote dans Xvfb et une session D-Bus avec un trousseau
  déverrouillé, et relit `PILOTE_DIAG` : serveur, page, HTTPS, trousseau,
  fermeture avec une écriture en attente. Capture en annotations
  « Capture <machine> i/N ». Puis l'essai de mise à jour (`--maj`).
* Les tests unitaires tournent aussi sous Linux (job `paquet`) : les tests en
  échec sortent en annotations. Piège rencontré : `test_agenda`, `test_garmin`
  et `test_coros` remplacent `actus._chiffrer` hors Windows pour toute la
  série ; `test_linux.py` travaille donc sur une copie neuve du module.
* Job `ecrans-linux` : les écrans de `tests/ecrans.txt` sur les données de
  Brice, « Ecran n linux i/N ».
* `python tests/lire_tests.py <sha>` recolle `capture-<machine>.jpg` et
  `ecran-<n>-linux.jpg`.

## Reste à vérifier

* Sur un vrai Chromebook : l'installation par double-clic, le trousseau
  (Crostini ne lance pas forcément GNOME Keyring à l'ouverture de session :
  il peut demander un mot de passe de trousseau au premier code enregistré),
  et les clés partagées.
* Le bac à sable de WebKitGTK (bubblewrap) dans le conteneur Debian du test,
  lancé en `--privileged`.
