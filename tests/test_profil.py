"""Exporter / importer tout un utilisateur (src/profil.py,
`python -m unittest discover tests`).

Toutes les écritures vont dans un dossier temporaire : `storage.get_app_dir`
est remplacé le temps de chaque test, jamais `Donnees/` (lien vers les vraies
données sur le PC d'Arthur). Données fictives de Brice.
"""
import importlib
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

import storage  # noqa: E402
import profil  # noqa: E402

_TMP = Path(tempfile.mkdtemp(prefix="pilote_profil_"))
_DONNEES = _TMP / "Donnees"


def _ecrire(chemin, obj):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(obj), encoding="utf-8")


def _lire(chemin):
    return json.loads(chemin.read_text(encoding="utf-8"))


class Profil(unittest.TestCase):
    def setUp(self):
        self._get_app_dir = storage.get_app_dir
        storage.get_app_dir = lambda: _DONNEES          # jamais les vraies données
        self.addCleanup(setattr, storage, "get_app_dir", self._get_app_dir)
        shutil.rmtree(_TMP, ignore_errors=True)
        _DONNEES.mkdir(parents=True)
        _ecrire(_DONNEES / "users.json", {"active": "brice", "users": [
            {"slug": "brice", "label": "Brice", "emoji": "", "color": "#c026d3"},
            {"slug": "lea", "label": "Léa", "emoji": "", "color": ""}]})
        b = _DONNEES / "users" / "brice"
        _ecrire(b / "pea_data.json", {"positions": [{"t": "WPEA.PA"}], "transactions": [],
                                      "depots": [], "_cache": {"gros": "x" * 1000}})
        _ecrire(b / "finances.json", {"transactions": [{"label": "Boulangerie"}]})
        _ecrire(b / "sante.json", {"pesees": [72]})
        _ecrire(b / "actus.json", {"adresse": "brice@example.com", "code": "chiffre"})
        _ecrire(b / "backups" / "pea_data_2026-11-24.json", {"positions": []})
        (b / "pin.hash").write_text("hash-du-pin", encoding="utf-8")
        _ecrire(_DONNEES / "users" / "lea" / "pea_data.json",
                {"positions": [], "transactions": [], "depots": []})
        _ecrire(_DONNEES / "users" / "lea" / "sports.json", {"seances": [1]})
        self.fichier = _TMP / "export.zip"

    def test_chaque_module_est_exporte(self):
        """Un nouveau JsonStore oublié dans FICHIERS ne partirait pas."""
        for nom in ("actus", "agenda", "coros", "cto", "garmin", "patrimoine",
                    "pret", "sante", "sports", "taches"):
            mod = importlib.import_module(nom)
            self.assertIn(mod._store.filename, profil.FICHIERS, nom)
        self.assertIn("finances.json", profil.FICHIERS)
        self.assertIn(storage.DATA_FILE, profil.FICHIERS)

    def test_export_sans_pin_ni_backups_ni_cache(self):
        profil.exporter(str(self.fichier), "4.4.86")
        with zipfile.ZipFile(self.fichier) as z:
            noms = set(z.namelist())
            pea = json.loads(z.read("pea_data.json"))
            temoin = json.loads(z.read(profil.TEMOIN))
        self.assertEqual(noms, {"pea_data.json", "finances.json", "sante.json",
                                "actus.json", profil.TEMOIN})
        self.assertNotIn("_cache", pea)
        self.assertEqual(temoin["label"], "Brice")
        self.assertEqual(temoin["color"], "#c026d3")
        self.assertFalse(list(_TMP.glob("*.part")))

    def test_nouvel_utilisateur(self):
        profil.exporter(str(self.fichier), "4.4.86")
        r = profil.importer(str(self.fichier), "nouveau")
        self.assertEqual(r["slug"], "brice_2")          # jamais le dossier existant
        st = _lire(_DONNEES / "users.json")
        self.assertEqual(st["active"], "brice_2")
        self.assertEqual([u["label"] for u in st["users"]], ["Brice", "Léa", "Brice"])
        neuf = _DONNEES / "users" / "brice_2"
        self.assertEqual(_lire(neuf / "sante.json"), {"pesees": [72]})
        self.assertFalse((neuf / "pin.hash").exists())
        # L'original n'a pas bougé
        self.assertIn("_cache", _lire(_DONNEES / "users" / "brice" / "pea_data.json"))

    def test_remplacer_garde_nom_pin_et_archive(self):
        profil.exporter(str(self.fichier), "4.4.86")
        st = _lire(_DONNEES / "users.json")
        st["active"] = "lea"
        _ecrire(_DONNEES / "users.json", st)
        lea = _DONNEES / "users" / "lea"
        (lea / "pin.hash").write_text("pin-de-lea", encoding="utf-8")
        r = profil.importer(str(self.fichier), "remplacer")
        self.assertEqual(r["slug"], "lea")
        self.assertEqual(_lire(lea / "finances.json"), {"transactions": [{"label": "Boulangerie"}]})
        self.assertFalse((lea / "sports.json").exists())     # absent du profil
        self.assertEqual((lea / "pin.hash").read_text(encoding="utf-8"), "pin-de-lea")
        self.assertEqual(len(_lire(_DONNEES / "users.json")["users"]), 2)
        with zipfile.ZipFile(r["securite"]) as z:          # l'ancien état est gardé
            self.assertEqual(json.loads(z.read("sports.json")), {"seances": [1]})

    def test_mot_de_passe(self):
        chiffre = _TMP / "export.pilote"
        profil.exporter(str(chiffre), "4.4.86", "secret de Brice")
        self.assertFalse(zipfile.is_zipfile(chiffre))
        self.assertEqual(profil.apercu(str(chiffre)), {"ok": True, "chiffre": True})
        with self.assertRaises(ValueError) as e:
            profil.importer(str(chiffre), "nouveau", "mauvais")
        self.assertTrue(str(e.exception).startswith("mot_de_passe:"))
        ap = profil.apercu(str(chiffre), "secret de Brice")
        self.assertEqual(ap["label"], "Brice")
        self.assertIn("sante.json", ap["fichiers"])
        r = profil.importer(str(chiffre), "nouveau", "secret de Brice")
        self.assertTrue((_DONNEES / "users" / r["slug"] / "sante.json").exists())

    def test_fichiers_refuses_sans_rien_ecrire(self):
        avant = (_DONNEES / "users.json").read_bytes()
        # Une sauvegarde complète (pas de témoin), un zip qui tente de sortir
        # du dossier, un PEA incomplet, un fichier qui n'est pas un zip
        cas = {}
        cas["sauvegarde"] = {"users.json": "{}"}
        cas["evasion"] = {profil.TEMOIN: "{}", "../../x.json": "{}"}
        cas["pea"] = {profil.TEMOIN: "{}", "pea_data.json": '{"positions": []}'}
        for nom, contenu in cas.items():
            p = _TMP / (nom + ".zip")
            with zipfile.ZipFile(p, "w") as z:
                for k, v in contenu.items():
                    z.writestr(k, v)
            with self.assertRaises(ValueError, msg=nom):
                profil.importer(str(p), "nouveau")
        texte = _TMP / "texte.zip"
        texte.write_text("pas un zip", encoding="utf-8")
        with self.assertRaises(ValueError):
            profil.importer(str(texte), "remplacer")
        self.assertEqual((_DONNEES / "users.json").read_bytes(), avant)
        self.assertFalse((_TMP / "x.json").exists())
        self.assertEqual(sorted(d.name for d in (_DONNEES / "users").iterdir()), ["brice", "lea"])


if __name__ == "__main__":
    unittest.main()
