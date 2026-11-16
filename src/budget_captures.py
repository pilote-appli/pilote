"""
budget_captures.py — Captures d'écran d'une appli bancaire -> opérations de
Mes comptes.

L'utilisateur fait une capture de la liste de ses opérations dans l'appli de
sa banque (BoursoBank, Revolut, N26, Crédit Agricole…) et l'importe comme un
relevé. Le texte est lu par le moteur de Windows (celui de Santé, sante.py ;
Vision sur Mac), puis ce module reconnaît les lignes « libellé … montant »,
les en-têtes de date (« Aujourd'hui », « Hier », « lundi 10 novembre ») et
écarte ce qui n'est pas une opération (solde, totaux par catégorie, à venir).
Les opérations repartent ensuite dans le classement des relevés
(budget_releves.analyser) : même aperçu, rien n'est écrit sans validation.

Mesure et pièges : docs/modules/comptes.md, « Captures d'écran ».
"""
from __future__ import annotations

import collections
import datetime
import os
import re
import statistics
import tempfile
import unicodedata

# ─── Texte ───────────────────────────────────────────────────────────────────


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = s.replace("’", "'")
    return re.sub(r"\s+", " ", s).strip()


MOIS = {"janvier": 1, "janv": 1, "jan": 1, "january": 1, "fevrier": 2, "fevr": 2, "fev": 2, "feb": 2,
        "february": 2, "mars": 3, "mar": 3, "march": 3, "avril": 4, "avr": 4, "apr": 4, "april": 4, "mai": 5,
        "may": 5, "juin": 6, "jun": 6, "june": 6, "juillet": 7, "juil": 7, "jul": 7, "july": 7, "aout": 8,
        "aou": 8, "aug": 8, "august": 8, "septembre": 9, "sept": 9, "sep": 9, "september": 9, "octobre": 10,
        "oct": 10, "october": 10, "novembre": 11, "nov": 11, "november": 11, "decembre": 12, "dec": 12,
        "december": 12}
_MOIS_RE = "|".join(sorted(MOIS, key=len, reverse=True))
_JOURS_RE = (r"lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|lun|mar|mer|jeu|ven|sam|dim|monday|tuesday|"
             r"wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun")

# ─── Montants ────────────────────────────────────────────────────────────────
# Ce que l'OCR fait d'un montant : « -1 ooo,oo€ » (o pour 0), « _9,99 » (le
# signe moins lu comme un tiret bas), « 800,006 » ou « 50,00C » (le symbole €
# en exposant lu comme 6, C, e ou ?), « 12,50 EUR », « € 12.50 », « 1,234.56 ».

_EURO = r"(?:€|eur|euros?|e|c|6|\?|¢|ê|é|£|\$)"
_SIGNE = r"(?P<signe>[-−–—_~+])?"
_ENTIER = r"(?P<ent>\d{1,3}(?:[ .,'  ]\d{3})+|\d+)"
_MONTANT_RE = re.compile(
    r"^" + _SIGNE + r"\s?(?P<pre>€|eur)?\s?" + _SIGNE.replace("signe", "signe2") + r"\s?" + _ENTIER
    + r"(?:[,.](?P<dec>\d{2}))?\s?(?P<suf>" + _EURO + r")?$", re.I)


def _chiffres_ocr(t: str) -> str:
    """o, O, D lus à la place de 0 dans un nombre ; l, I, | à la place de 1."""
    def fix(m):
        return m.group(0).translate(str.maketrans("oODlI|", "000111"))
    # seulement entre ou à côté de chiffres et de séparateurs
    return re.sub(r"(?<![a-zA-Z])[\doODlI|][\doODlI|\s.,]*[\doODlI|](?![a-zA-Z]{2})", fix, t)


def lire_montant(texte: str):
    """« -1 000,00 € » -> (-1000.0, signe '-', devise '€'). None si ce n'est pas
    un montant seul."""
    t = str(texte or "").strip().replace("−", "-")
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*[>›»〉]+$", "", t)      # chevron de la ligne (« - 10,40 € > »)
    if not t or len(t) > 22:
        return None
    t = _chiffres_ocr(t)
    # « 800,006 » : trois décimales dont la dernière est le symbole € mal lu
    m3 = re.fullmatch(r"(.*\d[,.]\d{2})([6])", t)
    if m3 and not re.search(r"\d[,.]\d{4}", t):
        t = m3.group(1) + "€"
    # « - 1 304,77 0 », « -960,00 K » : le symbole € lu comme une lettre, après un blanc
    m4 = re.fullmatch(r"(.*\d[,.]\d{2}) ([0oO6cCeéKk€])", t)
    if m4:
        t = m4.group(1) + " €"
    # « - 522,43' » : le € en exposant lu comme une apostrophe ou un accent
    m5 = re.fullmatch(r"(.*\d[,.]\d{2}) ?['’`´°*]", t)
    if m5:
        t = m5.group(1) + " €"
    m = _MONTANT_RE.match(t)
    if not m:
        return None
    ent, dec, suf, pre = m.group("ent"), m.group("dec"), (m.group("suf") or ""), (m.group("pre") or "")
    signe = m.group("signe") or m.group("signe2") or ""
    devise = "€" if (pre or re.fullmatch(r"(?i)€|eur|euros?|e|c|6|\?|¢|ê|é", suf)) else (suf if suf in "£$" else "")
    if dec is None:
        # Sans centimes, seulement avec un vrai symbole (« -12 € » chez Revolut)
        # (un « € » mal lu, « -40 C », passe s'il y a un signe ; « -15533 € » est
        # « -155,33 € » dont la virgule n'a pas été lue : refusé plutôt que faux)
        if not (suf == "€" or pre or _norm(suf) in ("eur", "euro", "euros")
                or (signe and suf and re.search(r"\d \S$", t))):
            return None
        if re.search(r"[.,]\d{1,2}$", ent) or re.fullmatch(r"\d{4,}", ent):
            return None
    # Séparateurs de milliers : « 1 000 », « 1.000 » (avec virgule décimale), « 1,000 » (avec point)
    if re.search(r"[ .,'  ]", ent):
        groupes = re.split(r"[ .,'  ]", ent)
        if any(len(g) != 3 for g in groupes[1:]):
            return None
        ent = "".join(groupes)
    v = float(ent) + (float("0." + dec) if dec else 0.0)
    if v == 0 or v > 1_000_000:
        return None
    if signe in "-−–—_~" and signe:
        v = -v
        signe = "-"
    return (round(v, 2), signe, devise)


# ─── Dates ───────────────────────────────────────────────────────────────────

_JOURS_NUM = {"lun": 0, "mar": 1, "mer": 2, "jeu": 3, "ven": 4, "sam": 5, "dim": 6, "mon": 0, "tue": 1, "wed": 2,
              "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _jour_mois(j, mo, an, ref: datetime.date, jour_sem=None):
    """Sans année : la plus récente qui ne dépasse pas la capture ; avec le
    jour de la semaine (« dimanche 19 mai »), l'année où ce jour tombe juste."""
    try:
        j, mo = int(j), int(mo)
        if an:
            an = int(an)
            an = an + 2000 if an < 100 else an
            return datetime.date(an, mo, j)
        d = datetime.date(ref.year, mo, j)
        if d > ref + datetime.timedelta(days=1):
            d = datetime.date(ref.year - 1, mo, j)
        if jour_sem is not None and d.weekday() != jour_sem:
            for k in range(1, 8):
                try:
                    d2 = datetime.date(d.year - k, mo, j)
                except ValueError:
                    continue
                if d2.weekday() == jour_sem:
                    return d2
        return d
    except ValueError:
        return None


def lire_date(texte: str, ref: datetime.date, mois_courant=None):
    """Date contenue dans un texte (en-tête ou sous-titre) : (date, seule) où
    seule dit que le texte n'est rien d'autre qu'une date (un en-tête)."""
    n = _norm(texte).strip(" .,:-·•|")
    n = re.sub(r"(\d)(er|e)\b", r"\1", n)
    # « mardi IO novembre » : I, l et O lus à la place de 1 et 0 dans le jour
    n = re.sub(r"\b([0-9iol]{1,2}) (?=(?:" + _MOIS_RE + r")\b)",
               lambda m: m.group(1).translate(str.maketrans("iol", "101")) + " ", n)
    if not n:
        return None, False
    # Aujourd'hui / Hier (et leurs lectures abîmées : « Ier », « aujourdhui »)
    m = re.match(r"^(aujourd ?'? ?hui|aujourdhui|today|ce jour)\b", n)
    if m:
        return ref, len(n) <= len(m.group(0)) + 8 or bool(re.fullmatch(r"[\w' ]+[ ,]+\d{1,2}[:h]\d{2}", n))
    m = re.match(r"^(hier|yesterday|ier)\b", n)
    if m and not (m.group(1) == "ier" and len(n) > 4):
        return ref - datetime.timedelta(days=1), len(n) <= len(m.group(0)) + 8
    # « Il y a 6 heures », « il y a 3 jours », « 2 h ago »
    m = re.match(r"^(?:il ?y ?a )?(\d{1,2}) ?(min|mins|minutes?|h|heures?|hours?|j|jours?|days?)\b(?: ago)?", n)
    if m and (re.match(r"il ?y ?a ", n) or "ago" in n):
        jours = int(m.group(1)) if m.group(2)[0] in "jd" else 0
        return ref - datetime.timedelta(days=jours), len(n) <= len(m.group(0)) + 4
    m = re.match(r"^(avant[- ]hier)\b", n)
    if m:
        return ref - datetime.timedelta(days=2), True
    # « lundi 31 juillet 2023 », « 31 juil. », « 12 NOV », « mardi 12 novembre »
    m = re.search(r"(?:\b(" + _JOURS_RE + r")\.?,? )?\b(\d{1,2}) (" + _MOIS_RE + r")\.?(?: (\d{4}))?\b", n)
    if m:
        d = _jour_mois(m.group(2), MOIS[m.group(3)], m.group(4), ref,
                       _JOURS_NUM.get(m.group(1)[:3]) if m.group(1) else None)
        if d:
            reste = (n[:m.start()] + n[m.end():]).strip(" .,:-·•|")
            return d, not reste or bool(re.fullmatch(r"[\d:h ]*", reste))
    # « Nov 12, 2026 », « November 12 »
    m = re.search(r"\b(" + _MOIS_RE + r")\.? (\d{1,2})(?:,? (\d{4}))?\b", n)
    if m:
        d = _jour_mois(m.group(2), MOIS[m.group(1)], m.group(3), ref)
        if d:
            reste = (n[:m.start()] + n[m.end():]).strip(" .,:-·•|")
            reste = re.sub(r"^(" + _JOURS_RE + r")\.?,?", "", reste).strip()
            return d, not reste
    # « 12/11/2026 », « 12/11 », « 12.11.26 »
    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?\b", n)
    if m and 1 <= int(m.group(2)) <= 12:
        d = _jour_mois(m.group(1), m.group(2), m.group(3), ref)
        if d:
            reste = (n[:m.start()] + n[m.end():]).strip(" .,:-·•|")
            reste = re.sub(r"^(" + _JOURS_RE + r")\.?,?", "", reste).strip()
            return d, not reste
    # Jour de la semaine seul (« Mardi ») : la semaine passée
    m = re.fullmatch(r"(lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|monday|tuesday|wednesday|thursday|"
                     r"friday|saturday|sunday)", n)
    if m:
        jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        en = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        k = jours.index(m.group(1)) if m.group(1) in jours else en.index(m.group(1))
        ecart = (ref.weekday() - k) % 7 or 7
        return ref - datetime.timedelta(days=ecart), True
    return None, False


def lire_mois(texte: str, ref: datetime.date):
    """En-tête de mois : « Novembre 2026 », « NOVEMBRE », « Octobre » -> (année, mois)."""
    n = _norm(texte).strip(" .,:-")
    m = re.fullmatch(r"(" + _MOIS_RE + r")\.?(?: (\d{4}))?", n)
    if not m or len(m.group(1)) < 3:
        return None
    mo = MOIS[m.group(1)]
    an = int(m.group(2)) if m.group(2) else (ref.year if mo <= ref.month else ref.year - 1)
    return an, mo

# ─── Ce qui n'est pas une opération ──────────────────────────────────────────

_PAS_OPERATION = re.compile(
    r"\b(solde|soldes|balance|disponible|available|a venir|en cours|encours|decouvert|plafond|limite|"
    r"total(?! ?(energies|access|station|wash|fina|elf))|totaux|"
    r"depense|depenses|depenser|spent|revenus? du mois|budget|reste a|il vous reste|epargne totale|patrimoine|"
    r"valeur|montant brut|plus[- ]value|moins[- ]value|performance|rendement|cours de|portefeuille|"
    r"investi|iban|bic|rib|objectif|cashback|cagnotte|economies|this month|ce mois|mois dernier|"
    r"moyenne|par mois|par jour|net worth|income|spending|depuis le|statistiques|analyse|"
    r"debit differe|prelevements?\s*/\s*virements|operations? a venir|virements? a venir|"
    r"en attente de|pending|bloque|autorisation|mon compte|avenir|"
    r"carte (visa|mastercard|premier|gold|platinum|ultim|metal|standard))\b")
# (un virement vers le livret, le PEA, l'assurance vie est une opération : le
# classement des relevés le reconnaît comme virement interne. Mais un libellé
# qui COMMENCE par un nom de compte est la ligne de ce compte, avec son solde.)
_NOM_DE_COMPTE = re.compile(r"(comptes?|livrets?|ldds|lep|pel|cel|pea|cto|assurance vie|epargne|entrees|sorties|"
                            r"total des comptes|mes comptes|mes |mon |ma )\b")
# Sous-titre d'une ligne de compte : son solde, son numéro masqué
_SOUS_TITRE_COMPTE = re.compile(r"solde|disponible|iban|[•*x]{3,}|n[°o] ?[•*x]|^([a-z]{1,2} ){3,}\d{4}$")
# (« •••• 1016 » se lit parfois « e e ee 1016 » : des lettres seules puis 4 chiffres)
_SOUS_TITRE_RESUME = re.compile(r"^\d+ (transactions?|operations?|paiements?|achats?|mouvements?|depenses?)\b|"
                                r"\b\d+ ?%")
_SOUS_TITRE_PLACEMENT = re.compile(r"\b(valeur (de |de la )?part|parts?\b|cours|quantite|qte|vl au|nav|expire|expiration|valable|echeance|restant|objectif)\b")
_EN_ATTENTE = re.compile(r"(en attente|a venir|operations? a venir|pending|upcoming|en cours|prevu|previsionnel(le)?s?|"
                         r"operations? en attente|autorisations?( en cours)?)")
_GENRE_SOUS_TITRE = re.compile(r"^(paiement|achat|prelevement|prlv|virement|vir|retrait|carte|cb|depot|remise|"
                               r"cheque|frais|commission|cotisation|remboursement|transfert|card|transfer|"
                               r"direct debit|top[- ]?up|rechargement|contactless|sans contact|apple pay|"
                               r"google pay|en attente|pending)")


def _est_heure(t: str) -> bool:
    return bool(re.fullmatch(r"\d{1,2}[:h.]\d{2}( ?(am|pm))?", _norm(t)))


def _en_attente(dessus, entetes, ys) -> bool:
    """L'opération est-elle dans une section « En attente » ? Elle dure
    jusqu'à l'en-tête suivant ; mais jusqu'à « Transactions comptabilisées »
    quand l'écran en a un (ING : des dates sous chaque section), et jusqu'en
    bas quand c'est le titre de l'écran (« Opérations cartes en attente »
    suivi directement d'un en-tête de date, sans opération entre les deux).
    ys : hauteur de chaque opération de l'écran."""
    attente = [e for e in dessus if e[1] is None]
    if not attente:
        return False
    dernier = attente[-1]
    apres = [e for e in dessus if e[0] > dernier[0]]
    if any(e[1] == "fin" or e[1] == "mois" for e in apres):
        return False
    if not apres:
        return True
    suivant = min([e[0] for e in entetes if e[0] > dernier[0]] or [10 ** 9])
    # (« Opérations à venir (2) » chez Nickel est une ligne repliée, un lien :
    # pas le titre de l'écran. Un titre dit « en attente » ou « en cours », sans chiffre.)
    t = _norm(dernier[2].texte)
    titre = not any(dernier[0] < y < suivant for y in ys) and bool(re.search(r"en attente|en cours", t)) \
        and not re.search(r"\d", t)
    fin_ecran = any(e[1] == "fin" and e[0] > dernier[0] for e in entetes)
    return titre or fin_ecran


_VOCAB_CATEGORIES = None


def _est_categorie(titre: str) -> bool:
    """Libellé qui est un nom de catégorie ou de compte, pas un marchand."""
    global _VOCAB_CATEGORIES
    if _VOCAB_CATEGORIES is None:
        mots = set()
        try:
            from budget_marchands import CIBLES, SYNONYMES
            for k, v in SYNONYMES.items():
                for x in [k] + list(v):
                    mots.update(_norm(x).split())
            for t, c, s in CIBLES.values():
                mots.update(_norm(c).split())
                mots.update(_norm(s or "").split())
        except Exception:
            pass
        mots.update("comptes compte bancaires epargne actions crypto cryptos livret ldds pea cto assurance vie "
                    "retraits retrait banque divers autres shopping voyages voyage transports sante loisirs "
                    "abonnements factures emprunt emprunts besoins essentiels virement virements especes "
                    "revenus depenses impots taxes achats sorties maison logement vacances cadeaux enfants "
                    "education animaux beaute soins habillement vetements high tech multimedia professionnel "
                    "pro chq vir cheques investissements bourse immobilier esthetique quotidien ressources charges "
                    "fixes categoriser categorise categorie categoriee".split())
        mots -= {"et", "de", "la", "le", "les", "des", "du", "a", "en", "au", "aux"}
        # Des mots d'opérations, pas de catégories : « Virement Livret Bleu »,
        # « Retrait DAB 28/09 » sont des opérations
        mots -= {"virement", "vir", "retrait", "dab", "prelevement", "cb", "carte", "paiement", "cheque"}
        _VOCAB_CATEGORIES = mots
    toks = [t for t in re.split(r"[^a-z]+", _norm(titre)) if len(t) > 1 and t not in (
        "et", "de", "la", "le", "les", "des", "du", "en", "au", "aux")]
    # (un mot coupé, « Banqu », compte s'il commence un mot du vocabulaire)
    # (coupé d'une ou deux lettres seulement : « Shop » n'est pas « Shopping »)
    connus = sum(1 for t in toks if t in _VOCAB_CATEGORIES or (len(t) >= 5 and any(
        m.startswith(t) and len(m) - len(t) <= 2 for m in _VOCAB_CATEGORIES)))
    return bool(toks) and len(toks) <= 4 and connus >= 0.6 * len(toks)

def _libelle_brut(t: str) -> bool:
    """« CB CARREFOUR 12/11 », « PRLV SEPA EDF » : le libellé brut de la banque
    (majuscules, préfixe bancaire, date ou numéro), à nettoyer."""
    lettres = re.sub(r"[^A-Za-zÀ-ÿ]", "", t)
    maj = lettres and sum(c.isupper() for c in lettres) >= 0.8 * len(lettres)
    return bool(maj and (re.match(r"(?i)(cb|carte|prlv|prelevement|vir|virement|paiement|achat|retrait|facture|"
                                  r"remise|chq|cheque)\b", t.strip()) or re.search(r"\d{2}[/.]\d{2}|\d{4,}", t)))


# ─── Lignes de texte ─────────────────────────────────────────────────────────

class Ligne:
    __slots__ = ("mots", "texte", "x0", "x1", "y0", "y1", "h", "montant", "pris")

    def __init__(self, mots):
        self.mots = mots
        self.texte = " ".join(w["t"] for w in mots).strip()
        self.x0 = min(w["x"] for w in mots)
        self.x1 = max(w["x"] + w["w"] for w in mots)
        self.y0 = min(w["y"] for w in mots)
        self.y1 = max(w["y"] + w["h"] for w in mots)
        self.h = statistics.median([w["h"] for w in mots]) or 1
        self.montant = None
        self.pris = False

    @property
    def cy(self):
        return (self.y0 + self.y1) / 2.0


def _lignes(mots: list) -> list:
    """Lignes du moteur (`l`), coupées là où un grand blanc sépare deux
    colonnes (« Plombier ......... -500,00 € » lu d'un seul tenant)."""
    par = collections.OrderedDict()
    for w in mots:
        if str(w.get("t", "")).strip():
            par.setdefault(w.get("l", id(w)), []).append(w)
    sortie = []
    for groupe in par.values():
        groupe.sort(key=lambda w: w["x"])
        h = statistics.median([w["h"] for w in groupe]) or 1
        cour = [groupe[0]]
        for w in groupe[1:]:
            fin = cour[-1]["x"] + cour[-1]["w"]
            if w["x"] - fin > 2.2 * h:
                sortie.append(Ligne(cour))
                cour = [w]
            else:
                cour.append(w)
        sortie.append(Ligne(cour))
    # Un montant collé au libellé sans grand blanc (« Carrefour -12,50 € ») :
    # on détache les derniers mots s'ils forment un montant à droite.
    finales = []
    for li in sortie:
        coupee = False
        if len(li.mots) >= 2 and lire_montant(li.texte) is None:
            for k in range(1, min(4, len(li.mots) - 1) + 1):
                queue = li.mots[-k:]
                tq = " ".join(w["t"] for w in queue)
                if lire_montant(tq) is not None and re.search(r"[,.]\d{2}|€", tq):
                    finales.append(Ligne(li.mots[:-k]))
                    finales.append(Ligne(queue))
                    coupee = True
                    break
        if not coupee:
            finales.append(li)
    finales.sort(key=lambda l: (l.y0, l.x0))
    return finales


def _recouvrement(a, b) -> float:
    """Part de la hauteur de la plus petite ligne commune aux deux."""
    haut = min(a.y1, b.y1) - max(a.y0, b.y0)
    return haut / max(1.0, min(a.y1 - a.y0, b.y1 - b.y0))

# ─── Une capture ─────────────────────────────────────────────────────────────


def operations(ocr: dict, ref: datetime.date, couleur=None) -> dict:
    """Résultat de l'OCR ({words, width, height}) -> {operations, ignorees,
    raison}. `couleur(x0, y0, x1, y1)` rend "vert", "rouge" ou "" pour la
    couleur du texte d'un montant (None : pas d'image, pas de couleur)."""
    W = ocr.get("width") or max([w["x"] + w["w"] for w in ocr.get("words", [])] or [1])
    lignes = _lignes(ocr.get("words", []))
    ign = collections.Counter()
    for li in lignes:
        m = lire_montant(li.texte)
        # (dans la partie droite : un écran de téléphone posé au milieu d'une
        # image plus large a ses montants vers le centre)
        if m and li.x1 > 0.4 * W:
            li.montant = m
    montants = [li for li in lignes if li.montant]
    if not montants:
        return {"operations": [], "ignorees": {}, "raison": "aucun montant lu"}
    h_med = statistics.median([li.h for li in montants])
    # Colonne des libellés : le bord gauche le plus fréquent des lignes de
    # texte situées à gauche des montants (à 2 % de la largeur près)
    bords = collections.Counter(int(li.x0 / (0.02 * W)) for li in lignes
                                if not li.montant and len(re.sub(r"\W", "", li.texte)) >= 3 and li.x1 < 0.75 * W)
    x_col = (bords.most_common(1)[0][0] * 0.02 * W) if bords else 0
    # Icône lue comme une lettre collée devant le libellé (« e F Cotis Compte
    # Jeune ») : le premier mot, à gauche de la colonne, est retiré
    for k, li in enumerate(lignes):
        if not li.montant and len(li.mots) >= 2 and li.x0 < x_col - 0.03 * W and len(li.mots[0]["t"]) <= 2 \
                and abs(li.mots[1]["x"] - x_col) <= 0.04 * W:
            lignes[k] = Ligne(li.mots[1:])

    # Dates : en-têtes (ligne qui n'est qu'une date) et mois
    entetes = []      # (y, date, ligne) ; date None : section « En attente »
    mois_entetes = []
    for li in lignes:
        if li.montant:
            continue
        tn = _norm(li.texte).strip(" .:")
        # (« Opérations à venir … -311,92 € » est une ligne de résumé, avec son
        # montant : pas le titre d'une section)
        avec_montant = any(m.x0 > li.x1 and _recouvrement(m, li) > 0.3 for m in montants)
        # (« Opérations à venir (2) » est une ligne repliée, un lien : pas une section)
        repliee = bool(re.search(r"\(\d+\)", tn))
        if li.x0 < 0.5 * W and not avec_montant and not repliee and (_EN_ATTENTE.fullmatch(tn) or re.match(
                r"(transactions?|operations?|paiements?|mouvements?)( cartes?| cb)? (en attente|en cours|a venir)\b", tn)):
            entetes.append((li.cy, None, li))
            li.pris = True
            continue
        if li.x0 < 0.5 * W and re.fullmatch(r"(transactions?|operations?|mouvements?) (comptabilisees?|passees?|"
                                            r"effectuees?|realisees?|enregistrees?)|historique|"
                                            r"(mes )?dernieres (operations|transactions)|mois en cours", tn):
            entetes.append((li.cy, "fin", li))      # fin de la section « en cours »
            continue
        d, seule = lire_date(li.texte, ref)
        # Jour et mois empilés dans une colonne (« 02 » au-dessus de « FÉVR. »)
        if not d and re.fullmatch(r"\d{1,2}", li.texte.strip()) and li.x0 < 0.5 * W:
            for l2 in lignes:
                if l2 is not li and 0 <= l2.y0 - li.y1 <= 0.9 * li.h and l2.x0 < li.x1 and l2.x1 > li.x0 \
                        and lire_mois(re.sub(r"[^\w]", "", l2.texte), ref):
                    d = _jour_mois(li.texte.strip(), lire_mois(re.sub(r"[^\w]", "", l2.texte), ref)[1], None, ref)
                    if d:
                        seule = True
                        l2.pris = True
                    break
        if d and seule:
            entetes.append((li.cy, d, li))
            li.pris = True
            continue
        mm = lire_mois(li.texte, ref)
        if mm and li.x0 < 0.5 * W:
            mois_entetes.append((li.cy, mm))
            entetes.append((li.cy, "mois", li))

    # 1er passage : chaque montant, son libellé et son sous-titre
    rangs = []
    sous_pris = set()
    ticket = False
    attente_cles = []     # (montant, début du libellé) des opérations en attente
    n_comptes = 0         # lignes écartées comme nom de compte (« Épargne », « Comptes bancaires »)
    for a in montants:
        v, signe, devise = a.montant
        # Gros chiffre (solde en tête d'écran, total) : pas une opération.
        # Gros par rapport aux autres montants ET à son libellé (une image peut
        # mêler de petits montants, un téléphone réduit, à un grand encart)
        gros = len(montants) >= 2 and a.h > 1.55 * h_med
        # Deux montants sur la même ligne (« -27,00 £  -31,63 € ») : le
        # montant dans la devise d'origine, puis celui du compte, à droite
        voisins = [m for m in montants if m is not a and _recouvrement(m, a) > 0.5]
        if any(m.x0 > a.x1 for m in voisins):
            ign["devise d'origine"] += 1
            continue
        # (une valeur sans signe puis sa variation signée, « 303,85 €  +23,45 € » :
        # un tableau de placements, pas une opération)
        if signe and any(m.x1 < a.x0 and not m.montant[1] and m.montant[2] not in ("£", "$")
                         and devise not in ("£", "$") for m in voisins):
            ign["tableau"] += 1
            continue
        # Libellé : la ligne à gauche qui partage la même hauteur
        # (montant centré entre le libellé et le sous-titre : le libellé, plus
        # gros ou au-dessus ; une date ou une heure seule n'est pas un libellé)
        # Le plus à droite d'abord : à gauche du libellé, il n'y a que le logo
        # (« DONOU » écrit dans l'icône) ou une colonne de dates.
        cands = [l for l in lignes if l is not a and not l.montant and l.x1 <= a.x0 + 4
                 and _recouvrement(l, a) > 0.1 and not _est_heure(l.texte)]
        # (une icône lue « O » ou « e », ou le texte d'un logo à gauche du
        # libellé, « uber » : pas le libellé quand un vrai libellé est à côté)
        vrais = [l for l in cands if len(re.sub(r"\W", "", l.texte)) >= 3]
        if vrais:
            cands = vrais
        if len(cands) > 1:
            x_lib = max(l.x0 for l in cands)
            cands = [l for l in cands if not (l.x1 < x_lib and len(l.texte) <= 8
                                              and any(c.x0 == x_lib and c.h >= l.h for c in cands))]
        lib = None
        if cands:
            bons = [l for l in cands if not lire_date(l.texte, ref)[1] and _recouvrement(l, a) > 0.5] or \
                [l for l in cands if not lire_date(l.texte, ref)[1]]
            x_max = max([l.x0 for l in bons] or [0])
            lib = max(cands, key=lambda l: (not l.pris and not lire_date(l.texte, ref)[1], _recouvrement(l, a) > 0.5,
                                            l.x0 >= x_max - 0.03 * W, round(l.h / max(1.0, a.h) * 5), -l.cy))
            # Montant centré entre deux lignes alignées : le libellé est celle du haut
            for l in cands:
                if l is not lib and not l.pris and 0 < lib.y0 - l.y1 <= 1.0 * lib.h \
                        and abs(l.x0 - lib.x0) <= 0.02 * W + lib.h and l.h >= lib.h * 0.9 \
                        and not lire_date(l.texte, ref)[1]:
                    lib = l
            # Montant à hauteur du sous-titre (plus petit) : le libellé est la
            # ligne plus grande juste au-dessus, même si elle ne touche pas le montant
            for l in lignes:
                if l is not lib and not l.montant and not l.pris and 0 < lib.y0 - l.y1 <= 0.8 * lib.h \
                        and abs(l.x0 - lib.x0) <= 0.03 * W + lib.h \
                        and (lib.h < 0.92 * l.h or _est_categorie(lib.texte)
                             or _GENRE_SOUS_TITRE.search(_norm(lib.texte))) \
                        and l.x1 <= a.x0 + 4 and not lire_date(l.texte, ref)[1] and not _est_heure(l.texte):
                    lib = l
                    break
        if lib is None:
            # Montant posé sur la ligne du sous-titre : le libellé est juste
            # au-dessus ; ou montant remonté au-dessus du libellé (sa date est
            # écrite dessous, Mouv by LCL) : juste en dessous. Pas une date seule.
            proches = [l for l in lignes if l is not a and not l.montant and l.x1 <= a.x0 + 4 and not l.pris
                       and (0 < a.cy - l.cy <= 2.2 * max(l.h, a.h) or 0 < l.cy - a.cy <= 1.8 * max(l.h, a.h))
                       and not _est_heure(l.texte) and not lire_date(l.texte, ref)[1]]
            if proches:
                lib = min(proches, key=lambda l: abs(a.cy - l.cy))
        # Libellé trop court (une icône lue « O ») ou hors de la colonne de
        # texte (le logo écrit « uber ») : la ligne la plus grande de la colonne
        # des libellés, juste au-dessus du montant ou à sa hauteur (montant
        # centré sur le titre et le sous-titre, Revolut, Trade Republic)
        if lib is None or len(re.sub(r"\W", "", lib.texte)) < 3 or lib.x0 < x_col - 0.03 * W:
            fen = [l for l in lignes if l is not a and not l.montant and l.x1 <= a.x0 + 4
                   and l.x0 >= x_col - 0.03 * W and -1.0 * a.h <= a.cy - l.cy <= 2.0 * max(l.h, a.h)
                   and len(re.sub(r"\W", "", l.texte)) >= 3 and not _est_heure(l.texte)
                   and not lire_date(l.texte, ref)[1] and not l.pris]
            if fen:
                lib = max(fen, key=lambda l: (round(l.h / max(1.0, a.h) * 5), -abs(a.cy - l.cy)))
        if gros and (lib is None or a.h > 1.35 * lib.h):
            ign["solde"] += 1
            continue
        # « En attente de validation » écrit sur la ligne même (ING)
        if lib is not None and any(l is not lib and abs(l.cy - a.cy) <= 1.6 * a.h and l.x0 > lib.x0
                                   and re.search(r"en attente|pending", _norm(l.texte)) for l in lignes):
            attente_cles.append((round(abs(v), 2), _norm(lib.texte)[:10], None))
            ign["en attente"] += 1
            continue
        if lib is None:
            ign["sans libelle"] += 1
            continue
        # Un en-tête de date à côté d'un montant : total du jour
        d_lib, seule = lire_date(lib.texte, ref)
        if d_lib and seule:
            ign["total du jour"] += 1
            continue
        # Libellé coupé sur deux ou trois lignes (« Vir Inst Dupont Paul » /
        # « Tr », « Cotis Ass Pret 12345 » / « 678901 23 ») : les lignes de même
        # taille, alignées et serrées, qui ne sont ni une catégorie, ni une date,
        # ni une heure, ni le libellé d'un autre montant
        # (au-dessus, « Vir De M Paul » est le début du libellé, pas un sous-titre
        # de genre : ce contrôle ne vaut que pour la ligne d'en dessous)
        def suite(l, voisin, dessous=True):
            return (not l.montant and not l.pris and abs(l.x0 - voisin.x0) <= 0.02 * W + 0.5 * voisin.h
                    and 0.85 * voisin.h <= l.h <= 1.2 * voisin.h and l.x1 <= a.x0 + 4
                    and not lire_date(l.texte, ref)[0] and not _est_heure(l.texte) and not _est_categorie(l.texte)
                    and not (dessous and _GENRE_SOUS_TITRE.search(_norm(l.texte)))
                    # (un sous-titre porte souvent une heure, un « • », un code postal)
                    and not re.search(r"\d{1,2}[:h]\d{2}|[•·|]|\b\d{5} [A-Za-zÀ-ÿ]{3}", l.texte)
                    and not any(m is not a and _recouvrement(m, l) > 0.5 for m in montants))
        bloc = [lib]
        while len(bloc) < 3:
            haut = [l for l in lignes if l not in bloc and 0 <= bloc[0].y0 - l.y1 <= 0.7 * bloc[0].h
                    and suite(l, bloc[0], dessous=False)]
            if not haut:
                break
            bloc.insert(0, max(haut, key=lambda l: l.y1))
        while len(bloc) < 3:
            bas = [l for l in lignes if l not in bloc and 0 <= l.y0 - bloc[-1].y1 <= 0.7 * bloc[-1].h
                   and suite(l, bloc[-1])]
            if not bas:
                break
            bloc.append(min(bas, key=lambda l: l.y0))
        texte_lib = " ".join(l.texte for l in bloc)
        haut_lib, bas_lib = bloc[0], bloc[-1]
        # Sous-titre : la ligne juste en dessous du libellé, alignée à gauche
        # (une date seule peut en être un : « 14/11/2026 » sous le libellé)
        sous = None
        for l in lignes:
            if l in bloc or l is a or l.montant:
                continue
            if 0 < l.y0 - bas_lib.y1 <= 1.3 * lib.h and abs(l.x0 - lib.x0) <= 0.04 * W + lib.h:
                if l.x1 <= a.x0 + 4 or _recouvrement(l, a) <= 0:
                    sous = l
                    break
        # Le libellé peut être le sous-titre d'un autre (montant à hauteur du sous-titre)
        dessus = None
        for l in lignes:
            if l in bloc or l.montant or l.pris:
                continue
            if 0 < haut_lib.y0 - l.y1 <= 1.5 * lib.h and abs(l.x0 - lib.x0) <= 0.04 * W + lib.h and l.h >= lib.h * 0.95:
                dessus = l
        titre, sous_l = texte_lib, sous
        if dessus is not None and (_GENRE_SOUS_TITRE.search(_norm(lib.texte)) or lire_date(lib.texte, ref)[0]
                                   or _est_heure(lib.texte.split()[-1])) \
                and not any(l2.montant and _recouvrement(l2, dessus) > 0.3 for l2 in montants):
            titre, sous_l = dessus.texte, lib
        sous_t = sous_l.texte if sous_l else ""
        tn = _norm(titre)
        if re.match(r"(sous[- ])?total\b", tn):
            ticket = True
        # (le libellé peut lui-même être le sous-titre : « 15 transactions », « N° •••• 4835 »)
        compte = bool(_NOM_DE_COMPTE.match(tn) or _SOUS_TITRE_COMPTE.search(_norm(sous_t))
                      or _SOUS_TITRE_COMPTE.search(tn))
        if _PAS_OPERATION.search(tn) or _SOUS_TITRE_RESUME.search(_norm(sous_t)) or _SOUS_TITRE_RESUME.search(tn) \
                or _SOUS_TITRE_PLACEMENT.search(_norm(sous_t)) or compte:
            n_comptes += compte
            ign["solde ou total"] += 1
            continue
        if len(re.sub(r"[^a-z]", "", tn)) < 2:
            ign["sans libelle"] += 1
            continue
        if devise in ("£", "$"):
            ign["autre devise"] += 1
            continue
        if sous_l is not None:
            sous_pris.add(id(sous_l))
        # Date écrite sous le montant, à droite (« 12 janvier 2025 », Mouv by LCL)
        sous_mt = None
        for l in lignes:
            if l is not a and not l.montant and 0 <= l.y0 - a.y1 <= 1.2 * a.h and l.x1 > a.x0 and l.x0 < a.x1 + a.h \
                    and lire_date(l.texte, ref)[1]:
                sous_mt = lire_date(l.texte, ref)[0]
                sous_pris.add(id(l))
                break
        rangs.append((a, v, signe, devise, titre, sous_t, sous_mt))

    # En-têtes de date : pas ceux qui sont en fait le sous-titre d'une opération
    entetes = [e for e in entetes if id(e[2]) not in sous_pris]

    # 2e passage : la date de chaque opération
    ys = [r[0].cy for r in rangs]
    ops = []
    for a, v, signe, devise, titre, sous_t, sous_mt in rangs:
        # Colonne de dates collée au libellé (« 17/06 Rel. Lille Dorez ») : la
        # date de la ligne, retirée du libellé
        date, source_date = (sous_mt, "ligne") if sous_mt else (None, "")
        m = re.match(r"^\s*(\d{1,2}[/.]\d{1,2}(?:[/.]\d{2,4})?|\d{1,2} (?:" + _MOIS_RE + r")\.?)\s+(?=\S{2})",
                     _norm(titre))
        if m and date is None:
            d, _ = lire_date(m.group(1), ref)
            if d:
                date, source_date = d, "ligne"
                titre = titre.strip()[len(m.group(0).strip()):].strip()
        # La date du sous-titre, puis celle de l'en-tête ; une date écrite dans
        # le libellé de la banque (« CARTE 26/09 … ») n'a pas d'année : en dernier
        d, _ = lire_date(sous_t, ref)
        if d and date is None:
            date, source_date = d, "ligne"
        dessus_e = [e for e in entetes if e[0] < a.cy + 0.5 * a.h]
        if _en_attente(dessus_e, entetes, ys):
            attente_cles.append((round(abs(v), 2), _norm(titre)[:10], date.isoformat() if date else None))
            ign["en attente"] += 1      # section « En attente », « À venir »
            continue
        dessus_e = [e for e in dessus_e if e[1] not in ("mois", "fin")]
        if date is None and dessus_e:
            date, source_date = dessus_e[-1][1], "entete"
        if date is None:
            d, _ = lire_date(titre, ref)
            if d:
                date, source_date = d, "libelle"
        if date is None:
            dessus_m = [m for m in mois_entetes if m[0] < a.cy]
            if dessus_m:
                an, mo = dessus_m[-1][1]
                fin = datetime.date(an + (mo == 12), mo % 12 + 1, 1) - datetime.timedelta(days=1)
                date, source_date = min(fin, ref), "mois"
        # Libellé propre : sans l'heure ni la date collées (« Carrefour · 14:32 »)
        propre = re.sub(r"\s*[·•|,-]?\s*\d{1,2}[:h]\d{2}\s*$", "", titre).strip(" ·•|-")
        propre = re.sub(r"\s*(\.{2,}|…)$", "", propre).strip()     # libellé coupé par l'appli
        ops.append({"valeur": v, "signe": signe, "devise": devise, "titre": propre, "texte": a.texte,
                    "sous": sous_t, "date": date, "sourceDate": source_date,
                    "couleur": couleur(a.x0, a.y0, a.x1, a.y1) if couleur else ""})

    if not ops:
        return {"operations": [], "ignorees": dict(ign), "raison": "aucune ligne d'opération reconnue"}
    # Des euros : un écran sans aucun « € » et aux montants à l'anglaise
    # (« 45,143.49 », « 7.89 ») est la bourse, une crypto, une autre devise.
    # Sans le symbole (gris clair, souvent pas lu), la virgule décimale suffit.
    anglais = sum(1 for o in ops if re.search(r"\d\.\d{2}(?!\d)", o["texte"])
                  and not re.search(r"\d,\d{2}(?!\d)", o["texte"]))
    if not any(o["devise"] == "€" for o in ops) and anglais * 2 >= len(ops):
        return {"operations": [], "ignorees": dict(ign, **{"sans euro": len(ops)}),
                "raison": "aucun montant en euros"}
    # Une liste d'opérations est datée (en-têtes « Aujourd'hui », « 12 nov. »,
    # ou date sur chaque ligne). Sans aucune date, c'est la liste des comptes,
    # un portefeuille, des totaux : rien n'est proposé.
    if not any(o["date"] and o["sourceDate"] != "mois" for o in ops):
        # (un mois seul, « Avril » au-dessus de la liste, c'est l'écran des
        # totaux par catégorie : pas une date d'opération)
        # Exception : les « Dernières opérations » de l'accueil d'une appli
        # (Crédit Agricole, Green-Got, Blank), sans date. Leurs montants sont
        # signés ou colorés, comme des opérations ; une liste de comptes montre
        # des soldes sans signe. Datées du jour de la capture, « à vérifier ».
        signes = sum(1 for o in ops if o["signe"] or o["couleur"])
        n_cat = sum(1 for o in ops if _est_categorie(o["titre"]))
        # (un montant à cinq chiffres et plus est un solde de compte, pas une dépense)
        signee = len(ops) >= 2 and signes >= 0.8 * len(ops) and n_comptes < len(ops) \
            and max(abs(o["valeur"]) for o in ops) < 20000 and n_cat < 0.5 * len(ops)
        # (sans signe lu, on refuse : essayé le 15/11/2026, accepter aussi les
        # montants sans signe faisait passer cryptos, indices et avantages
        # salariés pour des opérations, 7 -> 32 inventées sur les vraies captures)
        if signee:
            for o in ops:
                o["date"], o["sourceDate"] = None, "aucune"
        else:
            return {"operations": [], "ignorees": dict(ign, **{"sans date": len(ops)}),
                    "raison": "aucune date sur l'écran"}
    else:
        # Une ligne sans date au milieu de lignes datées : le solde d'une carte
        # de compte, un total. Écartée.
        sans = [o for o in ops if not o["date"]]
        if sans:
            ign["sans date"] += len(sans)
            ops = [o for o in ops if o["date"]]
    # Écran des totaux par catégorie ou de la liste des comptes : les
    # libellés sont des noms de catégories (« Abonnements », « Épargne »),
    # sans date propre à chaque ligne. Une vraie liste peut avoir quelques
    # libellés de ce genre (« Restaurant ») : il en faut presque tous.
    # (les lignes déjà écartées comme noms de comptes comptent aussi)
    sans_date_ligne = [o for o in ops if o["sourceDate"] != "ligne"]
    n_cat = sum(1 for o in sans_date_ligne if _est_categorie(o["titre"])) + n_comptes
    if len(sans_date_ligne) >= 2 and n_cat >= 0.7 * (len(sans_date_ligne) + n_comptes):
        return {"operations": [], "ignorees": dict(ign, **{"totaux": len(ops)}),
                "raison": "écran des totaux par catégorie ou des comptes"}
    # Ticket de caisse photographié : une ligne TOTAL, et aucun montant signé
    # ni coloré (une appli de banque signe ou colore ses opérations)
    if ticket and not any(o["signe"] or o["couleur"] for o in ops):
        return {"operations": [], "ignorees": dict(ign, **{"ticket": len(ops)}),
                "raison": "ticket de caisse, pas une liste d'opérations"}

    # Sens : le signe écrit, sinon la couleur, sinon la convention de l'écran
    avec_moins = any(o["signe"] == "-" for o in ops)
    avec_plus = any(o["signe"] == "+" or o["couleur"] == "vert" for o in ops)
    sortie = []
    for o in ops:
        v = abs(o["valeur"])
        if o["signe"] == "-":
            s = -1
        elif o["signe"] == "+":
            s = 1
        elif o["couleur"] == "vert":
            s = 1
        elif o["couleur"] == "rouge":
            s = -1
        elif avec_moins and not avec_plus:
            s = 1           # les dépenses portent un « - », les revenus rien
        else:
            s = -1          # écran de dépenses, ou les revenus portent un « + » ou sont en vert
        sens_devine = not o["signe"] and o["couleur"] not in ("vert", "rouge") and not avec_moins
        sous_n = _norm(o["sous"])
        cat_banque = o["sous"] if (o["sous"] and not _GENRE_SOUS_TITRE.search(sous_n)
                                   and not lire_date(o["sous"], ref)[0] and not _est_heure(o["sous"])
                                   and not re.search(r"\d", o["sous"])) else ""
        sortie.append({
            "date": (o["date"] or ref).isoformat(),
            "dateDevinee": o["date"] is None,
            "sensDevine": sens_devine,
            "montantSigne": round(s * v, 2),
            "_signeLu": o["signe"],
            "brut": o["titre"],
            # Libellé de l'appli déjà lisible (« Billets de cinéma ») : gardé tel
            # quel ; libellé brut de la banque (« CB CARREFOUR 12/11 ») : nettoyé
            "libelleExact": "" if _libelle_brut(o["titre"]) else o["titre"],
            "typeCol": o["sous"],
            "categorieBanque": cat_banque,
            "mcc": "",
        })
    return {"operations": sortie, "ignorees": dict(ign), "raison": "", "attente": attente_cles}

# ─── Lecture d'une image ─────────────────────────────────────────────────────

FORMATS = ("PNG", "JPEG", "WEBP", "BMP", "GIF")


def est_image(data: bytes) -> bool:
    return (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff"
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP") or data[:2] == b"BM" or data[:4] == b"GIF8")


def est_heic(data: bytes) -> bool:
    return data[4:8] == b"ftyp" and data[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"heim", b"hevc")


def _couleur_fn(im, f):
    """Couleur du texte d'un montant, d'après l'image d'origine (avant le
    passage en gris) : vert pour un revenu chez BoursoBank, N26, Lydia…"""
    rgb = im.convert("RGB")

    def couleur(x0, y0, x1, y1):
        try:
            box = (int(x0 / f), int(y0 / f), int(x1 / f) + 1, int(y1 / f) + 1)
            zone = rgb.crop(box)
            px = list(zone.getdata())
            if not px:
                return ""
            # fond = couleur la plus fréquente ; texte = pixels qui s'en écartent le plus
            fond = collections.Counter((r // 16, g // 16, b // 16) for r, g, b in px).most_common(1)[0][0]
            fr, fg, fb = (c * 16 + 8 for c in fond)
            texte = [p for p in px if abs(p[0] - fr) + abs(p[1] - fg) + abs(p[2] - fb) > 120]
            if len(texte) < 6:
                return ""
            r = sum(p[0] for p in texte) / len(texte)
            g = sum(p[1] for p in texte) / len(texte)
            b = sum(p[2] for p in texte) / len(texte)
            if g > r + 35 and g > b + 5:
                return "vert"
            if r > g + 60 and r > b + 40:
                return "rouge"
            return ""
        except Exception:
            return ""
    return couleur


def lire_image(data: bytes, ref: datetime.date) -> dict:
    """Une capture (octets) -> {ok, banque, operations, ignorees} comme un
    relevé de budget_releves.lire_fichier."""
    import sante
    from PIL import Image, ImageOps
    import io
    chk = sante.ocr_available()
    if not chk.get("ok"):
        return {"ok": False, "erreur": chk.get("error") or "lecture d'images indisponible sur ce poste"}
    try:
        im = Image.open(io.BytesIO(data), formats=list(FORMATS))
        im = ImageOps.exif_transpose(im)
        im.load()
    except Exception:
        return {"ok": False, "erreur": "image illisible"}
    fd, src = tempfile.mkstemp(prefix="pilote_capture_", suffix=".png")
    os.close(fd)
    fd, pre = tempfile.mkstemp(prefix="pilote_capture_pre_", suffix=".png")
    os.close(fd)
    meilleur = None
    meilleur_mode, score_mode = None, None
    lectures = []
    try:
        im.convert("RGB").save(src, compress_level=1)
        w = im.size[0]
        # Trois lectures. D'abord en taille réelle (agrandie x2 sous 900 px de
        # large : capture réduite par une messagerie), avec les deux
        # traitements, clair et sombre : deviner le mode sur toute l'image se
        # trompait quand un écran clair est entouré de sombre. Puis le meilleur
        # des deux, agrandi x2, qui rattrape souvent un montant ou une ligne.
        base = 1.0 if w >= 900 else 2.0
        plan = [(base, "clair"), (base, "sombre"), None]
        for k, etape in enumerate(plan):
            if etape is None:
                etape = (base * 2, meilleur_mode or "clair")
            ech, mode = etape
            # un fichier par lecture : le moteur peut garder le précédent ouvert
            pre_k = pre[:-4] + "_%d.png" % k
            if not _preparer(src, pre_k, ech, mode):
                continue
            ocr = sante._run_ocr(pre_k)
            try:
                os.remove(pre_k)
            except OSError:
                pass
            if not ocr.get("ok"):
                if k == 0:
                    return {"ok": False, "erreur": "lecture de l'image impossible : " + str(ocr.get("error", ""))}
                continue
            f = (ocr.get("width") or w) / float(w)
            r = operations(ocr, ref, _couleur_fn(im, f))
            r["_montants"] = sum(1 for wd in ocr.get("words", []) if re.search(r"\d[,.]\d{2}", wd.get("t", "")))
            lectures.append(r)
            if meilleur is None or _score(r) > _score(meilleur):
                meilleur = r
            # (à égalité d'opérations, le traitement qui a lu le plus de montants)
            if k < 2 and (meilleur_mode is None or (_score(r), r["_montants"]) > score_mode):
                meilleur_mode, score_mode = mode, (_score(r), r["_montants"])
    finally:
        for p in (src, pre):
            try:
                os.remove(p)
            except OSError:
                pass
    if meilleur:
        _completer_signes(meilleur["operations"], [r for r in lectures if r is not meilleur])
        # Une opération qu'une lecture a vue « en attente » (la mention est
        # petite, une autre lecture a pu la rater) : écartée
        # (même montant, même libellé, et même date quand on la connaît : Diego
        # en attente le 24 octobre n'efface pas Diego reçu le 23)
        attente = [k for r in lectures for k in r.get("attente", [])]

        def en_attente(o):
            return any(k[0] == round(abs(o["montantSigne"]), 2) and k[1] == _norm(o["brut"])[:10]
                       and (k[2] is None or k[2] == o["date"]) for k in attente)
        meilleur["operations"] = [o for o in meilleur["operations"] if not en_attente(o)]
    if not meilleur or not meilleur["operations"]:
        return {"ok": False, "erreur": "aucune opération reconnue sur cette capture : il faut l'écran de la liste "
                                       "des opérations, avec le libellé et le montant de chacune"}
    return {"ok": True, "banque": "Capture d'écran", "operations": meilleur["operations"],
            "ignorees": meilleur["ignorees"]}


def _preparer(src: str, dst: str, echelle: float, mode: str = "clair") -> bool:
    """Image en gris pour le moteur. « clair » : le canal le plus sombre (un
    montant vert ou rouge devient noir, comme le mode « min » de Santé),
    inversé si le fond est sombre. « sombre » : le canal le plus clair, puis
    inversé ; avec le plus sombre, un montant rouge sur fond noir devenait
    noir sur noir, illisible."""
    try:
        from PIL import Image, ImageChops, ImageOps, ImageStat
        im = Image.open(src).convert("RGB")
        r, g, b = im.split()
        if mode == "sombre":
            gris = ImageOps.invert(ImageChops.lighter(ImageChops.lighter(r, g), b))
        else:
            gris = ImageChops.darker(ImageChops.darker(r, g), b)
            if ImageStat.Stat(gris).mean[0] < 100:
                gris = ImageOps.invert(gris)
        w, h = gris.size
        f = min(echelle, 8000 / float(max(w, h)))
        if f > 1.0:
            gris = gris.resize((int(w * f), int(h * f)), Image.LANCZOS)
        gris.save(dst, compress_level=1)
        return True
    except Exception as e:
        print("[captures] preparation KO : %s" % e, flush=True)
        return False


def _score(r):
    """La lecture la plus complète : le plus d'opérations, puis le plus de
    dates différentes (un en-tête de date gris clair, pas lu, rattache ses
    opérations à l'en-tête d'avant)."""
    ops = r["operations"]
    return (len(ops), len({o["date"] for o in ops}))


def _completer_signes(ops, autres):
    """Un « - » que l'une des deux lectures n'a pas vu (petit, gris) : repris
    de l'autre lecture, pour la même opération (montant et libellé)."""
    for o in ops:
        if not o.get("_signeLu"):
            for r in autres:
                for x in r["operations"]:
                    if x.get("_signeLu") and abs(abs(x["montantSigne"]) - abs(o["montantSigne"])) < 0.005 \
                            and _norm(x["brut"])[:10] == _norm(o["brut"])[:10]:
                        o["montantSigne"] = abs(o["montantSigne"]) * (-1 if x["_signeLu"] == "-" else 1)
                        o["sensDevine"] = False
                        break
    for o in ops:
        o.pop("_signeLu", None)


class SessionOcr:
    """Un seul moteur de lecture pour toutes les captures d'un import (voir
    sante._ServeurOcr : 3 s de démarrage au lieu de 3 s par passe).
    differe=True : le moteur ne démarre qu'à demarrer(), appelé devant la
    première capture. Un import de CSV ou de PDF ne lançait sinon un
    PowerShell que pour rien : 3 s perdues à chaque import, et 1 020 dans
    test_entrainement_1020_releves (mesuré le 16/11/2026)."""

    def __init__(self, differe: bool = False):
        self.differe = differe
        self.ouvert = False

    def demarrer(self):
        import sys
        if sys.platform != "win32" or self.ouvert:
            return
        import sante
        if sante._serveur is None:
            try:
                sante._serveur = sante._ServeurOcr()
                self.ouvert = True
            except Exception:
                sante._serveur = None

    def __enter__(self):
        if not self.differe:
            self.demarrer()
        return self

    def __exit__(self, *a):
        if self.ouvert:
            import sante
            if sante._serveur is not None:
                sante._serveur.fermer()
            sante._serveur = None
        return False


def fusionner(par_capture: list) -> list:
    """Plusieurs captures d'un même écran qui se chevauchent (on fait défiler,
    on capture encore) : une opération vue sur deux captures n'est gardée
    qu'une fois. Deux cafés identiques le même jour sur UNE capture restent
    deux cafés : on garde, pour chaque opération, le plus grand nombre de fois
    qu'une seule capture la montre."""
    garde = collections.Counter()
    sortie = []
    for ops in par_capture:
        ici = collections.Counter()
        for o in ops:
            k = (o["date"] if not o.get("dateDevinee") else "?", "%.2f" % o["montantSigne"], _norm(o["brut"]))
            ici[k] += 1
            if ici[k] > garde[k]:
                garde[k] += 1
                sortie.append(o)
    return sortie
