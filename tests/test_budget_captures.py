"""Tests de budget_captures.py (captures d'écran d'une appli bancaire).

Sans moteur OCR : les « lectures » sont des listes de mots positionnés, comme
celles que rend ocr_win.ps1. La mesure sur de vraies images est faite par
tests/mesurer_captures.py (docs/modules/comptes.md, « Captures d'écran »)."""
import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import budget_captures as bc  # noqa: E402

REF = datetime.date(2026, 11, 14)


def ecran(lignes, largeur=1170):
    """lignes : [(x, y, texte, h)] -> lecture OCR (un mot par élément d'espace)."""
    mots = []
    for k, (x, y, texte, h) in enumerate(lignes):
        cx = x
        for t in texte.split(" "):
            w = int(len(t) * h * 0.55) + 2
            mots.append({"t": t, "l": k + 1, "x": cx, "y": y, "w": w, "h": h})
            cx += w + int(h * 0.3)
    return {"ok": True, "width": largeur, "height": 2532, "words": mots}


class Montants(unittest.TestCase):
    def test_formes(self):
        cas = {
            "-50,00 €": -50.0, "-50,00€": -50.0, "−9,99 €": -9.99, "_9,99€": -9.99, "- 12,50 €": -12.5,
            "+1 200,00 €": 1200.0, "1 200,00 €": 1200.0, "1.200,00 €": 1200.0, "-1 ooo,oo€": -1000.0,
            "800,006": 800.0, "50,00C": 50.0, "12,50 EUR": 12.5, "-€12.50": -12.5, "€1,234.56": 1234.56,
            "-12 €": -12.0, "3.187,76 €": 3187.76, "54,00": 54.0,
        }
        for texte, attendu in cas.items():
            m = bc.lire_montant(texte)
            self.assertIsNotNone(m, texte)
            self.assertAlmostEqual(m[0], attendu, 2, texte)

    def test_pas_des_montants(self):
        for texte in ["Carrefour", "14:32", "12/11/2026", "45,8996", "59,87 %", "12", "2026", "FR76 1234",
                      "Aujourd'hui", "1 2345,00 €", "0,00 €"]:
            self.assertIsNone(bc.lire_montant(texte), texte)


class Dates(unittest.TestCase):
    def test_entetes(self):
        cas = {
            "Aujourd'hui": REF, "AUJOURD'HUI": REF, "Hier": REF - datetime.timedelta(1),
            "lundi 31 juillet 2023": datetime.date(2023, 7, 31), "mardi 10 novembre": datetime.date(2026, 11, 10),
            "10 nov.": datetime.date(2026, 11, 10), "VENDREDI 13 NOVEMBRE": datetime.date(2026, 11, 13),
            "12/11/2026": datetime.date(2026, 11, 12), "Lun. 9 nov.": datetime.date(2026, 11, 9),
            "28 déc.": datetime.date(2025, 12, 28), "1er novembre": datetime.date(2026, 11, 1),
            "November 12, 2026": datetime.date(2026, 11, 12), "Il y a 6 heures": REF,
            "il y a 3 jours": REF - datetime.timedelta(3), "Mardi": datetime.date(2026, 11, 10),
        }
        for texte, attendu in cas.items():
            d, seule = bc.lire_date(texte, REF)
            self.assertEqual(d, attendu, texte)
            self.assertTrue(seule, texte)

    def test_date_dans_un_sous_titre(self):
        d, seule = bc.lire_date("12 nov., 14:32", REF)
        self.assertEqual(d, datetime.date(2026, 11, 12))
        d, seule = bc.lire_date("Aujourd'hui, 09:10", REF)
        self.assertEqual(d, REF)

    def test_pas_des_dates(self):
        for texte in ["Carrefour Market", "Restaurant Le Mai", "Virement reçu", "Ierome"]:
            d, seule = bc.lire_date(texte, REF)
            self.assertFalse(d and seule, texte)


class Ecran(unittest.TestCase):
    def test_liste_avec_entetes(self):
        """À la manière de BoursoBank : en-têtes de date, libellé, sous-titre,
        montant à droite ; solde en tête et « à venir » à écarter."""
        r = bc.operations(ecran([
            (420, 120, "Compte courant", 30), (460, 180, "800,00 €", 60),
            (250, 300, "Prélèvements à venir", 22), (880, 300, "-50,00 €", 24),
            (250, 420, "Aujourd'hui", 22),
            (340, 500, "Assurance Auto", 24), (880, 500, "-50,00 €", 26), (340, 540, "Assurances", 18),
            (340, 620, "Virement Lucie", 24), (900, 620, "54,00 €", 26), (340, 660, "Virement reçu", 18),
            (250, 760, "Hier", 22),
            (340, 840, "Plombier", 24), (870, 840, "-500,00 €", 26), (340, 880, "Entretien", 18),
            (250, 980, "lundi 31 juillet 2023", 22),
            (340, 1060, "Facture d'électricité", 24), (860, 1060, "-135,00 €", 26), (340, 1100, "Prélèvement", 18),
        ]), REF)
        ops = [(o["date"], o["montantSigne"], o["brut"]) for o in r["operations"]]
        self.assertEqual(ops, [
            ("2026-11-14", -50.0, "Assurance Auto"),
            ("2026-11-14", 54.0, "Virement Lucie"),      # sans signe parmi des « - » : un revenu
            ("2026-11-13", -500.0, "Plombier"),
            ("2023-07-31", -135.0, "Facture d'électricité"),
        ])

    def test_date_et_heure_sous_le_libelle(self):
        """À la manière de Revolut : « 12 nov., 14:32 » sous le libellé,
        montant centré entre les deux lignes, revenus avec « + »."""
        r = bc.operations(ecran([
            (200, 200, "Carrefour City", 36), (900, 225, "-23,40 €", 40), (200, 260, "Aujourd'hui, 12:10", 28),
            (200, 400, "Salaire Employeur", 36), (880, 425, "+2 100,00 €", 40), (200, 460, "12 nov., 08:02", 28),
            (200, 600, "Uber", 36), (920, 625, "-8,90 €", 40), (200, 660, "11 nov., 23:40", 28),
        ]), REF)
        ops = [(o["date"], o["montantSigne"], o["brut"]) for o in r["operations"]]
        self.assertEqual(ops, [("2026-11-14", -23.4, "Carrefour City"), ("2026-11-12", 2100.0, "Salaire Employeur"),
                               ("2026-11-11", -8.9, "Uber")])

    def test_date_sous_le_libelle_pas_un_entete(self):
        """« 14/11/2026 » sous un libellé est la date de CETTE opération, pas
        l'en-tête des suivantes."""
        r = bc.operations(ecran([
            (200, 200, "CARTE AIRBNB", 36), (900, 225, "-43,03 €", 40), (200, 260, "14/11/2026", 28),
            (200, 400, "PRLV SEPA B AND YOU", 36), (900, 425, "-12,44 €", 40), (200, 460, "12/11/2026", 28),
        ]), REF)
        self.assertEqual([o["date"] for o in r["operations"]], ["2026-11-14", "2026-11-12"])

    def test_ecrans_qui_ne_sont_pas_des_operations(self):
        # Totaux par catégorie
        r = bc.operations(ecran([
            (150, 100, "Novembre", 30),
            (280, 300, "Shopping", 30), (610, 300, "-435,50 €", 30), (280, 345, "6 transactions", 24),
            (280, 440, "Voyages", 30), (615, 440, "-307,05 €", 30), (280, 485, "3 transactions", 24),
        ], 924), REF)
        self.assertEqual(r["operations"], [])
        # Liste des comptes (aucune date)
        r = bc.operations(ecran([
            (100, 300, "Compte courant", 30), (800, 300, "1 250,40 €", 30),
            (100, 400, "Mon épargne", 30), (800, 400, "200,00 €", 30),
            (100, 500, "M. Victor Martin", 30), (800, 500, "-15,00 €", 30),
        ]), REF)
        self.assertEqual(r["operations"], [])

    def test_total_du_jour_ecarte(self):
        r = bc.operations(ecran([
            (100, 200, "Mardi 10 novembre", 26), (900, 200, "-35,20 €", 26),
            (200, 280, "Boulangerie Paul", 32), (900, 280, "-5,20 €", 32),
            (200, 380, "Total Energies", 32), (900, 380, "-30,00 €", 32),
        ]), REF)
        self.assertEqual([o["montantSigne"] for o in r["operations"]], [-5.2, -30.0])


    def test_section_en_attente(self):
        """« En attente » jusqu'à l'en-tête suivant ; une ligne de résumé
        « Opérations à venir -311,92 € » n'est pas un titre de section."""
        r = bc.operations(ecran([
            (60, 100, "Opérations à venir", 30), (900, 100, "-311,92 €", 30),
            (60, 200, "En attente", 22),
            (200, 280, "Virement charges", 32), (880, 280, "-2 670,00 €", 32),
            (60, 380, "Aujourd'hui", 22),
            (200, 460, "Train", 32), (900, 460, "-62,98 €", 32),
            (200, 560, "Paiement Facture", 32), (880, 560, "+2 800,00 €", 32),
        ]), REF)
        self.assertEqual([(o["brut"], o["montantSigne"]) for o in r["operations"]],
                         [("Train", -62.98), ("Paiement Facture", 2800.0)])

    def test_en_attente_jusqu_aux_comptabilisees(self):
        """ING : « Transactions en cours » puis « Transactions comptabilisées »,
        chaque opération avec sa date au-dessus."""
        r = bc.operations(ecran([
            (60, 100, "Transactions en cours (montants susceptibles de changer)", 24),
            (60, 170, "18 septembre 2019", 20), (60, 200, "TRANSFERT", 26), (900, 200, "-15,00 €", 26),
            (60, 300, "Transactions comptabilisées", 24),
            (60, 370, "8 octobre 2019", 20), (60, 400, "TRANSFERT", 26), (900, 400, "-22,00 €", 26),
            (60, 470, "25 septembre 2019", 20), (60, 500, "TRANSFERT", 26), (900, 500, "106,00 €", 26),
        ]), REF)
        self.assertEqual([(o["date"], o["montantSigne"]) for o in r["operations"]],
                         [("2019-10-08", -22.0), ("2019-09-25", 106.0)])

    def test_colonne_de_dates_collee_au_libelle(self):
        r = bc.operations(ecran([
            (100, 100, "Pratiq+", 30), (850, 100, "+ 634,39 €", 30),
            (100, 180, "17/06 Rel. Lille Dorez", 26), (880, 180, "- 33,26 €", 26),
            (100, 240, "16/06 Vir De M Jordan", 26), (880, 240, "+ 58,34 €", 26),
            (100, 300, "15/06 Vir Sepa Martin Jean", 26), (880, 300, "- 18,00 €", 26),
        ]), REF)
        self.assertEqual([(o["date"], o["montantSigne"], o["brut"]) for o in r["operations"]], [
            ("2026-06-17", -33.26, "Rel. Lille Dorez"), ("2026-06-16", 58.34, "Vir De M Jordan"),
            ("2026-06-15", -18.0, "Vir Sepa Martin Jean")])

    def test_bourse_et_crypto_ecartees(self):
        """Montants à l'anglaise sans aucun euro : la bourse, une crypto."""
        r = bc.operations(ecran([
            (100, 100, "Aujourd'hui", 24),
            (100, 200, "Bitcoin", 30), (900, 200, "7.89", 30), (100, 240, "BTC", 20),
            (100, 320, "Ethereum", 30), (900, 320, "67.89", 30), (100, 360, "ETH", 20),
            (100, 440, "Dow Jones", 30), (850, 440, "45,143.49", 30),
        ]), REF)
        self.assertEqual(r["operations"], [])

    def test_sous_titre_categorie_plus_bas(self):
        """Montant à hauteur de la catégorie (plus petite) : le libellé est
        le marchand juste au-dessus."""
        r = bc.operations(ecran([
            (60, 100, "Aujourd'hui", 24),
            (300, 200, "Pizzeria Napoli", 34), (300, 250, "Restaurants", 28), (900, 252, "-21,63 €", 30),
            (300, 350, "U EXPRESS", 34), (300, 400, "Alimentation", 28), (900, 402, "-13,26 €", 30),
        ]), REF)
        self.assertEqual([o["brut"] for o in r["operations"]], ["Pizzeria Napoli", "U EXPRESS"])


    def test_placements_ecartes(self):
        r = bc.operations(ecran([
            (60, 200, "AMUNDI ACTIONS MONDE", 28), (60, 240, "VALEUR DE PART AU 11/05/2020 : 11,701 €", 20),
            (850, 200, "537,07 €", 28),
            (60, 320, "AMUNDI MODERATO", 28), (60, 360, "VALEUR DE PART AU 11/05/2020 : 209,77 €", 20),
            (850, 320, "360,03 €", 28),
        ]), REF)
        self.assertEqual(r["operations"], [])

    def test_libelle_brut_ou_lisible(self):
        self.assertTrue(bc._libelle_brut("CB CARREFOUR 12/11"))
        self.assertTrue(bc._libelle_brut("PRLV SEPA EDF"))
        self.assertFalse(bc._libelle_brut("Billets de cinéma"))
        self.assertFalse(bc._libelle_brut("SNCF"))


    def test_jour_et_mois_empiles(self):
        """Sogexia : « 02 » au-dessus de « FÉVR. » dans la colonne de gauche."""
        r = bc.operations(ecran([
            (40, 200, "02", 30), (36, 236, "FÉVR.", 18),
            (200, 205, "Paiement CB - Fournisseur Énergie", 26), (900, 205, "-26,21 €", 26),
            (40, 320, "31", 30), (36, 356, "JANV.", 18),
            (200, 325, "Paiement CB - Plateforme Streaming", 26), (900, 325, "-0,99 €", 26),
        ]), REF)
        self.assertEqual([(o["date"], o["montantSigne"]) for o in r["operations"]],
                         [("2026-02-02", -26.21), ("2026-01-31", -0.99)])

    def test_date_sous_le_montant(self):
        """Mouv by LCL : la date est écrite sous le montant, à droite."""
        r = bc.operations(ecran([
            (200, 200, "Vers Cadeau Maman", 30), (900, 200, "- 10,00 €", 30), (900, 240, "Aujourd'hui", 20),
            (200, 340, "Netflix", 30), (900, 340, "- 7,99 €", 30), (860, 380, "12 janvier 2025", 20),
            (200, 480, "Boulangerie Paul", 30), (900, 480, "- 2,70 €", 30), (860, 520, "11 janvier 2025", 20),
        ]), REF)
        self.assertEqual([(o["date"], o["montantSigne"]) for o in r["operations"]],
                         [("2026-11-14", -10.0), ("2025-01-12", -7.99), ("2025-01-11", -2.7)])

    def test_accueil_sans_date(self):
        """« Dernières opérations » de l'accueil, sans date : montants signés,
        datés du jour de la capture et signalés « date devinée »."""
        r = bc.operations(ecran([
            (100, 100, "Dernières transactions", 28),
            (100, 200, "SNCF Connect", 30), (880, 200, "-110,80 €", 30),
            (100, 300, "Biocoop", 30), (880, 300, "-90,82 €", 30),
            (100, 400, "Salaire", 30), (860, 400, "+2 478,98 €", 30),
        ]), REF)
        self.assertEqual([(o["montantSigne"], o["dateDevinee"]) for o in r["operations"]],
                         [(-110.8, True), (-90.82, True), (2478.98, True)])
        # Une liste de comptes, elle, a des soldes sans signe : refusée
        r = bc.operations(ecran([
            (100, 200, "SARL Durand Paris", 30), (850, 200, "87 908,00 €", 30),
            (100, 300, "SARL Durand Lyon", 30), (850, 300, "46 752,24 €", 30),
        ]), REF)
        self.assertEqual(r["operations"], [])

    def test_chevron_et_devise_d_origine(self):
        r = bc.operations(ecran([
            (60, 100, "Aujourd'hui", 24),
            (200, 200, "V&A Shop", 30), (640, 200, "-27,00 £", 26), (880, 200, "-31,63 €", 30),
            (200, 300, "Epicerie", 30), (850, 300, "- 13,90 € >", 30),
        ]), REF)
        self.assertEqual([(o["brut"], o["montantSigne"]) for o in r["operations"]],
                         [("V&A Shop", -31.63), ("Epicerie", -13.9)])

    def test_avantages_et_tableau_ecartes(self):
        r = bc.operations(ecran([
            (100, 200, "Trajets domicile-travail", 30), (100, 240, "Expire le 31/12/2026", 20),
            (880, 200, "100,00 €", 30),
            (100, 340, "Culture", 30), (100, 380, "Expire le 08/09/2026", 20), (880, 340, "33,00 €", 30),
        ]), REF)
        self.assertEqual(r["operations"], [])
        r = bc.operations(ecran([
            (60, 100, "12/05/2025", 24),
            (100, 200, "Emploi Europe", 28), (600, 200, "303,85 €", 28), (880, 200, "+ 23,45 €", 28),
            (100, 300, "Pôle emploi", 28), (600, 300, "3023,85 €", 28), (880, 300, "- 13,62 €", 28),
        ]), REF)
        self.assertEqual(r["operations"], [])


    def test_libelle_sur_deux_lignes(self):
        """Libellé coupé (« Vir Inst Dupont Paul » / « Tr »), sous-titre de
        catégorie à la même taille, montant à hauteur de la seconde ligne."""
        r = bc.operations(ecran([
            (50, 100, "14 novembre", 28),
            (247, 200, "Vir Inst Dupont Paul", 34), (828, 252, "- 100,00 €", 34), (248, 256, "Tr", 32),
            (248, 312, "Sport", 34),
            (247, 430, "Cotis Ass Pret 12345", 33), (886, 484, "- 9,15 €", 33), (249, 485, "678901 23", 34),
            (249, 544, "Frais bancaires", 30),
        ]), REF)
        self.assertEqual([(o["brut"], o["montantSigne"]) for o in r["operations"]],
                         [("Vir Inst Dupont Paul Tr", -100.0), ("Cotis Ass Pret 12345 678901 23", -9.15)])

    def test_icone_lue_comme_une_lettre(self):
        """Montant centré sur le titre et le sous-titre ; l'icône ronde, lue
        « O », le recouvre mieux que le titre : ce n'est pas le libellé."""
        r = bc.operations(ecran([
            (97, 100, "Ce mois-ci", 32),
            (230, 202, "Option Way", 31), (97, 220, "O", 56), (895, 232, "173,78 €", 32), (229, 271, "10 nov.", 22),
            (230, 400, "Uber Eats", 31), (96, 422, "uber", 21), (946, 430, "8,74 €", 32), (229, 469, "9 nov.", 22),
        ]), REF)
        self.assertEqual([(o["brut"], o["date"]) for o in r["operations"]],
                         [("Option Way", "2026-11-10"), ("Uber Eats", "2026-11-09")])


class Fusion(unittest.TestCase):
    def test_captures_qui_se_chevauchent(self):
        a = [{"date": "2026-11-14", "montantSigne": -3.2, "brut": "Café"},
             {"date": "2026-11-14", "montantSigne": -3.2, "brut": "Café"},
             {"date": "2026-11-13", "montantSigne": -20.0, "brut": "Uber"}]
        b = [{"date": "2026-11-13", "montantSigne": -20.0, "brut": "Uber"},
             {"date": "2026-11-12", "montantSigne": -9.99, "brut": "Netflix"}]
        f = bc.fusionner([a, b])
        self.assertEqual([(o["brut"], o["montantSigne"]) for o in f],
                         [("Café", -3.2), ("Café", -3.2), ("Uber", -20.0), ("Netflix", -9.99)])

    def test_formats_d_image(self):
        self.assertTrue(bc.est_image(b"\x89PNG\r\n\x1a\n" + b"0" * 20))
        self.assertTrue(bc.est_image(b"\xff\xd8\xff\xe0" + b"0" * 20))
        self.assertFalse(bc.est_image(b"Date;Libelle;Montant\n"))
        self.assertTrue(bc.est_heic(b"\x00\x00\x00\x18ftypheic" + b"0" * 10))


if __name__ == "__main__":
    unittest.main()
