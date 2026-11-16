"""
splash.py — Petite fenetre de chargement affichee au lancement de Pilote.

La fenetre principale est creee CACHEE et ne s'ouvre qu'une fois l'accueil
pret : boot() (index.html) appelle Api.app_ready(), qui la montre et ferme
celle-ci. En attendant, animation « Signature » (choisie par Arthur le
03/10/2026 parmi trois maquettes) : le logo arrive en rebondissant, le P
monte dans la tuile, « Pilote » s'ecrit lettre par lettre ; puis, en
boucle, un reflet passe sur la tuile, des ondes en partent et une barre
glisse dessous. Rien que transform et opacity : pendant le chargement, le
processeur est pris par Python et WebView2, ces proprietes-la restent
fluides.

Le HTML est construit ici plutot que dans un fichier a part : un splash.html
devrait etre ajoute aux datas de build/pilote.spec, et l'oublier ne se
verrait que dans l'exe compile (le meme piege que ocr_win.ps1). La police est
celle du systeme (style Verre) : la page n'a pas d'origine et ne peut rien
demander au serveur local.
"""
from __future__ import annotations

import re

# 340 x 260 (maquette validee) agrandi de 35 % a la demande d'Arthur (4.3.19) :
# .scene { zoom } grossit tout le contenu d'autant, les proportions restent
SIZE = (460, 350)

_DEFAULT_ACCENT = "#c026d3"   # ACCENT_DEFAULT (index.html) / DEFAULT_COLOR (appicon.py)

# Style « Verre », le seul depuis le 16/11/2026 (le Carnet est retire) : memes
# jetons que html.verre dans index.html. « haut » eclaire le centre du fond ;
# « bord » = --brd rendu opaque sur --bg, pour le liseré que Windows 11 trace
# autour des coins arrondis.
_THEMES_VERRE = {
    "light": {"bg": "#eceef3", "txt": "#1d1d1f", "txt2": "#5f5f66", "brd": "rgba(0,0,0,0.11)",
              "haut": "#f6f7fa", "bord": (206, 208, 214), "fond1": 34, "fond2": 22},
    "dark":  {"bg": "#0d0d12", "txt": "#f5f5f7", "txt2": "#aeaeb5", "brd": "rgba(255,255,255,0.13)",
              "haut": "#16161d", "bord": (44, 44, 52), "fond1": 30, "fond2": 19},
}


def _jetons(theme: str) -> dict:
    return _THEMES_VERRE.get(theme, _THEMES_VERRE["light"])


def background(theme: str) -> str:
    return _jetons(theme)["bg"]


def arrondir_coins(hwnd: int, theme: str) -> bool:
    """Coins arrondis par Windows 11 lui-meme (DWM) : lisses, ombre comprise,
    rayon fixe de 8 px. Une fenetre transparente avec border-radius en CSS
    passerait par la « couleur cle » de pywebview, qui laisse des franges.
    Sous Windows 10 l'appel echoue sans rien casser : coins droits."""
    try:
        import ctypes
        dwm = ctypes.windll.dwmapi
        rond = ctypes.c_int(2)                                     # DWMWCP_ROUND
        ok = dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(rond), 4) == 0  # DWMWA_WINDOW_CORNER_PREFERENCE
        r, g, b = _jetons(theme)["bord"]
        couleur = ctypes.c_uint(r | (g << 8) | (b << 16))         # COLORREF : 0x00BBGGRR
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(couleur), 4)  # DWMWA_BORDER_COLOR
        return ok
    except Exception:
        return False


_POLICE = '-apple-system, BlinkMacSystemFont, "Segoe UI Variable Display", "Segoe UI", system-ui, sans-serif'


def build_html(accent: str, theme: str) -> str:
    """Style Verre : fond a la couleur d'accent (comme le fond de l'app),
    tuile avec un reflet de verre, nom et P dans la police du systeme."""
    t = _jetons(theme)
    # L'accent finit dans du CSS : seul un #rrggbb passe
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent or ""):
        accent = _DEFAULT_ACCENT

    return """<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8"><title>Pilote</title>
<style>
:root { --bg:%(bg)s; --txt:%(txt)s; --txt2:%(txt2)s; --brd:%(brd)s; --accent:%(accent)s; }
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body { height: 100%%; background: var(--bg); overflow: hidden; user-select: none; cursor: default; }
body {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  border: 1px solid var(--brd); color: var(--txt);
  font-family: %(police)s;
  /* Deux taches d'accent, et le centre a peine plus clair */
  background:
    radial-gradient(60%% 70%% at 18%% 20%%, color-mix(in srgb, var(--accent) %(fond1)d%%, var(--bg)), transparent 72%%),
    radial-gradient(60%% 70%% at 85%% 85%%, color-mix(in srgb, var(--accent) %(fond2)d%%, var(--bg)), transparent 72%%),
    radial-gradient(ellipse 78%% 70%% at 50%% 44%%, %(haut)s, var(--bg));
}
.scene { position: relative; display: flex; flex-direction: column; align-items: center; zoom: 1.35; }
/* Logo : halo qui respire, deux ondes, tuile qui rebondit, P qui monte, reflet */
.logo { position: relative; width: 72px; height: 72px; }
.halo {
  position: absolute; inset: -80px; border-radius: 50%%;
  background: radial-gradient(closest-side, color-mix(in srgb, var(--accent) 24%%, transparent), transparent);
  animation: halo 3.4s .5s ease-in-out infinite alternate both;
}
@keyframes halo { from { opacity: .35; transform: scale(.8); } to { opacity: 1; transform: scale(1.08); } }
.onde {
  position: absolute; inset: 0; border-radius: 19px; border: 2px solid var(--accent); opacity: 0;
  animation: onde 2.6s .75s cubic-bezier(.15,.6,.3,1) infinite;
}
.onde + .onde { animation-delay: 2.05s; }
@keyframes onde { 0%% { transform: scale(1); opacity: .6; } 100%% { transform: scale(1.85); opacity: 0; } }
.tuile {
  position: relative; width: 72px; height: 72px; border-radius: 19px; overflow: hidden;
  background: linear-gradient(180deg, rgba(255,255,255,.28), rgba(255,255,255,0) 55%%), var(--accent);
  color: #fff; display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 40px;
  box-shadow: inset 0 1px 0 rgba(255,255,255,.45), 0 14px 30px -12px color-mix(in srgb, var(--accent) 80%%, transparent);
  animation: pop .8s cubic-bezier(.2,.9,.3,1.25) both;
}
@keyframes pop { 0%% { transform: scale(.25) rotate(-14deg); opacity: 0; } 55%% { opacity: 1; } 100%% { transform: none; opacity: 1; } }
.tuile .p { display: block; line-height: 1; animation: monte .65s .3s cubic-bezier(.2,.8,.2,1) both; }
@keyframes monte { from { transform: translateY(115%%); } to { transform: none; } }
.reflet {
  position: absolute; inset: -30%%; transform: translateX(-130%%);
  background: linear-gradient(105deg, transparent 38%%, rgba(255,255,255,.5) 50%%, transparent 62%%);
  animation: reflet 2.8s 1.1s ease-in-out infinite;
}
@keyframes reflet { 0%% { transform: translateX(-130%%); } 42%%, 100%% { transform: translateX(130%%); } }
/* Nom ecrit lettre par lettre */
.nom {
  display: flex; overflow: hidden; margin-top: 16px; padding: 0 3px .14em;
  font-weight: 700; font-size: 29px; letter-spacing: -.03em; line-height: 1.1;
}
.nom span { display: inline-block; animation: lettre .6s cubic-bezier(.2,.8,.2,1) both; }
.nom span:nth-child(1) { animation-delay: .55s; } .nom span:nth-child(2) { animation-delay: .61s; }
.nom span:nth-child(3) { animation-delay: .67s; } .nom span:nth-child(4) { animation-delay: .73s; }
.nom span:nth-child(5) { animation-delay: .79s; } .nom span:nth-child(6) { animation-delay: .85s; }
@keyframes lettre { from { transform: translateY(105%%) rotate(10deg); opacity: 0; } to { transform: none; opacity: 1; } }
/* Barre de chargement : un trait qui glisse en boucle */
.piste {
  width: 136px; height: 3px; border-radius: 9px; background: var(--brd); overflow: hidden; margin-top: 12px;
  animation: fondu .4s 1.15s both;
}
.piste i {
  display: block; width: 42%%; height: 100%%; border-radius: 9px; background: var(--accent);
  animation: glisse 1.5s 1.15s cubic-bezier(.65,0,.35,1) infinite;
}
@keyframes glisse { from { transform: translateX(-100%%); } to { transform: translateX(240%%); } }
.txt { font-size: 12.5px; color: var(--txt2); margin-top: 10px; animation: fondu .5s 1.3s both; }
@keyframes fondu { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
/* Mouvement reduit : tout s'affiche d'emblee, sans rebond ni onde. La barre
   continue de glisser, plus lentement : un indicateur de chargement doit
   rester visible. */
@media (prefers-reduced-motion: reduce) {
  .halo, .onde, .tuile, .tuile .p, .reflet, .nom span, .piste, .txt { animation: none; }
  .halo { opacity: .7; }
  .piste i { animation-duration: 3s; animation-delay: 0s; }
}
</style></head>
<body><div class="scene">
  <div class="logo" aria-hidden="true">
    <div class="halo"></div><i class="onde"></i><i class="onde"></i>
    <div class="tuile"><span class="p">P</span><i class="reflet"></i></div>
  </div>
  <div class="nom" aria-hidden="true"><span>P</span><span>i</span><span>l</span><span>o</span><span>t</span><span>e</span></div>
  <div class="piste" aria-hidden="true"><i></i></div>
  <div class="txt" role="status">Chargement de tes donn&eacute;es&hellip;</div>
</div></body></html>""" % {"accent": accent, "police": _POLICE, **t}
