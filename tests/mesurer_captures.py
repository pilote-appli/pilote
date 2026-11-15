"""
mesurer_captures.py — Mesure de budget_captures.py sur un dossier de captures
dont on connaît la bonne réponse (verite.json : corpus_captures.py, ou captures
réelles annotées à la main).

    python tests/mesurer_captures.py <dossier> [--erreurs] [--seul cap_0001.png [--lignes]]

Compte, pour chaque opération attendue : trouvée (montant et sens exacts),
date exacte, libellé reconnaissable ; et les opérations inventées (une ligne
lue qui n'est pas une opération : solde, total, compte). Les lectures de
l'OCR sont gardées dans <dossier>/_ocr/ : une seconde mesure ne relit rien.
"""
import datetime
import hashlib
import json
import os
import re
import sys
import unicodedata

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ICI, "..", "src"))
import budget_captures  # noqa: E402
import sante  # noqa: E402


def _norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def libelle_ok(lu, attendu):
    a, b = _norm(lu), _norm(attendu)
    if not a:
        return False
    if a == b or b.startswith(a.rstrip(" .")) and len(a) >= min(8, len(b)):
        return True
    ta, tb = set(a.split()), set(b.split())
    return len(ta & tb) / max(1, len(ta | tb)) >= 0.6


def _cache_ocr(dossier):
    cache = os.path.join(dossier, "_ocr")
    os.makedirs(cache, exist_ok=True)
    vrai = sante._run_ocr

    def run(path, timeout=90):
        h = hashlib.sha1(open(path, "rb").read()).hexdigest()[:20]
        f = os.path.join(cache, h + ".json")
        if os.path.exists(f):
            return json.load(open(f, encoding="utf-8"))
        r = vrai(path, timeout)
        if r.get("ok"):
            json.dump(r, open(f, "w", encoding="utf-8"))
        return r
    sante._run_ocr = run


def mesurer(dossier, erreurs=False, seul=None):
    v = json.load(open(os.path.join(dossier, "verite.json"), encoding="utf-8"))
    ref = datetime.date.fromisoformat(v.get("ref", "2026-11-14"))
    _cache_ocr(dossier)
    tot = dict(attendues=0, trouvees=0, dates=0, libelles=0, inventees=0, ecrans=0, ecrans_vides_ok=0,
               ecrans_vides=0, ecrans_parfaits=0, sens=0)
    with budget_captures.SessionOcr():
        for nom, cap in sorted(v["captures"].items()):
            if seul and nom != seul:
                continue
            chemin = os.path.join(dossier, nom)
            if not os.path.exists(chemin):
                continue
            r = budget_captures.lire_image(open(chemin, "rb").read(), datetime.date.fromisoformat(
                cap.get("ref", ref.isoformat())))
            lus = r.get("operations", []) if r.get("ok") else []
            att = cap["operations"]
            if not att:
                tot["ecrans_vides"] += 1
                tot["ecrans_vides_ok"] += not lus
                tot["inventees"] += len(lus)
                if lus and erreurs:
                    print("%s : écran sans opération, %d lues : %s" % (nom, len(lus), [
                        (o["brut"], o["montantSigne"]) for o in lus][:4]))
                continue
            tot["ecrans"] += 1
            restants = list(lus)
            parfait = True
            msgs = []
            for a in att:
                tot["attendues"] += 1
                cand = [o for o in restants if abs(abs(o["montantSigne"]) - abs(a["montant"])) < 0.005]
                cand.sort(key=lambda o: (not libelle_ok(o["brut"], a["libelle"]), o["date"] != a["date"]))
                if not cand:
                    parfait = False
                    msgs.append("  manquée : %s %s %s" % (a["date"], a["montant"], a["libelle"]))
                    continue
                o = cand[0]
                restants.remove(o)
                bon_sens = (o["montantSigne"] > 0) == (a["montant"] > 0)
                tot["sens"] += bon_sens
                tot["trouvees"] += bon_sens
                tot["dates"] += o["date"] == a["date"]
                tot["libelles"] += libelle_ok(o["brut"], a["libelle"])
                if not (bon_sens and o["date"] == a["date"] and libelle_ok(o["brut"], a["libelle"])):
                    parfait = False
                    msgs.append("  %s%s%s : lu %s %s « %s » / attendu %s %s « %s »" % (
                        "" if bon_sens else "SENS ", "" if o["date"] == a["date"] else "DATE ",
                        "" if libelle_ok(o["brut"], a["libelle"]) else "LIBELLE ", o["date"], o["montantSigne"],
                        o["brut"], a["date"], a["montant"], a["libelle"]))
            for o in restants:
                parfait = False
                tot["inventees"] += 1
                msgs.append("  inventée : %s %s « %s »" % (o["date"], o["montantSigne"], o["brut"]))
            tot["ecrans_parfaits"] += parfait
            if erreurs and msgs:
                print(nom + (" (" + r.get("erreur", "") + ")" if not r.get("ok") else ""))
                print("\n".join(msgs))
    a = max(1, tot["attendues"])
    print("Captures avec opérations : %d, parfaites : %d (%.1f %%)" % (
        tot["ecrans"], tot["ecrans_parfaits"], 100.0 * tot["ecrans_parfaits"] / max(1, tot["ecrans"])))
    print("Opérations attendues : %d" % tot["attendues"])
    print("  trouvées (montant et sens exacts) : %.1f %%" % (100.0 * tot["trouvees"] / a))
    print("  date exacte : %.1f %%" % (100.0 * tot["dates"] / a))
    print("  libellé reconnaissable : %.1f %%" % (100.0 * tot["libelles"] / a))
    print("Opérations inventées : %d" % tot["inventees"])
    print("Écrans sans opération (comptes, totaux) laissés vides : %d / %d" % (
        tot["ecrans_vides_ok"], tot["ecrans_vides"]))
    return tot


if __name__ == "__main__":
    args = sys.argv[1:]
    seul = args[args.index("--seul") + 1] if "--seul" in args else None
    if "--lignes" in args:
        vrai_op = budget_captures.operations

        def op(ocr, ref, couleur=None):
            for l in budget_captures._lignes(ocr.get("words", [])):
                print("  %4d %4d %4d %4d h%-3d %-28s %s" % (l.x0, l.x1, l.y0, l.y1, l.h, budget_captures.lire_montant(
                    l.texte), l.texte))
            r = vrai_op(ocr, ref, couleur)
            print("  ->", r["ignorees"], r["raison"])
            return r
        budget_captures.operations = op
    mesurer(args[0], "--erreurs" in args, seul)
