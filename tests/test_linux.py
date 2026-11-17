"""Version Linux (docs/linux.md) : trousseau, cles USB, dossier de donnees
(`python -m unittest discover -s tests`).

Tourne sous Windows comme sous Linux : les appels au systeme (secret-tool,
lsblk) sont remplaces par des imitations. Le test du paquet sur de vraies
machines Linux est dans .github/workflows/build-linux.yml.

Rien n'est ecrit dans `Donnees/` : un dossier temporaire seulement.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

import chiffrement  # noqa: E402
import plateforme  # noqa: E402
import sauvegarde  # noqa: E402


def _module_neuf(nom):
    """Une copie neuve d'un module de src/ : d'autres tests en remplacent des
    fonctions pour de bon (test_agenda, test_garmin et test_coros imitent
    actus._chiffrer hors Windows ; test_agenda et test_donnees,
    storage.get_app_dir)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(nom + "_essai_linux", str(RACINE / "src" / (nom + ".py")))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FauxTrousseau:
    """Imite secret-tool : store lit le code sur l'entree standard."""

    def __init__(self):
        self.elements = {}
        self.appels = []

    def __call__(self, cmd, input=None, **kw):
        self.appels.append((list(cmd), input))
        if cmd[0] != "secret-tool":
            raise AssertionError("commande inattendue : %s" % cmd)
        action, args = cmd[1], cmd[2:]
        attributs = tuple(a for a in args if not a.startswith("--label="))
        if action == "store":
            self.elements[attributs] = input
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if action == "lookup":
            if attributs in self.elements:
                return subprocess.CompletedProcess(cmd, 0, self.elements[attributs] + "\n", "")
            return subprocess.CompletedProcess(cmd, 1, "", "")
        if action == "clear":
            self.elements.pop(attributs, None)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(action)


class TrousseauLinux(unittest.TestCase):
    def setUp(self):
        self.faux = FauxTrousseau()
        actus = self.actus = _module_neuf("actus")
        for p in (mock.patch.object(sys, "platform", "linux"),
                  mock.patch.dict(sys.modules, {"actus": actus}),   # chiffrement.py : import actus
                  mock.patch.object(actus.subprocess, "run", self.faux),
                  mock.patch.object(actus, "_compte_trousseau", return_value="pilote-essai"),
                  mock.patch.object(chiffrement, "_compte_mac", return_value="pilote-sauvegarde-essai")):
            p.start()
            self.addCleanup(p.stop)

    def test_code_range_et_relu(self):
        s = self.actus._chiffrer("abcd efgh ijkl mnop", "Pilote Garmin", "Pilote : essai")
        self.assertEqual(s, "secret:pilote-essai")
        self.assertNotIn("abcd", s)               # rien du code dans le fichier
        self.assertEqual(self.actus._dechiffrer(s, "Pilote Garmin"), "abcd efgh ijkl mnop")

    def test_code_jamais_en_argument(self):
        self.actus._chiffrer("abcd efgh ijkl mnop")
        cmd, entree = self.faux.appels[0]
        self.assertEqual(entree, "abcd efgh ijkl mnop")
        self.assertFalse(any("abcd" in a for a in cmd))

    def test_un_element_par_service(self):
        a = self.actus._chiffrer("code gmail")
        b = self.actus._chiffrer("code icloud", "Pilote Agenda", "Pilote : iCloud")
        self.assertEqual(self.actus._dechiffrer(a), "code gmail")
        self.assertEqual(self.actus._dechiffrer(b, "Pilote Agenda"), "code icloud")

    def test_oubli_a_la_deconnexion(self):
        s = self.actus._chiffrer("abcd")
        self.actus._oublier(s)
        with self.assertRaises(ValueError):
            self.actus._dechiffrer(s)

    def test_sans_secret_tool_refus_clair(self):
        def absent(*a, **kw):
            raise FileNotFoundError("secret-tool")
        with mock.patch.object(self.actus.subprocess, "run", absent):
            with self.assertRaises(OSError) as e:
                self.actus._chiffrer("abcd")
        self.assertIn("gnome-keyring", str(e.exception))

    def test_trousseau_qui_refuse(self):
        refus = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Cannot create an item")
        with mock.patch.object(self.actus.subprocess, "run", refus):
            with self.assertRaises(OSError):
                self.actus._chiffrer("abcd")

    def test_cle_des_sauvegardes(self):
        cle = os.urandom(32)
        s = chiffrement.garder_cle(cle)
        self.assertEqual(s, "secret:pilote-sauvegarde-essai")
        self.assertEqual(chiffrement.relire_cle(s), cle)
        chiffrement.oublier_cle(s)
        self.assertEqual(self.faux.elements, {})


class ClesUsbLinux(unittest.TestCase):
    ARBRE = {"blockdevices": [
        {"name": "nvme0n1", "mountpoint": None, "rm": False, "hotplug": False, "tran": "nvme",
         "children": [
             {"name": "nvme0n1p1", "mountpoint": "/boot/efi", "rm": False, "hotplug": False},
             {"name": "nvme0n1p2", "mountpoint": "/", "rm": False, "hotplug": False}]},
        # Ancien lsblk : RM et HOTPLUG en "0"/"1", TRAN sur le disque seulement
        {"name": "sdb", "mountpoint": None, "rm": "1", "hotplug": "1", "tran": "usb",
         "children": [{"name": "sdb1", "mountpoint": "/media/brice/CLE", "label": "CLE",
                       "uuid": "1234-ABCD", "fstype": "vfat", "rm": "1", "hotplug": "1"}]},
        {"name": "sdc", "mountpoint": None, "rm": False, "hotplug": False, "tran": "usb",
         "children": [{"name": "sdc1", "mountpoint": "/media/brice/DISQUE", "label": None,
                       "uuid": "u-2", "fstype": "ext4"}]},
        {"name": "loop3", "mountpoint": "/snap/core/1", "rm": False, "hotplug": False},
    ]}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pilote_linux_")
        sortie = json.dumps(self.ARBRE)
        for p in (mock.patch.object(sauvegarde, "_disk_space", return_value=(10, 100)),
                  mock.patch.object(sauvegarde, "_CHROMEOS_AMOVIBLES", os.path.join(self.tmp, "removable")),
                  mock.patch("subprocess.run",
                             lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, sortie, ""))):
            p.start()
            self.addCleanup(p.stop)

    def test_cles_et_disques_externes_seulement(self):
        cles = sauvegarde._linux_cles()
        self.assertEqual([c["root"] for c in cles], ["/media/brice/CLE", "/media/brice/DISQUE"])
        self.assertEqual(cles[0]["serial"], "1234-ABCD")
        self.assertEqual(cles[0]["device"], "/dev/sdb1")
        self.assertEqual(cles[1]["label"], "DISQUE")     # sans nom : celui du point de montage

    def test_cle_partagee_par_chromeos(self):
        os.makedirs(os.path.join(self.tmp, "removable", "MA CLE"))
        cles = sauvegarde._linux_cles()
        chromebook = [c for c in cles if c["label"] == "MA CLE"]
        self.assertEqual(len(chromebook), 1)
        self.assertEqual(chromebook[0]["serial"], "")    # suivie par son nom

    def test_ejection_refusee_sur_chromebook(self):
        r = sauvegarde.ejecter(os.path.join(sauvegarde._CHROMEOS_AMOVIBLES, "MA CLE"))
        if sys.platform.startswith("linux"):
            self.assertFalse(r["ok"])
            self.assertIn("ChromeOS", r["error"])

    def test_lsblk_illisible(self):
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("lsblk")):
            self.assertEqual(sauvegarde._lsblk(), [])


class MiseAJourLinux(unittest.TestCase):
    """updater._installer_linux, sans reseau ni apt : sudo, pkexec, ou repli."""

    class _Reponse:
        def __init__(self, donnees):
            self.donnees, self.headers = donnees, {"Content-Length": str(len(donnees))}

        def read(self, n):
            morceau, self.donnees = self.donnees[:n], self.donnees[n:]
            return morceau

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def setUp(self):
        import updater
        self.updater = updater
        self.tmp = Path(tempfile.mkdtemp(prefix="pilote_maj_linux_"))
        self.commandes = []
        self.codes = {}                       # premier mot -> code de retour
        lances = self.lances = []

        def run(cmd, **kw):
            self.commandes.append(list(cmd))
            if cmd[0] == "dpkg-deb":
                return subprocess.CompletedProcess(cmd, 0, "Package: pilote\nVersion: 9.9.9\n", "")
            if cmd[0] == "xdg-user-dir":
                return subprocess.CompletedProcess(cmd, 0, str(self.tmp) + "\n", "")
            return subprocess.CompletedProcess(cmd, self.codes.get(cmd[0], 1), "", "refus")

        for p in (mock.patch.object(plateforme, "paquet_linux", return_value=True),
                  mock.patch.object(updater.urllib.request, "urlopen",
                                    lambda req, timeout=0: self._Reponse(b"x" * 300000)),
                  mock.patch.object(updater.subprocess, "run", run),
                  mock.patch.object(updater.subprocess, "Popen", lambda cmd, **kw: lances.append(cmd)),
                  mock.patch("shutil.which", lambda n: "/usr/bin/" + n),
                  mock.patch.object(updater, "_log", lambda m: None),
                  mock.patch.object(updater, "_log_path", lambda: self.tmp / "update.log"),
                  mock.patch("time.sleep", lambda s: None)):
            p.start()
            self.addCleanup(p.stop)
        updater._attendu.clear()

    def test_sudo_sans_mot_de_passe_puis_relance(self):
        self.codes["sudo"] = 0
        self.updater._installer_linux("https://github.com/x/Pilote_Linux.deb", "9.9.9")
        self.assertEqual(self.updater.get_progress()["step"], "launching")
        apt = [c for c in self.commandes if c[0] == "sudo"][0]
        self.assertEqual(apt[:4], ["sudo", "-n", "apt-get", "install"])
        self.assertFalse(any(c[0] == "pkexec" for c in self.commandes))
        self.assertEqual(self.lances[0][0], "/bin/sh")          # script de relance

    def test_pkexec_si_sudo_demande_un_mot_de_passe(self):
        self.codes["pkexec"] = 0
        self.updater._installer_linux("https://github.com/x/Pilote_Linux.deb", "9.9.9")
        self.assertEqual(self.updater.get_progress()["step"], "launching")
        self.assertTrue(any(c[0] == "pkexec" for c in self.commandes))

    def test_repli_dans_telechargements(self):
        self.updater._installer_linux("https://github.com/x/Pilote_Linux.deb", "9.9.9")
        p = self.updater.get_progress()
        self.assertEqual(p["step"], "error")
        self.assertIn("double-clique", p["error"])
        self.assertTrue((self.tmp / "Pilote_Linux.deb").is_file())
        self.assertEqual(self.lances[0][0], "xdg-open")

    def test_mauvaise_version_refusee(self):
        self.codes["sudo"] = 0
        self.updater._installer_linux("https://github.com/x/Pilote_Linux.deb", "9.9.8")
        self.assertEqual(self.updater.get_progress()["step"], "error")
        self.assertFalse(any(c[0] == "sudo" for c in self.commandes))


class DossierDeDonnees(unittest.TestCase):
    def test_paquet_dans_le_dossier_personnel(self):
        tmp = tempfile.mkdtemp(prefix="pilote_xdg_")
        storage = _module_neuf("storage")
        with mock.patch.object(plateforme, "paquet_linux", return_value=True), \
             mock.patch.object(plateforme, "version_store", return_value=False), \
             mock.patch.object(sys, "platform", "linux"), \
             mock.patch.dict(os.environ, {"XDG_DATA_HOME": tmp}):
            self.assertEqual(storage.get_app_dir(), Path(tmp) / "Pilote" / "Donnees")
            self.assertEqual(storage.scan_orphan_data(), [])

    def test_hors_linux_pas_de_paquet(self):
        if not sys.platform.startswith("linux"):
            self.assertFalse(plateforme.paquet_linux())

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux seulement")
    def test_depot_clone_pas_un_paquet(self):
        self.assertFalse(plateforme.paquet_linux())


if __name__ == "__main__":
    unittest.main()
