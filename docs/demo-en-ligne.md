# Démo en ligne (site, sous les boutons d'installation)

Décidé avec Arthur le 18/11/2026 : sur l'accueil de pilote-appli.github.io,
juste après les trois boutons d'installation, « À vous de piloter » et la
**vraie interface** de Pilote, remplie avec les données de Brice, où l'on peut
cliquer partout. Pilou propose la visite au démarrage (« Visiter avec Pilou »
ou « Je me débrouille ») ; la fin de la visite et le bandeau invitent à
installer. Sous la démo, « Pilote vous a plu ? Installez-le » et les trois
boutons.

## Comment ça marche

L'interface est `src/ui/index.html` tel quel. Dans l'app, elle lit par le
serveur local et écrit par le pont pywebview ; sur le site, aucun des deux
n'existe. `build/demo/demo.js`, chargé avant tout autre script, les remplace :

* **lectures** (`/data`, `/cours`, `/history`, `load_*`, `get_users`…) :
  réponses enregistrées sur Brice, dans `demo-donnees.js` (`window.__DEMO`).
  Une requête jamais vue reçoit la réponse de la même route la plus proche
  (même titre, autre période), jamais celle d'autres titres ;
* **écritures** (`save_*`) : acceptées puis oubliées. Un rechargement repart de
  Brice. `save_patrimoine` rend les chiffres enregistrés de `load_patrimoine` ;
* **connexions et fichiers** (Gmail, iCloud, montres, clé USB, imports,
  export) : refusés avec le message « Dans la démo, rien ne s'enregistre et
  rien ne se connecte ». `sauvegarde_usb_state`, `agenda_synchroniser` et
  `expositions_update`, que l'app demande toute seule, sont refusés en silence ;
* ce qui change à l'écran : bandeau « Démo » avec « Installer Pilote » (à la
  place de « Revenir à mon profil »), fin de visite qui invite à installer,
  boutons Réduire / Agrandir / Fermer masqués.

Brice est marqué `exemple` : c'est le « mode exemple » de l'app
(`docs/utilisateurs-et-pin.md`), avec sa visite de Pilou (`PILOU_VISITE`).

Rien ne sort de la page : la CSP de la démo (`connect-src 'self'`) n'autorise
que le site lui-même, et `demo.js` refuse toute requête vers un autre serveur.
Vérifié le 18/11/2026 dans Edge : 47 onglets ouverts, aucune requête sortante.

## Fabriquer la démo

```
python build/demo/fabriquer_demo.py ..\pilote-appli.github.io\demo
```

Le script copie `src/` dans un dossier temporaire, y écrit Brice
(`src/donnees_exemple.py`), démarre le vrai serveur de cette copie, ouvre
l'interface dans Edge (Playwright, `channel="msedge"`) et passe sur chaque
onglet de la barre latérale, puis sur les indices de comparaison de la courbe.
Les vraies données ne sont jamais lues. Il écrit `index.html`, `demo.js`,
`demo-donnees.js` et `vendor/` dans le dossier donné.

* **Anonymisation** : `/data` rend des chemins du PC dans son `_debug` (ils
  portent le nom de la session Windows). `anonymiser()` les remplace par
  `C:\Users\Brice\…` et **arrête tout** si le nom de session reste quelque
  part : la démo va sur un site public.
* Les cours et les courbes sont ceux du jour de la fabrication, et les dates de
  Brice sont relatives à ce jour : la démo se refait à chaque version, **toute
  seule** (ci-dessous). Sans aucun cours lu (Yahoo qui ne répond pas), le
  script s'arrête (`verifier_cours`) : l'ancienne démo reste en ligne.
* `demo/version.txt` : la version de Pilote dont vient la démo.

## Refaite toute seule à chaque version

Le workflow `.github/workflows/demo.yml` **du site** (pas de Pilote) tourne
toutes les deux heures : il lit la dernière release de Pilote et, si
`demo/version.txt` est en retard, refait la démo sur un Windows de GitHub
(Edge y est installé) et la commite. Le code de l'app vient du tag de la
release ; le script, de `main` (ses corrections servent aussi aux versions
déjà publiées). Choisi ainsi pour n'avoir aucune clé à créer : Pilote est
public, et le site ne s'écrit qu'avec son propre jeton. Le bouton « Run
workflow » de l'onglet Actions du site la refait tout de suite.

Une nouvelle version apparaît donc dans la démo au plus deux heures après sa
release. GitHub met en pause un workflow planifié après 60 jours sans commit
dans le dépôt : sans version pendant deux mois, le réactiver dans l'onglet
Actions du site.
* Un nouvel appel au pont qui ne fait que lire : l'ajouter à `LECTURES` dans
  `demo.js`, sinon la démo répond « dans l'app ». Une lecture qui révélerait
  quelque chose du PC (clés USB, chemins) n'y va pas.

## Sur le site

`index.html` (section `#essayer`), `assets/demo.js` et le bloc « Démo de
l'accueil » de `assets/style.css`. La page est affichée à 1366 × 740 puis
réduite pour tenir dans le cadre (0,93 sur un écran de 1366 px). Sous 760 px
de large, ou sans JS, la démo ne se charge pas : la capture de l'accueil et
« L'ouvrir quand même » la remplacent. « Installer Pilote » dans la démo
envoie un message à la page (`postMessage`, même origine), qui descend
jusqu'aux boutons.
