"""
corpus_captures.py — Captures d'écran fictives d'applis bancaires, avec leur
bonne réponse, pour entraîner et mesurer budget_captures.py.

Chaque capture est une page HTML à la manière d'une appli de banque (liste des
opérations : en-têtes de date, libellé, sous-titre, montant à droite ; mode
clair ou sombre ; solde en tête, barre du bas…), photographiée par Chrome sans
fenêtre à la taille d'un téléphone. Les mises en page reprennent ce que
montrent les captures publiées sur l'App Store et Google Play (BoursoBank,
Revolut, N26, Fortuneo, Crédit Agricole, Lydia…), sans en copier aucune :
couleurs, polices et marchands sont tirés au hasard, aucune marque n'apparaît.

    python tests/corpus_captures.py <dossier> [n] [graine]

écrit <dossier>/cap_0001.png … et <dossier>/verite.json. Les images ne vont
pas dans le dépôt (lourdes) : le dossier se régénère à l'identique.
"""
import datetime
import html
import json
import os
import random
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import corpus_budget as cb  # noqa: E402

REF = datetime.date(2026, 11, 14)
CHROME = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
          r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
POLICES = ["Segoe UI", "Arial", "Helvetica", "Verdana", "Tahoma", "Calibri", "Trebuchet MS", "Segoe UI Semibold",
           "Bahnschrift", "Candara", "Corbel"]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]
MOIS_C = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
CATS = {"courses": "Alimentation", "restaurant": "Restaurants", "carburant": "Carburant", "transport": "Transports",
        "telephone": "Téléphone & internet", "internet": "Téléphone & internet", "energie": "Énergie",
        "loyer": "Logement", "streaming": "Abonnements", "shopping": "Shopping", "sante": "Santé",
        "pharmacie": "Santé", "salaire": "Salaire", "aides": "Allocations", "assurance": "Assurances"}


def _date_entete(d, rng, style):
    if d == REF and rng.random() < 0.9:
        return "Aujourd'hui" if style != "maj" else "AUJOURD'HUI"
    if d == REF - datetime.timedelta(days=1) and rng.random() < 0.9:
        return "Hier" if style != "maj" else "HIER"
    j, m = JOURS[d.weekday()], MOIS[d.month - 1]
    t = {
        "long": "%s %d %s" % (j, d.day, m),
        "longan": "%s %d %s %d" % (j, d.day, m, d.year),
        "court": "%d %s" % (d.day, MOIS_C[d.month - 1]),
        "maj": ("%s %d %s" % (j, d.day, m)).upper(),
        "num": d.strftime("%d/%m/%Y"),
        "jourcourt": "%s. %d %s" % (j[:3].capitalize(), d.day, MOIS_C[d.month - 1]),
        "cap": ("%s %d %s" % (j, d.day, m)).capitalize(),
    }[style]
    return t


def _montant(v, fmt, rng):
    s = "%.2f" % abs(v)
    ent, dec = s.split(".")
    sep = fmt["milliers"]
    if len(ent) > 3:
        ent = ent[:-3] + sep + ent[-3:]
    if fmt["anglais"]:
        ent = ent.replace(sep, ",")
        corps = "€" + ent + ("." + dec if not (fmt["sans_centimes"] and dec == "00") else "")
    elif fmt["sans_centimes"] and dec == "00":
        corps = ent + "\u00a0€"
    else:
        euro = {"apres": "\u00a0€", "colle": "€", "sup": "<sup style='font-size:.6em'>€</sup>",
                "eur": "\u00a0EUR", "rien": ""}[fmt["euro"]]
        corps = ent + "," + dec + euro
    if v < 0:
        if fmt["conv"] in ("moins", "moins_plus"):
            return fmt["moins"] + corps
        return corps                              # dépense sans signe (rouge ou noire)
    if fmt["conv"] in ("moins_plus", "plus"):
        return "+" + ("\u00a0" if fmt["moins"].endswith("\u00a0") else "") + corps
    return corps


def _libelle(o, rng, brut):
    if brut:
        return cb.libelle(rng.choice(["sg", "cm", "lbp", "ca", "bpce", "fortuneo", "lcl"]), o, rng)[:34]
    if o.genre == "retrait":
        return rng.choice(["Retrait DAB", "Retrait d'espèces", "Retrait " + rng.choice(cb.VILLES).title()])
    if o.genre == cb.V:
        if o.interne:
            return "Virement vers " + o.nom.title()
        if o.montant > 0:
            return rng.choice(["Virement de ", "Virement reçu de ", "", "Vir. "]) + o.nom.title()
        return rng.choice(["Virement à ", "Virement vers ", ""]) + o.nom.title()
    nom = o.nom
    nom = nom.title() if rng.random() < 0.75 else nom
    if o.genre == cb.P and rng.random() < 0.3:
        nom = "Prélèvement " + nom
    return nom[:32]


def _sous_titre(o, rng, mode, d):
    if mode == "categorie":
        return CATS.get(o.notion or "", rng.choice(["Divers", "Loisirs", "Shopping", "Achats"]))
    if mode == "genre":
        return {"retrait": "Retrait", cb.V: "Virement" + (" reçu" if o.montant > 0 else ""),
                cb.P: "Prélèvement"}.get(o.genre, rng.choice(["Paiement par carte", "Carte", "Paiement CB"]))
    if mode == "heure":
        return "%02d:%02d" % (rng.randint(7, 22), rng.randint(0, 59))
    if mode == "date_heure":
        if d == REF:
            j = "Aujourd'hui"
        elif d == REF - datetime.timedelta(days=1):
            j = "Hier"
        else:
            j = "%d %s" % (d.day, MOIS_C[d.month - 1])
        return "%s, %02d:%02d" % (j, rng.randint(7, 22), rng.randint(0, 59))
    if mode == "date":
        return d.strftime("%d/%m/%Y") if rng.random() < 0.5 else "%d %s %d" % (d.day, MOIS[d.month - 1], d.year)
    return ""


def _style(rng):
    sombre = rng.random() < 0.3
    acc = rng.choice(["#0b5cff", "#7a2ff7", "#e6007e", "#00a37a", "#ff6a00", "#1b2a6b", "#c4002b", "#008c95"])
    return {
        "sombre": sombre,
        "fond": rng.choice(["#000", "#111317", "#1c1c1e", "#191b22"]) if sombre else rng.choice(
            ["#fff", "#f5f6fa", "#fafafa", "#f2f4f7"]),
        "carte": rng.choice(["#1c1c1e", "#22252c", "#000"]) if sombre else "#fff",
        "texte": "#f2f2f2" if sombre else rng.choice(["#111", "#1d1d1f", "#14213d", "#0b1f4b"]),
        "gris": "#9a9aa0" if sombre else rng.choice(["#6b7280", "#8a8a8e", "#5b6b84"]),
        "acc": acc,
        "police": rng.choice(POLICES),
        "taille": rng.choice([14, 15, 15, 16, 16, 17]),
        "pad": rng.choice([10, 12, 14, 16, 18]),
        "icone": rng.random() < 0.75,
        "bandeau": rng.random() < 0.5,         # en-tête de date dans une bande grise
        "vert": rng.choice(["#1aa760", "#00b67a", "#2ecc71", "#12a150"]),
        "rouge": rng.choice(["#d0021b", "#e5484d", "#c62828"]),
    }


def page(rng, n_ops, kind="liste"):
    st = _style(rng)
    fmt = {"milliers": rng.choice(["\u00a0", "\u202f", " ", "."]), "anglais": rng.random() < 0.05,
           "sans_centimes": rng.random() < 0.15, "euro": rng.choice(["apres", "apres", "colle", "sup", "eur"]),
           "conv": rng.choice(["moins", "moins", "moins_plus", "moins_plus", "plus", "aucun"]),
           "moins": rng.choice(["-", "-", "−", "-\u00a0", "– "])}
    if fmt["anglais"]:
        fmt["milliers"] = ","
    couleur_rev = rng.random() < 0.6           # revenu en vert
    couleur_dep = fmt["conv"] in ("aucun", "plus") and rng.random() < 0.6
    # (un mois seul au-dessus de la liste ne date rien : écran écarté par le lecteur)
    # Mises en page vues pendant la validation (15/11/2026) : jour et mois
    # empilés à gauche (Sogexia), date sous le montant (Mouv by LCL), accueil
    # « Dernières opérations » sans date (Crédit Agricole, Green-Got)
    date_mode = rng.choice(["entete", "entete", "entete", "entete", "ligne", "colonne", "empile", "sous_montant",
                            "aucune"])
    if date_mode == "aucune":
        fmt["conv"] = rng.choice(["moins", "moins_plus"])     # montants signés, comme ces accueils
    chevron = rng.random() < 0.3
    attente = kind == "liste" and date_mode in ("entete", "colonne") and rng.random() < 0.25
    a_venir = kind == "liste" and rng.random() < 0.15
    entete_style = rng.choice(["long", "longan", "court", "maj", "num", "jourcourt", "cap"])
    sous_mode = rng.choice(["categorie", "genre", "heure", "aucun"]) if date_mode != "ligne" else \
        rng.choice(["date_heure", "date"])
    brut = rng.random() < 0.3
    W = 390
    H = rng.choice([780, 812, 844, 870, 900])
    css = ("*{box-sizing:border-box}body{margin:0;background:%s;color:%s;font-family:'%s';font-size:%dpx;"
           "width:%dpx;overflow:hidden}.row{display:flex;align-items:center;padding:%dpx 16px;gap:12px}"
           ".ic{width:38px;height:38px;border-radius:50%%;flex:none}.l{flex:1;min-width:0}.t{white-space:nowrap;"
           "overflow:hidden;text-overflow:ellipsis;font-weight:%s}.s{color:%s;font-size:.82em;margin-top:2px}"
           ".m{white-space:nowrap;font-weight:%s;text-align:right}.dh{padding:8px 16px;color:%s;font-size:.85em;%s}"
           ) % (st["fond"], st["texte"], st["police"], st["taille"], W, st["pad"],
                rng.choice(["500", "600", "400"]), st["gris"], rng.choice(["500", "600", "700"]), st["gris"],
                "background:%s;" % ("#2a2a2e" if st["sombre"] else "#e9edf3") if st["bandeau"] else
                "font-weight:600;margin-top:6px;")
    corps = []
    # Barre d'état du téléphone
    if rng.random() < 0.8:
        corps.append("<div style='display:flex;justify-content:space-between;padding:10px 22px;font-weight:600'>"
                     "<span>%d:%02d</span><span>%s</span></div>" % (rng.randint(8, 22), rng.randint(0, 59),
                                                                  rng.choice(["5G", "4G", "LTE", "", "Wi-Fi"])))
    # En-tête : solde, titre, recherche
    haut = rng.choice(["solde", "titre", "recherche", "solde_avenir", "rien"])
    solde = round(rng.uniform(-300, 8000), 2)
    if haut in ("solde", "solde_avenir"):
        corps.append("<div style='background:%s;color:#fff;padding:18px 16px;text-align:center'><div style='opacity:"
                     ".8'>%s</div><div style='font-size:2.2em;font-weight:700'>%s</div></div>"
                     % (st["acc"], rng.choice(["Compte courant", "Compte chèques", "Mon compte", "Solde"]),
                        _montant(solde, dict(fmt, conv="moins"), rng)))
        if haut == "solde_avenir":
            corps.append("<div class='row' style='background:%s'><div class='l'>%s</div><div class='m'>%s</div></div>"
                         % (st["carte"], rng.choice(["Opérations à venir", "Prélèvements à venir", "Solde à venir",
                                                     "Débit différé carte"]),
                            _montant(-round(rng.uniform(10, 400), 2), dict(fmt, conv="moins"), rng)))
    elif haut == "titre":
        corps.append("<div style='font-size:1.6em;font-weight:700;padding:10px 16px'>%s</div>"
                     % rng.choice(["Opérations", "Mes opérations", "Transactions", "Historique", "Activité"]))
    elif haut == "recherche":
        corps.append("<div style='margin:8px 16px;padding:10px;border-radius:10px;background:%s;color:%s'>"
                     "Rechercher une opération</div>" % ("#2a2a2e" if st["sombre"] else "#eceef2", st["gris"]))
    verite = []
    if a_venir:
        corps.append("<div class='row' style='background:%s'><div class='l'>%s</div><div class='m'>›</div></div>"
                     % (st["carte"], rng.choice(["Opérations à venir (2)", "À venir (1)", "Opérations à venir (3)"])))
    if date_mode == "aucune" and kind == "liste":
        corps.append("<div class='dh'>%s</div>" % rng.choice(["Dernières opérations", "Mes dernières transactions",
                                                              "Dernières transactions", "MOIS EN COURS"]))
    if attente:
        # Section « En attente » : pas encore des opérations (absentes de la bonne réponse)
        corps.append("<div class='dh'>%s</div>" % rng.choice(["En attente", "Opérations en attente", "EN COURS"]))
        for _ in range(rng.randint(1, 2)):
            corps.append("<div class='row' style='background:%s'><div class='l'><div class='t'>%s</div>"
                         "<div class='s'>%02d:%02d</div></div><div class='m'>%s</div></div>" % (
                             st["carte"], html.escape(rng.choice(cb.MARCHANDS)[0].title()), rng.randint(7, 22),
                             rng.randint(0, 59), _montant(-round(rng.uniform(3, 90), 2), fmt, rng)))
    if kind == "liste":
        ops = cb._ops(rng, n_ops)
        jours = sorted({REF - datetime.timedelta(days=int(rng.expovariate(1 / 6.0))) for _ in range(n_ops)},
                       reverse=True)
        jours = [j for j in jours if (REF - j).days < 60] or [REF]
        dates = sorted([rng.choice(jours) for _ in ops], reverse=True)
        if date_mode == "mois":
            # Captures où seul le mois est écrit : la date attendue est la fin du mois (ou ce jour)
            dates = [REF] * len(ops)
        cour = None
        if date_mode == "mois":
            corps.append("<div class='dh'>%s</div>" % rng.choice(["Novembre 2026", "NOVEMBRE 2026", "Novembre"]))
        for o, d in zip(ops, dates):
            if date_mode == "entete" and d != cour:
                corps.append("<div class='dh'>%s</div>" % html.escape(_date_entete(d, rng, entete_style)))
                cour = d
            lib = _libelle(o, rng, brut)
            sous = _sous_titre(o, rng, sous_mode, d)
            v = o.montant
            col = st["vert"] if (v > 0 and couleur_rev) else (st["rouge"] if (v < 0 and couleur_dep) else st["texte"])
            ic = ("<div class='ic' style='background:%s'></div>" % rng.choice(
                ["#ffd166", "#06d6a0", "#118ab2", "#ef476f", "#8338ec", "#3a86ff", "#adb5bd"])) if st["icone"] else ""
            gauche = ""
            if date_mode == "colonne":
                gauche = "<div style='width:44px;color:%s;font-size:.85em'>%s</div>" % (
                    st["gris"], d.strftime("%d/%m"))
            elif date_mode == "empile":
                gauche = ("<div style='width:44px;text-align:center;line-height:1.1'><div style='font-weight:700'>%02d"
                          "</div><div style='color:%s;font-size:.7em'>%s</div></div>") % (
                    d.day, st["gris"], MOIS_C[d.month - 1].upper())
            montant = _montant(v, fmt, rng)
            if rng.random() < 0.06 and v < 0:
                # Payé dans une autre devise : le montant d'origine, gris, avant celui du compte
                montant = "<span style='color:%s;font-weight:400;margin-right:10px'>-%s\u00a0£</span>%s" % (
                    st["gris"], ("%.2f" % (abs(v) * 0.85)).replace(".", ","), montant)
            if date_mode == "sous_montant":
                montant += "<div style='color:%s;font-size:.75em;font-weight:400'>%s</div>" % (
                    st["gris"], "Aujourd'hui" if d == REF else "%d %s %d" % (d.day, MOIS[d.month - 1], d.year))
            if chevron:
                montant += "<span style='color:%s;margin-left:8px'>›</span>" % st["gris"]
            corps.append("<div class='row' style='background:%s'>%s%s<div class='l'><div class='t'>%s</div>%s</div>"
                         "<div class='m' style='color:%s'>%s</div></div>" % (
                             st["carte"], gauche, ic, html.escape(lib),
                             "<div class='s'>%s</div>" % html.escape(sous) if sous else "", col, montant))
            verite.append({"date": (REF if date_mode == "aucune" else d).isoformat(), "montant": round(v, 2),
                           "libelle": lib})
    elif kind == "categories":
        corps.append("<div class='dh'>Dépenses par catégorie</div>")
        for c in rng.sample(list(set(CATS.values())), 5):
            corps.append("<div class='row'><div class='ic' style='background:#ccc'></div><div class='l'><div class='t'>"
                         "%s</div><div class='s'>%d transactions</div></div><div class='m'>%s</div></div>"
                         % (c, rng.randint(1, 30), _montant(-round(rng.uniform(5, 600), 2), fmt, rng)))
    elif kind == "budget":
        # Écran de budget (CMB, Arkéa) : ressources, charges, épargne, signés
        for c, mt in [("Mes ressources", 1620), ("Charges fixes", -720), ("Quotidien", -430), ("Mon épargne", 410),
                      ("Loisirs", -120)][:rng.randint(3, 5)]:
            corps.append("<div class='row'><div class='l'><div class='t'>%s</div></div><div class='m'>%s</div></div>"
                         % (c, _montant(mt + round(rng.uniform(-50, 50), 2), dict(fmt, conv="moins_plus"), rng)))
    elif kind == "placements":
        corps.append("<div class='dh'>Mes placements au %s</div>" % REF.strftime("%d/%m/%Y"))
        for c in rng.sample(["Fonds Actions Europe", "Monétaire Plus", "Obligations 2028", "Immobilier SCPI",
                             "ETF Monde"], 3):
            corps.append("<div class='row'><div class='l'><div class='t'>%s</div><div class='s'>Valeur de part : %s"
                         "</div></div><div class='m'>%s<div style='font-size:.8em'>%s</div></div></div>" % (
                             c, _montant(round(rng.uniform(10, 300), 2), dict(fmt, conv="aucun"), rng),
                             _montant(round(rng.uniform(100, 9000), 2), dict(fmt, conv="aucun"), rng),
                             _montant(round(rng.uniform(-300, 300), 2), dict(fmt, conv="moins_plus"), rng)))
    elif kind == "comptes":
        for c in ["Compte courant", "Livret A", "LDDS", "Assurance vie", "PEA", "Compte joint"]:
            corps.append("<div class='row'><div class='l'><div class='t'>%s</div><div class='s'>N° •••• %04d</div>"
                         "</div><div class='m'>%s</div></div>" % (c, rng.randint(0, 9999),
                                                                  _montant(round(rng.uniform(10, 9000), 2), fmt, rng)))
    # Barre du bas
    if rng.random() < 0.7:
        corps.append("<div style='display:flex;justify-content:space-around;margin-top:8px;"
                     "padding:10px 0 18px;background:%s;color:%s;font-size:.75em'>%s</div>" % (
                         st["carte"], st["gris"], "".join("<span>%s</span>" % x for x in rng.choice(
                             [["Comptes", "Virements", "Cartes", "Plus"], ["Accueil", "Paiements", "Hub", "Profil"],
                              ["Mes comptes", "Budget", "Aide", "Menu"]]))))
    # Hauteur : tout le contenu (sinon la bonne réponse compterait des lignes
    # cachées sous le bas de l'écran) ; au moins un écran de téléphone
    t = st["taille"]
    n_rows = sum(1 for c in corps if c.startswith("<div class='row'"))
    n_dh = sum(1 for c in corps if c.startswith("<div class='dh'"))
    haut = 60 + 140 + n_rows * (2 * st["pad"] + 2.4 * t + 4) + n_dh * (22 + 1.1 * t) + 70
    H = max(H, int(haut * 1.12))
    return ("<!doctype html><html><head><meta charset='utf-8'><style>%s</style></head><body>%s</body></html>"
            % (css, "".join(corps)), W, H, verite)


def _photo(chrome, html_path, png, W, H, dpr):
    """Une page -> une capture. Déjà faite : rien (la fabrication reprend là
    où elle s'était arrêtée). Chrome trop lent (PC chargé) : un second essai."""
    if os.path.exists(png) and os.path.getsize(png) > 0:
        return
    for delai in (90, 240):
        prof = tempfile.mkdtemp(prefix="pilote_chrome_")
        try:
            subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                            "--user-data-dir=" + prof, "--screenshot=" + png, "--window-size=%d,%d" % (W, H),
                            "--force-device-scale-factor=%s" % dpr, "file:///" + html_path.replace("\\", "/")],
                           capture_output=True, timeout=delai)
            return
        except subprocess.TimeoutExpired:
            continue


def main():
    dossier = os.path.abspath(sys.argv[1])
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    graine = int(sys.argv[3]) if len(sys.argv) > 3 else 2026
    os.makedirs(dossier, exist_ok=True)
    chrome = next(c for c in CHROME if os.path.exists(c))
    rng = random.Random(graine)
    verite, travaux = {}, []
    for i in range(1, n + 1):
        x = rng.random()
        kind = ("categories" if x < 0.04 else "comptes" if x < 0.08 else "budget" if x < 0.10 else
                "placements" if x < 0.12 else "liste")
        h, W, H, v = page(rng, rng.randint(5, 11), kind)
        nom = "cap_%04d.png" % i
        hp = os.path.join(dossier, nom[:-4] + ".html")
        open(hp, "w", encoding="utf-8").write(h)
        dpr = rng.choice([3, 3, 2, 2.625, 1.5])
        verite[nom] = {"kind": kind, "operations": v, "dpr": dpr}
        travaux.append((hp, os.path.join(dossier, nom), W, H, dpr))
    # La bonne réponse d'abord : elle ne dépend que de la graine
    json.dump({"ref": REF.isoformat(), "captures": verite}, open(os.path.join(dossier, "verite.json"), "w",
                                                                   encoding="utf-8"), ensure_ascii=False, indent=1)
    with ThreadPoolExecutor(2) as ex:
        list(ex.map(lambda t: _photo(chrome, *t), travaux))
    json.dump({"ref": REF.isoformat(), "captures": verite}, open(os.path.join(dossier, "verite.json"), "w",
                                                                   encoding="utf-8"), ensure_ascii=False, indent=1)
    print("ecrit", n, "captures dans", dossier)


if __name__ == "__main__":
    main()
