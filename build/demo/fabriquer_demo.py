"""Fabrique la démo en ligne de Pilote (le site : pilote-appli.github.io/demo/).

La démo, c'est la vraie interface (src/ui/index.html) qui tourne dans un
navigateur, sans serveur local ni pont pywebview : build/demo/demo.js leur
répond à leur place avec des réponses enregistrées sur les données de Brice.

Ce script :
1. copie src/ dans un dossier temporaire et y écrit les données de Brice
   (src/donnees_exemple.py) : les vraies données ne sont jamais lues, le
   dossier Donnees de la copie est un dossier neuf ;
2. démarre le vrai serveur local de cette copie, ouvre l'interface dans Edge
   (Playwright) et passe sur chaque onglet : chaque réponse du serveur et
   chaque lecture du pont sont notées ;
3. écrit la démo dans <dossier> : index.html (avec demo.js en tête), vendor/,
   demo-donnees.js.

Les cours et les courbes sont ceux du jour de la fabrication : la refaire à
chaque version garde la démo à jour.

Usage : python build/demo/fabriquer_demo.py <dossier de sortie>
        (par exemple ..\\pilote-appli.github.io\\demo)
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time

ICI = os.path.dirname(os.path.abspath(__file__))
DEPOT = os.path.abspath(os.path.join(ICI, "..", ".."))

CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
       "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; frame-src 'none'; "
       "object-src 'none'; base-uri 'none'; form-action 'none'")


def preparer_copie(tmp):
    """src/ copié à part, avec un Donnees neuf rempli par Brice."""
    shutil.copytree(os.path.join(DEPOT, "src"), os.path.join(tmp, "src"),
                    ignore=shutil.ignore_patterns("__pycache__"))
    sys.path.insert(0, os.path.join(tmp, "src"))
    import donnees_exemple
    dossier = os.path.join(tmp, "Donnees")
    donnees_exemple.ecrire(dossier)
    # Brice en utilisateur « Exemple » : l'interface affiche son bandeau et
    # la visite de Pilou le reconnaît (_estExemple)
    chemin = os.path.join(dossier, "users.json")
    with open(chemin, encoding="utf-8") as f:
        etat = json.load(f)
    for u in etat["users"]:
        u["exemple"] = True
    with open(chemin, "w", encoding="utf-8") as f:
        json.dump(etat, f, ensure_ascii=False, indent=1)
    return dossier


def enregistrer(tmp):
    import storage
    assert os.path.abspath(str(storage.get_app_dir())).startswith(os.path.abspath(tmp)), \
        "la copie lit un autre dossier que le sien : arrêt"
    import server
    import app
    api = app.Api()
    port = server.start_server(html_path=os.path.join(tmp, "src", "ui", "index.html"))
    methodes = sorted(n for n in dir(app.Api) if not n.startswith("_") and callable(getattr(app.Api, n)))

    pont, requetes = {}, {}

    def enreg(nom, args_json):
        args = json.loads(args_json or "[]")
        try:
            r = getattr(api, nom)(*args)
        except Exception as e:
            r = {"ok": False, "error": str(e)}
        r = json.loads(json.dumps(r, default=str))
        if nom != "jeton":
            pont[nom + json.dumps(args, separators=(",", ":"), ensure_ascii=False)] = r
            pont.setdefault(nom, r)
        return r

    def enreg_fetch(cle, texte):
        requetes[cle] = texte

    from playwright.sync_api import sync_playwright
    with open(os.path.join(ICI, "demo.js"), encoding="utf-8") as f:
        shim = f.read()
    with sync_playwright() as p:
        nav = p.chromium.launch(channel="msedge")
        # bypass_csp : les attentes de Playwright évaluent du texte, que la CSP de Pilote refuse
        page = nav.new_page(viewport={"width": 1366, "height": 768}, bypass_csp=True)
        page.on("console", lambda m: m.type == "error" and print("  [console]", m.text[:200]))
        page.on("response", lambda r: r.status >= 400 and print("  [%d]" % r.status, r.url[:160]))
        page.expose_function("__enreg", enreg)
        page.expose_function("__enregFetch", enreg_fetch)
        page.add_init_script("window.__DEMO = " + json.dumps({"fetch": {}, "pont": {}, "methodes": methodes}) + ";\n" + shim)
        page.goto("http://127.0.0.1:%d/" % port)
        page.wait_for_function("document.querySelector('#home-cards > *')", timeout=60000)
        page.wait_for_load_state("networkidle")
        onglets = page.evaluate("[...new Set([...document.querySelectorAll('.sb-item[data-tab]')].map(b => b.dataset.tab))]")
        print("  %d onglets" % len(onglets))
        for o in onglets:
            page.evaluate("t => { goTab(t); _setActiveSidebar(t); }", o)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            time.sleep(1.2)
        # Les périodes de la courbe du PEA (boutons 1M, 6M, 1A, Max…)
        page.evaluate("() => { goTab('dash'); _setActiveSidebar('dash'); }")
        time.sleep(1.5)
        # Les indices de comparaison de la courbe (CAC 40, S&P 500, ETF World),
        # cochés puis décochés pour laisser la démo comme Brice l'a réglée
        page.evaluate("""async () => {
          for (const c of document.querySelectorAll('#pane-dash input[data-bench]')) {
            c.click(); await new Promise(r => setTimeout(r, 2500)); c.click();
          }
        }""")
        page.wait_for_load_state("networkidle")
        time.sleep(1.0)
        nav.close()
    server.stop_server()
    return methodes, pont, requetes


def anonymiser(texte, tmp):
    """La démo va sur un site public : aucun chemin du PC qui la fabrique (ils
    portent le nom de la session) ne doit y rester. /data, par exemple, rend
    data_path et appdata_env dans son _debug. Les chemins sont remplacés par
    ceux d'un PC fictif, puis on vérifie que le nom de session a disparu."""
    remplacements = [(tmp, r"C:\Users\Brice\Pilote"), (os.path.expanduser("~"), r"C:\Users\Brice")]
    for chemin, fictif in remplacements:
        for avant, apres in ((chemin, fictif), (chemin.replace("\\", "/"), fictif.replace("\\", "/"))):
            for n in (1, 2, 4):   # chemin tel quel, échappé une fois (JSON), deux fois (JSON dans JSON)
                texte = texte.replace(avant.replace("\\", "\\" * n), apres.replace("\\", "\\" * n))
    nom = os.path.basename(os.path.expanduser("~"))
    if nom and re.search(re.escape(nom), texte, re.I):
        i = re.search(re.escape(nom), texte, re.I).start()
        raise SystemExit("ARRET : le nom de session « %s » reste dans la démo : …%s…" % (nom, texte[max(0, i - 80):i + 40]))
    return texte


def ecrire_demo(tmp, sortie, methodes, pont, requetes):
    os.makedirs(sortie, exist_ok=True)
    with open(os.path.join(tmp, "src", "ui", "index.html"), encoding="utf-8") as f:
        html = f.read()
    # vendor/ à côté de la page, plus à la racine du serveur
    html = html.replace("${location.origin}/vendor/", "${new URL('vendor/', location.href).href}")
    html = re.sub(r'(["\'`(])/vendor/', r"\1vendor/", html)
    tete = ('<head>\n<meta http-equiv="Content-Security-Policy" content="%s">\n'
            '<meta name="robots" content="noindex">\n'
            '<script src="demo-donnees.js"></script>\n<script src="demo.js"></script>\n' % CSP)
    html = html.replace("<head>", tete, 1)   # le premier, comme server._inject_session_token
    with open(os.path.join(sortie, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
    shutil.copy(os.path.join(ICI, "demo.js"), os.path.join(sortie, "demo.js"))
    donnees = {"fetch": requetes, "pont": pont, "methodes": methodes}
    texte = anonymiser(json.dumps(donnees, ensure_ascii=False, separators=(",", ":")), tmp)
    with open(os.path.join(sortie, "demo-donnees.js"), "w", encoding="utf-8", newline="\n") as f:
        f.write("/* Réponses enregistrées sur Brice, profil fictif (build/demo/fabriquer_demo.py) */\n")
        f.write("window.__DEMO = " + texte + ";\n")
    cible = os.path.join(sortie, "vendor")
    if os.path.isdir(cible):
        shutil.rmtree(cible)
    shutil.copytree(os.path.join(tmp, "src", "ui", "vendor"), cible)


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    sortie = os.path.abspath(sys.argv[1])
    tmp = tempfile.mkdtemp(prefix="pilote-demo-")
    try:
        preparer_copie(tmp)
        print("Enregistrement sur les données de Brice…".encode("ascii", "replace").decode())
        methodes, pont, requetes = enregistrer(tmp)
        print("  %d réponses du serveur, %d lectures du pont".encode("ascii", "replace").decode()
              % (len(requetes), len(pont)))
        for k in sorted(requetes):
            print("    %-70s %7d" % (k[:70], len(requetes[k])))
        ecrire_demo(tmp, sortie, methodes, pont, requetes)
        print("Demo ecrite dans %s" % sortie)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
