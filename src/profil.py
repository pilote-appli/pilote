"""
profil.py — Exporter tout un utilisateur dans un fichier, et l'importer.

Jusqu'au 25/11/2026, « Exporter » et « Importer » (Parametres, Donnees) ne
portaient que pea_data.json : les comptes, le sport, la sante, le patrimoine...
restaient sur le PC. Ici, tout l'utilisateur actif part dans un seul fichier :

  * un zip, avec un temoin `profil-pilote.json` (nom, emoji, couleur, version) ;
  * les fichiers de modules seulement (FICHIERS), sans backups, sans le cache
    des cours (`_cache` du PEA, regenerable) et SANS le code PIN : un fichier
    perdu ne doit pas arriver verrouille par un code connu d'un autre ;
  * chiffre par mot de passe si on en donne un (chiffrement.py, le meme que les
    sauvegardes) : extension .pilote, sinon .zip.

A l'import, deux choix : un nouvel utilisateur (rien d'existant n'est touche),
ou remplacer l'utilisateur actif (une archive de securite de son etat est
ecrite avant, dans backups/avant_import/). Les codes d'Actus, d'iCloud, de
Garmin et de Coros sont chiffres pour CE PC (Windows ou trousseau) : venus
d'un autre ordinateur, il faut se reconnecter. Detail : docs/parametres.md.
"""
from __future__ import annotations

import datetime
import io
import json
import tempfile
import zipfile
from pathlib import Path

import chiffrement
import donnees
import storage

TEMOIN = "profil-pilote.json"
EXT_ZIP = ".zip"
EXT_CHIFFRE = ".pilote"

# Un fichier par module (le nom de chaque JsonStore, plus le PEA et Mes
# comptes). Un nouveau module doit s'ajouter ici : tests/test_profil.py le
# verifie.
FICHIERS = (
    "pea_data.json", "finances.json", "cto.json", "sports.json", "pret.json",
    "sante.json", "patrimoine.json", "taches.json", "actus.json",
    "agenda.json", "garmin.json", "coros.json",
)

_TAILLE_MAX = 200 * 1024 * 1024   # garde-fou a la lecture d'un fichier choisi


def nom_fichier(label: str, chiffre: bool) -> str:
    import re
    propre = re.sub(r"[^\w-]+", "-", label or "", flags=re.UNICODE).strip("-") or "profil"
    jour = datetime.date.today().isoformat()
    return f"Pilote-profil-{propre[:40]}-{jour}" + (EXT_CHIFFRE if chiffre else EXT_ZIP)


def _zip_utilisateur(slug: str, version: str) -> bytes:
    """Le zip en memoire (quelques centaines de Ko : sans backups ni cache)."""
    dossier = storage.get_user_dir(slug)
    u = next((x for x in storage.get_users_state()["users"] if x["slug"] == slug), {})
    buf = io.BytesIO()
    n = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for nom in FICHIERS:
            p = dossier / nom
            if not p.is_file():
                continue
            data = donnees.lire_json(p)        # illisible : l'export s'arrete
            if nom == storage.DATA_FILE and isinstance(data, dict):
                data = {k: v for k, v in data.items() if k != "_cache"}
            z.writestr(nom, json.dumps(data, ensure_ascii=False, indent=1))
            n += 1
        z.writestr(TEMOIN, json.dumps({
            "v": 1, "label": u.get("label") or slug, "emoji": u.get("emoji") or "",
            "color": u.get("color") or "", "version": version,
            "date": datetime.datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False))
    if not n:
        raise ValueError("cet utilisateur n'a encore aucune donnee")
    return buf.getvalue()


def exporter(cible: str, version: str, mdp: str = None) -> dict:
    """Ecrit le profil de l'utilisateur actif dans `cible`."""
    slug = storage.get_users_state()["active"]
    brut = _zip_utilisateur(slug, version)
    cible = Path(cible)
    tmp = cible.with_name(cible.name + ".part")
    try:
        with open(tmp, "wb") as out:
            if mdp:
                sel = chiffrement.nouveau_sel()
                cle = chiffrement.deriver(mdp, sel)
                chiffrement.chiffrer_flux(io.BytesIO(brut), out, cle, sel)
            else:
                out.write(brut)
        tmp.replace(cible)
    finally:
        if tmp.exists():
            tmp.unlink()
    return {"ok": True, "path": str(cible)}


def _ouvrir(chemin: str, mdp: str = None) -> zipfile.ZipFile:
    """Le zip du profil, dechiffre en memoire s'il le faut. Leve ValueError
    avec un message lisible ; « mot_de_passe » en tete si on doit le demander."""
    p = Path(chemin)
    if not p.is_file():
        raise ValueError("Fichier introuvable.")
    if p.stat().st_size > _TAILLE_MAX:
        raise ValueError("Fichier trop lourd pour un profil de Pilote.")
    entete = chiffrement.lire_entete(p)
    if entete:
        if not mdp:
            raise ValueError("mot_de_passe:Ce fichier est protégé : tape son mot de passe.")
        try:
            cle = chiffrement.deriver(mdp, bytes.fromhex(entete["sel"]), int(entete["iter"]))
        except Exception:
            raise ValueError("En-tête du fichier illisible.")
        with tempfile.TemporaryFile() as clair:
            try:
                chiffrement.dechiffrer_flux(p, clair, cle)
            except chiffrement.MotDePasseIncorrect:
                raise ValueError("mot_de_passe:Mot de passe incorrect (ou fichier abîmé).")
            clair.seek(0)
            source = io.BytesIO(clair.read())   # un profil pese quelques centaines de Ko
    else:
        source = str(p)
    try:
        z = zipfile.ZipFile(source)
    except zipfile.BadZipFile:
        raise ValueError("Ce fichier n'est pas un profil exporté par Pilote.")
    if TEMOIN not in z.namelist():
        raise ValueError("Ce fichier n'est pas un profil exporté par Pilote "
                         "(une sauvegarde complète se restaure dans Paramètres, Sauvegarde).")
    return z


def lire(chemin: str, mdp: str = None) -> dict:
    """Contenu valide du profil : {temoin, fichiers: {nom: donnees}}. Rien
    n'est ecrit. Seuls les noms de FICHIERS sont pris (ni chemin, ni autre
    fichier : pas de zip-slip possible)."""
    z = _ouvrir(chemin, mdp)
    with z:
        try:
            temoin = json.loads(z.read(TEMOIN).decode("utf-8"))
        except Exception:
            raise ValueError("Profil abîmé (témoin illisible).")
        fichiers = {}
        for nom in FICHIERS:
            if nom not in z.namelist():
                continue
            try:
                data = json.loads(z.read(nom).decode("utf-8"))
            except Exception:
                raise ValueError(f"Profil abîmé : {nom} illisible.")
            if not isinstance(data, dict):
                raise ValueError(f"Profil abîmé : {nom} inattendu.")
            fichiers[nom] = data
    if not fichiers:
        raise ValueError("Ce profil ne contient aucune donnée.")
    if storage.DATA_FILE in fichiers:
        pea = fichiers[storage.DATA_FILE]
        if not all(k in pea for k in ("positions", "transactions", "depots")):
            raise ValueError("Profil abîmé : le PEA est incomplet.")
    return {"temoin": temoin if isinstance(temoin, dict) else {}, "fichiers": fichiers}


def apercu(chemin: str, mdp: str = None) -> dict:
    """Ce que la page montre avant de choisir : nom et modules presents."""
    if chiffrement.lire_entete(chemin) and not mdp:
        return {"ok": True, "chiffre": True}
    p = lire(chemin, mdp)
    t = p["temoin"]
    return {"ok": True, "chiffre": bool(mdp), "label": str(t.get("label") or "Profil")[:60],
            "emoji": str(t.get("emoji") or "")[:8], "version": str(t.get("version") or ""),
            "date": str(t.get("date") or "")[:10], "fichiers": sorted(p["fichiers"])}


def _archive_de_securite(slug: str) -> Path:
    dossier = storage.get_user_dir(slug)
    sec = dossier / storage.BACKUP_DIR / "avant_import"
    sec.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    cible = sec / f"profil_avant_import_{ts}.zip"
    with zipfile.ZipFile(cible, "w", zipfile.ZIP_DEFLATED) as z:
        for nom in FICHIERS:
            if (dossier / nom).is_file():
                z.write(dossier / nom, nom)
    return cible


def importer(chemin: str, mode: str, mdp: str = None) -> dict:
    """mode « nouveau » : un nouvel utilisateur, qui devient l'actif.
    mode « remplacer » : l'utilisateur actif prend le contenu du profil ; ses
    fichiers de modules absents du profil sont retires (ils restent dans
    l'archive de securite). Son nom et son code PIN ne changent pas."""
    if mode not in ("nouveau", "remplacer"):
        raise ValueError("mode inconnu")
    p = lire(chemin, mdp)                     # tout est valide avant d'ecrire
    t = p["temoin"]
    state = storage.get_users_state()
    securite = None
    if mode == "nouveau":
        label = str(t.get("label") or "Profil importé").strip()[:60] or "Profil importé"
        slug = storage.slugify(label, [u["slug"] for u in state["users"]])
        dossier = storage.get_user_dir(slug)   # neuf : slugify ecarte les dossiers existants
    else:
        slug = state["active"]
        dossier = storage.get_user_dir(slug)
        securite = _archive_de_securite(slug)
    for nom, data in p["fichiers"].items():
        donnees.ecrire_json(dossier / nom, data, prefixe=Path(nom).stem)
    if mode == "remplacer":
        for nom in FICHIERS:
            if nom not in p["fichiers"] and (dossier / nom).is_file():
                (dossier / nom).unlink()
    else:
        state["users"].append({"slug": slug, "label": label,
                               "emoji": str(t.get("emoji") or "")[:8],
                               "color": str(t.get("color") or "")[:32]})
        state["active"] = slug
        storage.save_users_state(state)
    return {"ok": True, "slug": slug, "mode": mode,
            "securite": str(securite) if securite else "",
            "fichiers": sorted(p["fichiers"])}
