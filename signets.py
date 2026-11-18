# -*- coding: utf-8 -*-
"""
signets.py — Ajoute des signets (table des matières cliquable dans la barre
latérale) à un livre PDF, et rend son sommaire imprimé cliquable.

Aucune IA, aucune API : uniquement PyMuPDF, rapidfuzz et (pour les scans) ocrmypdf.

EN LIGNE DE COMMANDE
    python signets.py livre.pdf                 → crée livre_signets.pdf et affiche le bilan
    python signets.py livre.pdf --txt           → écrit aussi livre_signets.txt (liste modifiable)
    python signets.py livre.pdf --liste ma_liste.txt
                                                → pose les signets d'une liste corrigée à la main
    python signets.py livre.pdf --sans-retour   → sans les petits liens « ↩ sommaire »

LES GRANDES ÉTAPES (fonction analyser_livre puis generer_pdf)
    1. OCR des pages sans texte ............................ ocr_si_necessaire
    2. Lecture des lignes de chaque page (texte + position) . lire_lignes
    3. Repérage des pages du sommaire (début ET fin) ........ trouver_pages_sommaire
    4. Extraction des entrées (titre, page, niveau, zone) ... extraire_entrees
    5. Recalage page imprimée → page PDF + vérification ..... recaler_entrees
    6. Écriture des signets et des liens dans une copie ..... generer_pdf
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

import pymupdf
from rapidfuzz import fuzz

# =============================================================================
# Réglages (on peut les ajuster si un livre résiste)
# =============================================================================
FENETRE = 4              # on cherche chaque titre à ± 4 pages de la page estimée
SEUIL_CONFIRME = 85      # similarité (sur 100) pour dire « titre retrouvé sur la page »
SEUIL_CANDIDAT = 75      # en dessous, une ligne n'est même pas considérée
BANDE_MARGE = 0.12       # 12 % en haut et en bas de page : zone des en-têtes et des folios
ZONE_SOMMAIRE = 0.25     # on cherche le sommaire dans le premier et le dernier quart du livre
MOTS_CLES_SOMMAIRE = ("table des matières", "sommaire", "contents", "table of contents")

CONFIRME = "confirmé"
DOUTEUX = "douteux"


# =============================================================================
# Structures de données
# =============================================================================
@dataclass(slots=True)
class Mot:
    x0: float
    y0: float
    x1: float
    y1: float
    texte: str


@dataclass
class Ligne:
    """Une ligne visuelle d'une page : ses mots (avec positions) et sa hauteur."""
    mots: list
    texte: str
    x0: float
    y0: float
    x1: float
    y1: float
    hauteur: float           # hauteur typique des mots ≈ taille de la police


@dataclass
class Entree:
    """Une entrée du sommaire = un futur signet."""
    titre: str
    page_imprimee: str = ""   # tel qu'imprimé dans le sommaire : "15", "xii"… ("" si absent)
    niveau: int = 1           # 1 = chapitre, 2 = section, …
    page_sommaire: int = -1   # page du PDF (0 = première) où se trouve la ligne du sommaire
    zones: list = field(default_factory=list)   # rectangles (x0, y0, x1, y1) à rendre cliquables
    page_pdf: int = -1        # page cible dans le PDF (0 = première page du fichier)
    statut: str = DOUTEUX
    remarque: str = ""
    # informations internes utiles au calcul
    x0: float = 0.0
    hauteur: float = 0.0
    sans_numero: bool = False
    numero_illisible: bool = False   # « titre ........ » dont le numéro n'a pas pu être lu


@dataclass
class Analyse:
    """Tout ce qu'il faut pour (re)générer le PDF, après corrections éventuelles."""
    chemin_travail: str       # PDF de base (OCRisé si besoin) — l'original n'est jamais modifié
    entrees: list
    pages_sommaire: list
    nb_pages: int
    pages_ocr: int = 0
    avertissements: list = field(default_factory=list)
    ctx: "Contexte | None" = field(default=None, repr=False)

    @property
    def sommaire_trouve(self):
        return bool(self.entrees)


def _signaler(progression, fraction, message):
    """Transmet l'avancement à l'interface (ou à la ligne de commande)."""
    if progression is not None:
        progression(max(0.0, min(1.0, fraction)), message)


# =============================================================================
# Petits outils sur le texte
# =============================================================================
_CONFUSIONS_OCR = str.maketrans({"1": "l", "i": "l", "|": "l", "!": "l", "0": "o"})


def normaliser(texte):
    """Minuscules, sans accents ni ponctuation, et confusions d'OCR neutralisées
    (l/1/I/|, O/0) : « Chapitre 1 – Espaces » → « chapltre l espaces »."""
    t = unicodedata.normalize("NFKD", texte)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    t = t.replace("œ", "oe").replace("æ", "ae").translate(_CONFUSIONS_OCR)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return t.strip()


_KW = tuple(normaliser(k) for k in MOTS_CLES_SOMMAIRE)
_MOTS_NUMEROTATION = {normaliser(m) for m in (
    "chapitre", "chap", "partie", "annexe", "appendice", "livre", "leçon", "lecon",
    "chapter", "part", "section", "tome")}


def coeur(texte_normalise):
    """Retire la numérotation au début : « chapltre 2 un tltre » → « un tltre »."""
    mots = texte_normalise.split()
    while len(mots) > 1 and (mots[0] in _MOTS_NUMEROTATION
                             or re.fullmatch(r"[0-9lvxcdmo]{1,4}|[a-z]", mots[0])):
        mots.pop(0)
    return " ".join(mots)


RE_ROMAIN = re.compile(r"m{0,4}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})")
_VALEURS_ROMAINES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def valeur_romaine(t):
    total = 0
    for a, b in zip(t, t[1:] + " "):
        v = _VALEURS_ROMAINES[a]
        total += -v if b != " " and _VALEURS_ROMAINES[b] > v else v
    return total


def lire_numero(jeton):
    """Reconnaît un numéro de page : ('a', 15) pour « 15 », ('r', 12) pour « xii ».
    Tolère les confusions d'OCR (« l5 » → 15). Renvoie None sinon."""
    t = jeton.strip(".,;:·…_•")
    if not t:
        return None
    if t.isdigit() and len(t) <= 4:
        return ("a", int(t))
    if len(t) <= 4 and re.fullmatch(r"[0-9lI|O]+", t) and any(c.isdigit() for c in t):
        return ("a", int(t.translate(str.maketrans("lI|O", "1110"))))
    if len(t) <= 7 and (t.islower() or t.isupper()) and RE_ROMAIN.fullmatch(t.lower()):
        return ("r", valeur_romaine(t.lower()))
    return None


def est_points_de_suite(jeton):
    return bool(re.fullmatch(r"[.·…_•]+|-{3,}", jeton))


def contient_mot_cle_sommaire(ligne):
    norm = normaliser(ligne.texte)
    return len(norm.split()) <= 6 and any(k in norm for k in _KW)


# =============================================================================
# Étape 1 — OCR des pages sans texte
# =============================================================================
def page_a_du_texte(page):
    return len(page.get_text("text").strip()) >= 3


def pages_a_ocriser(chemin_pdf):
    """Pages sans couche texte qui contiennent une image (les pages blanches sont ignorées)."""
    with pymupdf.open(chemin_pdf) as doc:
        return [i for i, page in enumerate(doc)
                if not page_a_du_texte(page) and page.get_images()]


def ocr_si_necessaire(chemin_pdf, dossier_travail, progression=None):
    """Lance ocrmypdf --skip-text si au moins une page n'a pas de texte.
    Renvoie (chemin du PDF à utiliser, liste des pages OCRisées, avertissement)."""
    a_faire = pages_a_ocriser(chemin_pdf)
    if not a_faire:
        return chemin_pdf, [], ""
    try:
        import ocrmypdf
        import progression_ocr
    except ImportError:
        return chemin_pdf, [], ("ocrmypdf n'est pas installé : les pages scannées "
                                f"({len(a_faire)}) n'ont pas pu être lues.")

    ocr_commence = []

    def rappel(fait, total, description):
        if total and "ocr" in (description or "").lower():
            ocr_commence.append(True)
            _signaler(progression, 0.4 * fait / total, f"OCR : page {int(fait)}/{int(total)}")
        elif ocr_commence:
            _signaler(progression, 0.4, "OCR : finalisation…")
        else:
            _signaler(progression, 0.0, f"OCR : préparation ({len(a_faire)} pages scannées)…")

    sortie = os.path.join(dossier_travail, "livre_ocr.pdf")
    _signaler(progression, 0.0, f"OCR : {len(a_faire)} pages scannées à lire…")
    for langues in (["fra", "eng"], ["eng"]):
        progression_ocr.rappel = rappel
        try:
            ocrmypdf.ocr(chemin_pdf, sortie, language=langues, skip_text=True,
                         output_type="pdf", optimize=0, progress_bar=True, use_threads=True,
                         plugins=["progression_ocr"])    # par son nom : même module, même rappel
            message = "" if langues != ["eng"] else (
                "Langue française de Tesseract absente : OCR fait en anglais seulement.")
            return sortie, a_faire, message
        except Exception as erreur:      # langue manquante, Tesseract absent, PDF chiffré…
            texte_erreur = str(erreur)
            if langues == ["fra", "eng"] and "fra" in texte_erreur.lower():
                continue
            return chemin_pdf, [], f"L'OCR a échoué ({type(erreur).__name__} : {texte_erreur[:200]})."
        finally:
            progression_ocr.rappel = None
    return chemin_pdf, [], "L'OCR a échoué."


RE_POINTS_DE_SUITE = re.compile(r"(?:[.·…_•]\s*){3,}")


def _finit_par_des_points(ligne):
    """Ligne « titre ......... » dont le numéro de page manque (oublié par l'OCR).
    Les points peuvent être suivis de restes d'OCR : « ........ 0... cc ccc ee »."""
    if len(ligne.mots) < 2 or lire_numero(ligne.mots[-1].texte.strip(".·…_•")):
        return False
    return bool(RE_POINTS_DE_SUITE.search(ligne.texte, 1))


def _isoler_numero(pix):
    """Dans l'image « ....... 15 », trouve les colonnes de pixels du numéro : en partant
    de la droite, on garde les colonnes où l'encre est haute (les points de suite,
    eux, sont bas). Renvoie (gauche, droite) en pixels, ou None."""
    w, h, s = pix.width, pix.height, pix.samples
    etendue = []
    for x in range(w):
        encre = [y for y in range(h) if s[y * w + x] < 128]
        etendue.append(max(encre) - min(encre) + 1 if encre else 0)
    plus_haut = max(etendue, default=0)
    if plus_haut == 0:
        return None
    haut = [e >= 0.45 * plus_haut for e in etendue]
    x = w - 1
    while x >= 0 and not haut[x]:
        x -= 1
    if x < 0:
        return None
    droite = gauche = x
    trou = 0
    while x >= 0:
        if haut[x]:
            gauche, trou = x, 0
        else:
            trou += 1
            if trou > 0.5 * plus_haut:        # grand blanc : on a dépassé le numéro
                break
        x -= 1
    return gauche, droite


def _avec_marge(pix, marge=40):
    """Ajoute une marge blanche autour d'une image (Tesseract lit mieux)."""
    grand = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, pix.width + 2 * marge,
                                                         pix.height + 2 * marge), False)
    grand.clear_with(255)
    pix.set_origin(marge, marge)
    grand.copy(pix, pix.irect)
    return grand.tobytes("png")


def _tesseract_numero(tesseract, image_png):
    """Lit un numéro de page isolé. Les chiffres seuls sont difficiles pour Tesseract :
    on essaie « une ligne » (7), puis « un mot » (8), puis « un caractère » (10)."""
    for mode in ("7", "8", "10"):
        try:
            resultat = subprocess.run(
                [tesseract, "stdin", "stdout", "--psm", mode, "-l", "eng",
                 "-c", "tessedit_char_whitelist=0123456789ivxlcdmIVXLCDM"],
                input=image_png, capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        texte = resultat.stdout.decode("utf-8", "replace").strip()
        if texte and " " not in texte and lire_numero(texte):
            return texte
    return None


def relire_numeros_du_sommaire(chemin_pdf, p, lignes, minimum=4):
    """Sur un sommaire scanné, Tesseract oublie souvent des numéros de page, isolés à
    droite. Si une page a au moins `minimum` lignes « titre ........ » sans numéro,
    on isole, pour chacune, le numéro à droite des points de suite et on le relit seul.
    Chaque numéro retrouvé reste ainsi sur SA ligne.
    Renvoie les nouvelles lignes de la page (ou les anciennes si rien n'a changé)."""
    from concurrent.futures import ThreadPoolExecutor

    orphelines = [l for l in lignes if _finit_par_des_points(l)]
    tesseract = shutil.which("tesseract")
    if not orphelines or len(orphelines) < minimum or not tesseract:
        return lignes
    zoom = 400 / 72
    matrice = pymupdf.Matrix(zoom, zoom)
    with pymupdf.open(chemin_pdf) as doc:
        page = doc[p]
        mots = list(page.get_text("words"))
        morceaux = []
        for l in orphelines:
            h = l.y1 - l.y0
            zone = pymupdf.Rect(l.x1 + 0.5, l.y0 - 0.3 * h, page.rect.x1 - 4, l.y1 + 0.3 * h)
            if zone.width < 4:
                continue
            bornes = _isoler_numero(page.get_pixmap(matrix=matrice, clip=zone, colorspace=pymupdf.csGRAY))
            if bornes is None:
                continue
            numero = pymupdf.Rect(zone.x0 + (bornes[0] - 2) / zoom, zone.y0,
                                  zone.x0 + (bornes[1] + 3) / zoom, zone.y1)
            image = _avec_marge(page.get_pixmap(matrix=matrice, clip=numero, colorspace=pymupdf.csGRAY))
            morceaux.append(((numero.x0, l.y0, numero.x1, l.y1), image))
    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as executeur:
        lectures = list(executeur.map(lambda m: _tesseract_numero(tesseract, m[1]), morceaux))
    nouveaux = [rect + (texte,) for (rect, _), texte in zip(morceaux, lectures) if texte]
    if not nouveaux:
        return lignes
    return regrouper_en_lignes(mots + nouveaux)


# =============================================================================
# Étape 2 — Lecture des lignes de chaque page
# =============================================================================
def regrouper_en_lignes(mots_bruts):
    """Regroupe les mots d'une page en lignes visuelles (même hauteur sur la page)."""
    mots = [Mot(m[0], m[1], m[2], m[3], m[4]) for m in mots_bruts if m[4].strip()]
    mots.sort(key=lambda m: ((m.y0 + m.y1) / 2, m.x0))
    groupes = []                       # [y du centre, hauteur, liste de mots]
    for m in mots:
        yc, h = (m.y0 + m.y1) / 2, m.y1 - m.y0
        if groupes and abs(yc - groupes[-1][0]) <= 0.4 * max(h, groupes[-1][1]):
            groupes[-1][2].append(m)
        else:
            groupes.append([yc, h, [m]])
    lignes = []
    for _, _, ms in groupes:
        ms.sort(key=lambda m: m.x0)
        lignes.append(Ligne(mots=ms, texte=" ".join(m.texte for m in ms),
                            x0=min(m.x0 for m in ms), y0=min(m.y0 for m in ms),
                            x1=max(m.x1 for m in ms), y1=max(m.y1 for m in ms),
                            hauteur=statistics.median(m.y1 - m.y0 for m in ms)))
    return lignes


def lire_lignes(doc, progression=None, debut=0.4, fin=0.6):
    n = len(doc)
    toutes = []
    for i, page in enumerate(doc):
        toutes.append(regrouper_en_lignes(page.get_text("words")))
        if i % 25 == 0:
            _signaler(progression, debut + (fin - debut) * i / n, f"Lecture du texte : page {i + 1}/{n}")
    return toutes


# =============================================================================
# Étape 3 — Repérage des pages du sommaire
# =============================================================================
@dataclass
class LigneSommaire:
    """Une ligne d'une page candidate, découpée en « titre … numéro »."""
    ligne: Ligne
    titre: str = ""
    numero: str = ""
    type_num: str = ""        # "a" (arabe), "r" (romain) ou "" (pas de numéro)
    valeur: int = 0
    x1_num: float = 0.0
    points: bool = False      # présence de points de suite
    ecart: float = 0.0        # espace blanc entre la fin du titre et le numéro
    valide: bool = False      # ressemble vraiment à une entrée de sommaire


def decouper_ligne(ligne):
    """« 1.1 Produit scalaire . . . . . 15 » → titre « 1.1 Produit scalaire », numéro « 15 »."""
    res = LigneSommaire(ligne)
    if len(ligne.mots) < 2 and not re.search(r"[.·…_•]{2}", ligne.texte):
        return res
    dernier = ligne.mots[-1]
    elements = [(m.texte, m.x1) for m in ligne.mots[:-1]]     # (texte, bord droit)
    num_txt = dernier.texte
    # Cas « scalaire.........15 » (points et numéro collés au dernier mot)
    colle = re.match(r"^(.*?)[.·…_•]{2,}([^.·…_•\s]+)\.?$", num_txt)
    if colle and lire_numero(colle.group(2)):
        res.points = True
        if colle.group(1):
            elements.append((colle.group(1), dernier.x0))
        num_txt = colle.group(2)
    num = lire_numero(num_txt)
    if num is None:
        return res
    # On enlève les points de suite à la fin du titre
    while elements and est_points_de_suite(elements[-1][0]):
        elements.pop()
        res.points = True
    if elements:
        t, x1 = elements[-1]
        nettoye = t.rstrip(".·…_•")
        if len(t) - len(nettoye) >= 2:
            res.points = True
        elements[-1] = (nettoye, x1)
    elements = [e for e in elements if e[0] and not est_points_de_suite(e[0])]
    titre = " ".join(e[0] for e in elements).strip()
    if sum(c.isalpha() for c in titre) < 2:
        return res
    res.titre, res.numero = titre, num_txt.strip(".,;:")
    res.type_num, res.valeur = num
    res.x1_num = dernier.x1
    res.ecart = max(0.0, dernier.x0 - elements[-1][1])
    return res


def analyser_page_sommaire(lignes):
    """Découpe chaque ligne et décide lesquelles sont de vraies entrées de sommaire.
    Indice clé : des points de suite, un grand blanc avant le numéro, ou des numéros
    alignés en colonne à droite."""
    analyses = [decouper_ligne(l) for l in lignes]
    surs = [a.x1_num for a in analyses
            if a.type_num == "a" and (a.points or a.ecart >= 1.5 * a.ligne.hauteur)]
    colonne = statistics.median(surs) if len(surs) >= 3 else None
    for a in analyses:
        if not a.type_num:
            continue
        aligne = colonne is not None and abs(a.x1_num - colonne) <= max(6.0, 0.6 * a.ligne.hauteur)
        if a.type_num == "a":
            a.valide = a.points or a.ecart >= 1.5 * a.ligne.hauteur or aligne
        else:                                   # chiffres romains : plus exigeant
            a.valide = a.points or aligne
    return analyses, colonne


def ressemble_a_un_sommaire(lignes):
    """Renvoie (est un sommaire ?, nombre d'entrées, mot-clé présent ?)."""
    if not lignes:
        return False, 0, False
    analyses, _ = analyser_page_sommaire(lignes)
    nb = sum(a.valide for a in analyses)
    mot_cle = any(contient_mot_cle_sommaire(l) for l in lignes)
    est = (nb >= 4 and nb >= 0.4 * len(lignes)) or (mot_cle and nb >= 2)
    return est, nb, mot_cle


def _part_croissante(valeurs):
    if len(valeurs) < 2:
        return 1.0
    return sum(b >= a for a, b in zip(valeurs, valeurs[1:])) / (len(valeurs) - 1)


def trouver_pages_sommaire(lignes_par_page):
    """Cherche le sommaire au début et à la fin du livre. Si plusieurs blocs de pages
    y ressemblent (sommaire abrégé + table détaillée, mini-sommaires…), on garde le
    plus riche dont les numéros de page sont globalement croissants (≠ un index)."""
    n = len(lignes_par_page)
    zone = max(30, int(n * ZONE_SOMMAIRE))
    pages = sorted(set(range(min(zone, n))) | set(range(max(0, n - zone), n)))
    infos = {p: ressemble_a_un_sommaire(lignes_par_page[p]) for p in pages}
    candidates = [p for p in pages if infos[p][0]]
    blocs = []
    for p in candidates:
        if blocs and p - blocs[-1][-1] <= 2:
            blocs[-1].append(p)
        else:
            blocs.append([p])
    meilleur, meilleur_score = [], 0
    for bloc in blocs:
        # on récupère une éventuelle page intermédiaire peu remplie (p. ex. titres de parties)
        bloc = [p for p in range(bloc[0], bloc[-1] + 1) if p in bloc or infos.get(p, (0, 0, 0))[1] >= 1]
        valeurs = []
        for p in bloc:
            analyses, _ = analyser_page_sommaire(lignes_par_page[p])
            valeurs += [a.valeur for a in analyses if a.valide and a.type_num == "a"]
        if _part_croissante(valeurs) < 0.7:
            continue                                   # numéros en désordre : un index ?
        score = sum(infos[p][1] for p in bloc) + 15 * any(infos[p][2] for p in bloc)
        if score > meilleur_score:
            meilleur, meilleur_score = bloc, score
    return meilleur


# =============================================================================
# Étape 4 — Extraction des entrées du sommaire
# =============================================================================
def _ligne_a_ignorer(ligne):
    """Titre « Table des matières », en-tête courant, folio isolé, mot « Pages »…"""
    if contient_mot_cle_sommaire(ligne):
        return True
    if len(ligne.mots) == 1 and lire_numero(ligne.texte):
        return True
    return normaliser(ligne.texte) in ("page", "pages", "pp")


def _prolonge(precedente, suivante, x_gauche, x_droite, x0_debut):
    """La ligne `suivante` est-elle la suite d'un titre coupé sur `precedente` ?
    Oui si elles sont proches verticalement, si `precedente` va presque jusqu'au bord
    droit (le texte a été renvoyé à la ligne) et si `suivante` n'est pas moins en retrait."""
    proche = suivante.y0 - precedente.y1 < 0.9 * precedente.hauteur
    pleine = precedente.x1 >= x_gauche + 0.6 * (x_droite - x_gauche)
    return proche and pleine and suivante.x0 >= x0_debut - 3


def _assembler_titre(morceaux):
    """Recolle un titre coupé, en gérant les coupures avec trait d'union."""
    titre = ""
    for m in morceaux:
        m = m.strip()
        if titre.endswith("-") and m[:1].islower() and titre[-2:-1].isalpha():
            titre = titre[:-1] + m
        else:
            titre = (titre + " " + m).strip()
    # Tout ce qui suit les premiers points de suite n'est pas le titre (restes d'OCR)
    points = RE_POINTS_DE_SUITE.search(titre)
    if points and sum(c.isalpha() for c in titre[:points.start()]) >= 2:
        titre = titre[:points.start()]
    titre = re.sub(r"\s*[.·…_•]{2,}\s*", " ", titre)
    titre = re.sub(r"\s+", " ", titre).strip(" .")
    return corriger_majuscules(retirer_faux_points(titre))


# ---- Nettoyage des titres lus par OCR -----------------------------------------
def _bruit_fort(mot):
    """Morceau qui ne peut être qu'un point de suite mal lu par l'OCR :
    « ... », « 0.0.0 », « 2.2 », « 00.0,5 », « eee », « cece »…"""
    m = mot.lower()
    if re.fullmatch(r"[.,:;'`·•_~\-–—…|?!]+", m):
        return True
    if re.search(r"[#@®©*%?]", m):                    # « oeeeee?e#e#e##s », « @ », « ® »
        reste = re.sub(r"[^a-z]", "", m)              # mais « @inversion » (= d'inversion) reste
        return len(reste) <= 2 or _bruit_de_lettres(reste)
    if re.fullmatch(r"[0-9.,:;'`\-–—]*[.,:;\-–—][0-9.,:;'`\-–—]*", m) and any(c.isdigit() for c in m):
        return True                                   # « 0.0.0 », « 20-0-00 », « --04 »
    return len(m) >= 2 and _bruit_de_lettres(m)


def _bruit_de_lettres(m):
    """« e », « ee », « ees », « eens », « cece », « nce », « ccc »… : des points de
    suite que l'OCR a pris pour des lettres (presque uniquement des e et des c)."""
    return (bool(re.fullmatch(r"[ecnos]{1,12}", m))
            and sum(c in "ec" for c in m) >= len(m) / 2)


def _bruit_faible(mot):
    """Morceau qui peut être du bruit s'il est entouré d'autre bruit (« 2 », « 0 », « ns »)."""
    m = mot.lower()
    petit_mot_de_bruit = (len(mot) <= 2 and mot.isalpha() and mot.islower()
                          and mot not in MOTS_COURTS_FRANCAIS)
    return _bruit_fort(m) or m.isdigit() or _bruit_de_lettres(m) or petit_mot_de_bruit


MOTS_COURTS_FRANCAIS = {"de", "et", "la", "le", "un", "du", "au", "ou", "en", "si", "sa", "se",
                        "ne", "il", "on", "à", "y", "l", "d"}


# Mots après lesquels un nombre final fait partie du titre (« Chapitre 2 », « Degré 3 »)
MOTS_SUIVIS_D_UN_NOMBRE = {normaliser(m) for m in (
    "chapitre", "partie", "annexe", "appendice", "section", "tome", "livre", "leçon",
    "dimension", "degré", "ordre", "rang", "classe", "type", "niveau", "exercice",
    "exemple", "théorème", "lemme", "figure", "planche", "chapter", "part")}


def retirer_faux_points(titre):
    """Retire, en fin de titre, les points de suite que l'OCR a lus comme des
    caractères : « Treillis 2 ee » → « Treillis », « Groupe 0.0020005 » → « Groupe ».
    Un vrai numéro est conservé : « Chapitre 2 » reste « Chapitre 2 »."""
    mots = titre.split()
    debut = len(mots)
    while debut > 1 and _bruit_faible(mots[debut - 1]):
        debut -= 1
    queue = mots[debut:]
    if len(queue) >= 2 or (len(queue) == 1 and _bruit_fort(queue[0])):
        mots = mots[:debut]
    # Un nombre seul à la fin d'un titre ordinaire (« … de groupes 20 ») est un reste d'OCR
    if (len(mots) >= 2 and mots[-1].isdigit()
            and normaliser(mots[-2]) not in MOTS_SUIVIS_D_UN_NOMBRE
            and not re.search(r"[=<>+^]", titre)):
        mots = mots[:-1]
    return " ".join(mots).strip(" .,-–—")


def corriger_majuscules(titre):
    """Majuscules mal lues par l'OCR : « COrpS » → « Corps » ; un titre tout en
    capitales (« ANNEAUX ET CORPS ») passe en minuscules, avec une majuscule au début
    et après « – » ou « . ». Les chiffres romains (« II ») sont conservés."""
    lettres = [c for c in titre if c.isalpha()]
    tout_majuscules = len(lettres) >= 4 and all(c.isupper() for c in lettres)
    corriges = []
    for mot in titre.split():
        majuscule_interne = any(a.islower() and b.isupper() for a, b in zip(mot, mot[1:]))
        romain = bool(RE_ROMAIN.fullmatch(mot.lower().strip(".,:;")))
        if majuscule_interne:
            mot = mot[0] + mot[1:].lower()
        elif tout_majuscules and not romain:
            mot = mot.lower()
        precedent = corriges[-1] if corriges else ""
        if tout_majuscules and (not corriges or precedent in ("–", "—", "-", ":") or precedent.endswith(".")):
            mot = mot[:1].upper() + mot[1:]
        corriges.append(mot)
    return " ".join(corriges)


def _entree_sans_numero(lignes, page):
    """Une ligne sans numéro (p. ex. « Première partie ») devient une entrée provisoire."""
    titre = _assembler_titre([l.texte for l in lignes])
    zones = [(l.x0, l.y0, l.x1, l.y1) for l in lignes]
    return Entree(titre=titre, niveau=1, page_sommaire=page, zones=zones,
                  x0=lignes[0].x0, hauteur=lignes[0].hauteur, sans_numero=True)


RE_TITRE_DE_PARTIE = re.compile(
    r"(?i)^(\S+\s+)?(partie|livre|tome|chapitre|annexes?|appendices?|part|chapter)\b")


def extraire_entrees(lignes_par_page, pages_sommaire):
    """Transforme les lignes du sommaire en entrées : titre, page imprimée, zones cliquables."""
    entrees = []
    for p in pages_sommaire:
        analyses, colonne = analyser_page_sommaire(lignes_par_page[p])
        valides = [a for a in analyses if a.valide]
        if not valides:
            continue
        x_droite = colonne or max(a.x1_num for a in valides)
        x_gauche = min(a.ligne.x0 for a in valides)
        en_attente = []                     # lignes sans numéro (début d'un titre coupé ?)
        for a in analyses:
            ligne = a.ligne
            if _ligne_a_ignorer(ligne):          # « Table des matières », en-tête, folio
                continue
            if a.valide:
                debut = []
                if en_attente and _prolonge(en_attente[-1], ligne, x_gauche, x_droite, en_attente[0].x0):
                    debut = en_attente
                elif en_attente:
                    entrees.append(_entree_sans_numero(en_attente, p))
                en_attente = []
                lignes = debut + [ligne]
                droite = max(x_droite, a.x1_num)
                entrees.append(Entree(
                    titre=_assembler_titre([l.texte for l in debut] + [a.titre]),
                    page_imprimee=a.numero, page_sommaire=p,
                    zones=[(l.x0, l.y0, droite, l.y1) for l in lignes],
                    x0=lignes[0].x0, hauteur=lignes[0].hauteur))
            elif _finit_par_des_points(ligne):
                # « Topologie générale ........ » : une vraie entrée, mais son numéro est
                # illisible. Surtout ne pas la coller à la ligne suivante comme un titre coupé.
                if en_attente and _prolonge(en_attente[-1], ligne, x_gauche, x_droite, en_attente[0].x0):
                    groupe = en_attente + [ligne]
                else:
                    if en_attente:
                        entrees.append(_entree_sans_numero(en_attente, p))
                    groupe = [ligne]
                en_attente = []
                entree = _entree_sans_numero(groupe, p)
                entree.numero_illisible = True
                entrees.append(entree)
            else:
                if en_attente and not _prolonge(en_attente[-1], ligne, x_gauche, x_droite, en_attente[0].x0):
                    entrees.append(_entree_sans_numero(en_attente, p))
                    en_attente = []
                en_attente.append(ligne)
        if en_attente:
            entrees.append(_entree_sans_numero(en_attente, p))
    return _filtrer_sans_numero(entrees)


def _filtrer_sans_numero(entrees):
    """Ne garde une ligne sans numéro que si elle ressemble à un titre de partie :
    mot « Partie », « Chapitre »… ou police plus grande que les autres entrées."""
    hauteurs = [e.hauteur for e in entrees if not e.sans_numero]
    if not hauteurs:
        return []
    h_med = statistics.median(hauteurs)
    gardees = []
    for e in entrees:
        if e.sans_numero and not e.numero_illisible:
            lettres = sum(c.isalpha() for c in e.titre)
            if lettres < 3 or len(e.titre.split()) > 15:
                continue
            if not (RE_TITRE_DE_PARTIE.match(e.titre) or e.hauteur >= 1.1 * h_med):
                continue
        gardees.append(e)
    # une ligne sans numéro tout à la fin n'a pas de suivante dont copier la page
    while gardees and gardees[-1].sans_numero:
        gardees.pop()
    return gardees


# ---- Niveaux hiérarchiques -------------------------------------------------
def niveau_par_numerotation(titre):
    """« 1.2.3 Titre » → 3 ; « Chapitre 4 … » → 1 ; « Première partie » → 0 ; sinon None."""
    t = titre.strip()
    if re.match(r"(?i)^(\S+\s+)?(partie|livre|tome|part)\b", t):
        return 0
    if re.match(r"(?i)^(chapitre|chapter|annexe|appendice|leçon)\b", t):
        return 1
    m = re.match(r"^(\d+(?:\.\d+)*)\.?\s", t)
    return m.group(1).count(".") + 1 if m else None


def _groupes_d_indentation(entrees):
    """Regroupe les retraits à gauche (x0) des entrées : chaque groupe = un niveau."""
    tol = max(4.0, 0.5 * statistics.median(e.hauteur for e in entrees))
    xs = sorted(e.x0 for e in entrees)
    groupes = [[xs[0]]]
    for x in xs[1:]:
        if x - groupes[-1][-1] <= tol:
            groupes[-1].append(x)
        else:
            groupes.append([x])
    # les retraits isolés (un titre centré…) ne comptent pas comme un niveau
    return [statistics.mean(g) for g in groupes if len(g) >= 2][:4], tol


def attribuer_niveaux(entrees):
    """Niveau = indentation si elle est parlante, sinon numérotation 1 / 1.1 / 1.1.2."""
    if not entrees:
        return
    centres, tol = _groupes_d_indentation(entrees)
    if len(centres) >= 2:
        for e in entrees:
            niveau = 1
            for k, c in enumerate(centres):
                if e.x0 >= c - tol:
                    niveau = k + 1
            e.niveau = niveau
    else:
        niveaux = [niveau_par_numerotation(e.titre) for e in entrees]
        decalage = 1 if 0 in niveaux else 0
        for e, n in zip(entrees, niveaux):
            e.niveau = 1 if n is None else n + decalage
    normaliser_niveaux(entrees)


def normaliser_niveaux(entrees):
    """Un signet ne peut descendre que d'un niveau à la fois (exigence du format PDF)."""
    precedent = 0
    for e in entrees:
        e.niveau = max(1, min(e.niveau, precedent + 1))
        precedent = e.niveau


# =============================================================================
# Étape 5 — Recalage : page imprimée → page PDF
# =============================================================================
def lire_folios(lignes_par_page, hauteurs):
    """Pour chaque page, les numéros lus au tout début ou à la fin des lignes du haut
    et du bas de page (là où sont imprimés les numéros de page)."""
    n = len(lignes_par_page)
    lectures = []
    for p, lignes in enumerate(lignes_par_page):
        h = hauteurs[p]
        haut = [l for l in lignes if l.y1 <= BANDE_MARGE * h][:2]
        bas = [l for l in lignes if l.y0 >= (1 - BANDE_MARGE) * h][-2:]
        trouves = []
        for l in haut + bas[::-1]:
            for mot in {id(l.mots[0]): l.mots[0], id(l.mots[-1]): l.mots[-1]}.values():
                num = lire_numero(mot.texte)
                if num and ((num[0] == "a" and 1 <= num[1] <= 2 * n + 50)
                            or (num[0] == "r" and num[1] <= 80)):
                    trouves.append(num)
        lectures.append(trouves)
    return lectures


def folios_fiables(lectures):
    """Ne garde que les numéros de page confirmés par une page voisine (à ± 3 pages)
    avec le même décalage. Une note « 1 Voir… » ou « Planche I » est ainsi écartée."""
    n = len(lectures)
    ensembles = [set(l) for l in lectures]
    fiables = {}
    for p, trouves in enumerate(lectures):
        for t, v in trouves:
            decalage = p - v
            if any((t, q - decalage) in ensembles[q]
                   for q in range(max(0, p - 3), min(n, p + 4)) if q != p):
                fiables[p] = (t, v)
                break
    # Deux ou trois lectures isolées dans tout le livre = coïncidences (nombres du texte)
    for type_num in ("a", "r"):
        lectures_type = [p for p, (t, v) in fiables.items() if t == type_num]
        if len(lectures_type) < max(4, 0.05 * n):
            for p in lectures_type:
                del fiables[p]
    return fiables


class Correspondance:
    """Table « page imprimée → page PDF », construite à partir :
       a) des PageLabels du PDF s'ils existent ;
       b) des numéros imprimés lus sur les pages (absorbe les sauts : planches…)."""

    def __init__(self, doc, fiables):
        self.n = len(doc)
        self.labels = {}
        if doc.get_page_labels():
            for i in range(self.n):
                lab = doc[i].get_label().strip().lower()
                if lab and lab not in self.labels:
                    self.labels[lab] = i
        self.lectures = {"a": sorted((p, v) for p, (t, v) in fiables.items() if t == "a"),
                         "r": sorted((p, v) for p, (t, v) in fiables.items() if t == "r")}

    def _depuis_lectures(self, type_num, valeur):
        lectures = self.lectures[type_num]
        if not lectures:
            return None
        for p, v in lectures:
            if v == valeur:
                return p
        dessous = [(p, v) for p, v in lectures if v < valeur]
        dessus = [(p, v) for p, v in lectures if v > valeur]
        if dessous and dessus:
            pb, vb = max(dessous, key=lambda x: (x[1], x[0]))
            ph, vh = min(dessus, key=lambda x: (x[1], x[0]))
            depuis_bas, depuis_haut = pb + (valeur - vb), ph - (vh - valeur)
            # Si un saut (planche…) se trouve entre les deux, on part du côté le plus proche ;
            # la recherche du titre tranchera.
            return depuis_bas if (valeur - vb) <= (vh - valeur) else depuis_haut
        if dessous:
            pb, vb = max(dessous, key=lambda x: (x[1], x[0]))
            return pb + (valeur - vb)
        ph, vh = min(dessus, key=lambda x: (x[1], x[0]))
        return ph - (vh - valeur)

    def estimations(self, page_imprimee):
        """Liste des pages PDF probables, avec la source de chaque estimation."""
        resultats = []
        if not page_imprimee:
            return resultats
        if page_imprimee.lower() in self.labels:
            resultats.append((self.labels[page_imprimee.lower()], "PageLabels"))
        num = lire_numero(page_imprimee)
        if num:
            p = self._depuis_lectures(*num)
            if p is not None:
                resultats.append((p, "numéros de page"))
        return [(min(max(p, 0), self.n - 1), s) for p, s in resultats]


class Contexte:
    """Données de travail sur le livre : lignes de chaque page, en-têtes courants, etc."""

    def __init__(self, doc, lignes_par_page, pages_sommaire):
        self.lignes = lignes_par_page
        self.n = len(doc)
        self.hauteurs = [page.rect.height for page in doc]
        self.pages_sommaire = set(pages_sommaire)
        toutes = [l.hauteur for lignes in lignes_par_page for l in lignes]
        self.h_corps = statistics.median(toutes) if toutes else 10.0
        self.fiables = folios_fiables(lire_folios(lignes_par_page, self.hauteurs))
        self.correspondance = Correspondance(doc, self.fiables)
        self.en_tetes = self._reperer_en_tetes()
        self._cache = {}
        self._vote = "pas calculé"

    # ---- En-têtes courants ------------------------------------------------
    def _bords_de_page(self, p):
        lignes, h = self.lignes[p], self.hauteurs[p]
        bords = []
        if lignes and lignes[0].y1 <= BANDE_MARGE * h:
            bords.append(0)
        if len(lignes) > 1 and lignes[-1].y0 >= (1 - BANDE_MARGE) * h:
            bords.append(len(lignes) - 1)
        return bords

    def _reperer_en_tetes(self):
        """En-tête courant = 1re/dernière ligne de la page, dans la marge, dont le texte
        (sans chiffres) revient sur au moins 3 pages, ou qui porte le numéro de page."""
        def sans_chiffres(l):
            return re.sub(r"[\dl ]+", " ", normaliser(l.texte)).strip()

        compteur = Counter(sans_chiffres(self.lignes[p][i])
                           for p in range(self.n) for i in self._bords_de_page(p))
        repetes = {t for t, c in compteur.items() if c >= 3 and t}
        en_tetes = set()
        for p in range(self.n):
            for i in self._bords_de_page(p):
                l = self.lignes[p][i]
                porte_folio = p in self.fiables and any(
                    lire_numero(m.texte) == self.fiables[p] for m in (l.mots[0], l.mots[-1]))
                if sans_chiffres(l) in repetes or porte_folio:
                    en_tetes.add((p, i))
        return en_tetes

    # ---- Textes candidats d'une page (lignes seules ou 2 à 4 lignes collées) ----
    def candidats(self, p):
        if p in self._cache:
            return self._cache[p]
        utiles = [l for i, l in enumerate(self.lignes[p]) if (p, i) not in self.en_tetes]
        res = []
        for k in range(len(utiles)):
            morceaux, gros = [], True
            for j in range(k, min(k + 4, len(utiles))):
                l = utiles[j]
                if j > k and l.y0 - utiles[j - 1].y1 > 2.5 * l.hauteur:
                    break
                morceaux.append(l.texte)
                # « gros » seulement si TOUTES les lignes collées sont en gros caractères
                gros = gros and l.hauteur >= 1.18 * self.h_corps
                norm = normaliser(" ".join(morceaux))
                res.append((norm, coeur(norm), gros))
        self._cache[p] = res
        return res

    def similarite_sur_page(self, entree, p):
        """Meilleure ressemblance (0-100) entre le titre et une ligne de la page p,
        et indique si cette ligne est en gros caractères."""
        tn = normaliser(entree.titre)
        tc = coeur(tn)
        meilleur, gros_meilleur = 0.0, False
        for norm, cn, gros in self.candidats(p):
            s = fuzz.ratio(tn, norm)
            if len(tc) >= 4 and cn:
                s = max(s, fuzz.ratio(tc, cn))
                # Titre du sommaire un peu abrégé par rapport à l'intertitre en gros caractères
                # (mais pas un titre court perdu au milieu d'une ligne bien plus longue)
                if gros and len(tc) >= 8 and len(tc) <= len(cn) <= 1.6 * len(tc):
                    s = max(s, 0.95 * fuzz.partial_ratio(tc, cn))
            if s + 6 * gros > meilleur + 6 * gros_meilleur:
                meilleur, gros_meilleur = s, gros
        return meilleur, gros_meilleur

    def chercher(self, entree, centre, fenetre=FENETRE, bornes=None):
        """Cherche le titre autour de la page `centre`. Renvoie (page, similarité) ou None.
        Bonus aux lignes en gros caractères, pénalité selon l'éloignement."""
        debut, fin = max(0, centre - fenetre), min(self.n - 1, centre + fenetre)
        if bornes:
            debut, fin = max(debut, bornes[0]), min(fin, bornes[1])
        meilleur = None
        for p in range(debut, fin + 1):
            if p in self.pages_sommaire:
                continue
            s, gros = self.similarite_sur_page(entree, p)
            if s < SEUIL_CANDIDAT:
                continue
            score = s + 6 * gros - 2.5 * abs(p - centre)
            if meilleur is None or score > meilleur[0]:
                meilleur = (score, p, s)
        return (meilleur[1], meilleur[2]) if meilleur else None

    def decalage_par_vote(self, entrees):
        """Secours sans numéros de page lisibles : on cherche les premiers titres dans
        tout le livre et on retient le décalage « page PDF − page imprimée » le plus fréquent."""
        if self._vote != "pas calculé":
            return self._vote
        votes = Counter()
        for e in [e for e in entrees if lire_numero(e.page_imprimee or "x") and
                  lire_numero(e.page_imprimee)[0] == "a"][:25]:
            valeur = lire_numero(e.page_imprimee)[1]
            for p in range(self.n):
                if p not in self.pages_sommaire and self.similarite_sur_page(e, p)[0] >= 90:
                    votes[p - valeur] += 1
        self._vote = votes.most_common(1)[0][0] if votes else None
        return self._vote


def _estimations(entree, ctx, entrees):
    est = ctx.correspondance.estimations(entree.page_imprimee)
    num = lire_numero(entree.page_imprimee) if entree.page_imprimee else None
    if num and num[0] == "a":
        vote = ctx.decalage_par_vote(entrees)
        if vote is not None:
            est.append((min(max(num[1] + vote, 0), ctx.n - 1), "décalage moyen"))
    vues, uniques = set(), []
    for p, s in est:
        if p not in vues:
            vues.add(p)
            uniques.append((p, s))
    return uniques


def recaler_entrees(entrees, ctx, progression=None, debut=0.65, fin=0.95):
    """Donne à chaque entrée sa page PDF réelle et un statut confirmé / douteux."""
    # Une entrée sans numéro (titre de partie) prend la page imprimée de l'entrée suivante
    for i, e in enumerate(entrees):
        if e.sans_numero:
            suivante = next((x for x in entrees[i + 1:] if not x.sans_numero), None)
            e.page_imprimee = suivante.page_imprimee if suivante else ""
    for i, e in enumerate(entrees):
        _signaler(progression, debut + (fin - debut) * i / max(1, len(entrees)),
                  f"Recherche des chapitres… ({i + 1}/{len(entrees)})")
        _recaler_une(e, ctx, entrees)
        if e.sans_numero:
            e.page_imprimee = ""
    verifier_ordre(entrees, ctx)


def _recaler_une(e, ctx, entrees):
    estimations = _estimations(e, ctx, entrees)
    for centre, source in estimations:
        trouve = ctx.chercher(e, centre)
        if trouve and trouve[1] >= SEUIL_CONFIRME:
            e.page_pdf, e.statut = trouve[0], CONFIRME
            ecart = trouve[0] - centre
            e.remarque = f"titre retrouvé ({source}{', ' + format(ecart, '+d') if ecart else ''})"
            return
    if estimations:
        e.page_pdf, e.statut = estimations[0][0], DOUTEUX
        e.remarque = f"titre non retrouvé près de la page estimée ({estimations[0][1]})"
        return
    # Aucune estimation (p. ex. pages romaines sans folio) : recherche dans tout le livre
    trouve = ctx.chercher(e, ctx.n // 2, fenetre=ctx.n)
    if trouve and trouve[1] >= 90:
        e.page_pdf, e.statut, e.remarque = trouve[0], CONFIRME, "titre retrouvé (recherche globale)"
    else:
        e.page_pdf, e.statut, e.remarque = 0, DOUTEUX, "page introuvable : à corriger"


def verifier_ordre(entrees, ctx):
    """Les pages doivent croître dans l'ordre du sommaire. Une incohérence est
    toujours signalée (statut douteux), jamais corrigée en silence."""
    for i in range(1, len(entrees)):
        a, b = entrees[i - 1], entrees[i]
        num_a, num_b = lire_numero(a.page_imprimee or "-"), lire_numero(b.page_imprimee or "-")
        if num_a and num_b and num_a[0] == num_b[0] and num_b[1] < num_a[1]:
            b.statut = DOUTEUX
            b.remarque = "numéro du sommaire plus petit que le précédent (mal lu ?)"
        if b.page_pdf >= a.page_pdf:
            continue
        if a.statut == DOUTEUX and b.statut == CONFIRME:
            # C'est sans doute l'entrée précédente (non confirmée) qui est trop loin :
            # on la cherche entre l'entrée d'avant et celle-ci.
            borne = entrees[i - 2].page_pdf if i >= 2 else 0
            trouve = ctx.chercher(a, b.page_pdf, fenetre=2 * FENETRE, bornes=(borne, b.page_pdf))
            if trouve and trouve[1] >= SEUIL_CONFIRME:
                a.page_pdf, a.statut = trouve[0], CONFIRME
                a.remarque = "recalé avant l'entrée suivante pour respecter l'ordre du sommaire"
            else:
                a.page_pdf = max(borne, min(a.page_pdf, b.page_pdf))
                a.remarque = "ordre incohérent avec l'entrée suivante : page imposée, à vérifier"
            continue
        trouve = ctx.chercher(b, a.page_pdf, fenetre=2 * FENETRE, bornes=(a.page_pdf, ctx.n - 1))
        if trouve and trouve[1] >= SEUIL_CONFIRME:
            b.page_pdf, b.statut = trouve[0], CONFIRME
            b.remarque = "recalé après l'entrée précédente pour respecter l'ordre du sommaire"
        else:
            b.page_pdf = a.page_pdf
            for x in (a, b):
                x.statut = DOUTEUX
            b.remarque = "ordre incohérent avec l'entrée précédente : page imposée, à vérifier"


def verifier_entree(e, ctx):
    """Re-vérifie une entrée après correction : le titre est-il sur la page cible ?"""
    if ctx is None:
        return
    s, _ = ctx.similarite_sur_page(e, e.page_pdf) if 0 <= e.page_pdf < ctx.n else (0, False)
    e.statut = CONFIRME if s >= SEUIL_CONFIRME else DOUTEUX


# =============================================================================
# Analyse complète d'un livre (étapes 1 à 5)
# =============================================================================
def analyser_livre(chemin_pdf, dossier_travail, progression=None, faire_ocr=True):
    """Analyse le livre et renvoie un objet Analyse (sans encore écrire le PDF final)."""
    avertissements = []
    chemin_travail, pages_ocr = chemin_pdf, []
    with pymupdf.open(chemin_pdf) as doc:
        if doc.needs_pass:
            raise ValueError("Ce PDF est protégé par un mot de passe : impossible de le traiter.")
    if faire_ocr:
        _signaler(progression, 0.0, "Recherche des pages scannées…")
        chemin_travail, pages_ocr, message = ocr_si_necessaire(chemin_pdf, dossier_travail, progression)
        if message:
            avertissements.append(message)
    with pymupdf.open(chemin_travail) as doc:
        if doc.get_toc():
            avertissements.append(f"Ce PDF avait déjà {len(doc.get_toc())} signets : "
                                  "ils seront remplacés.")
        lignes = lire_lignes(doc, progression)
        _signaler(progression, 0.6, "Recherche du sommaire…")
        # Pages scannées du début et de la fin : colonne des numéros oubliée par l'OCR ?
        zone = max(30, int(len(doc) * ZONE_SOMMAIRE))
        for p in pages_ocr:
            if p < zone or p >= len(doc) - zone:
                lignes[p] = relire_numeros_du_sommaire(chemin_travail, p, lignes[p])
        pages_sommaire = trouver_pages_sommaire(lignes)
        # Sur les pages du sommaire, le moindre numéro oublié par l'OCR est relu
        for p in pages_sommaire:
            lignes[p] = relire_numeros_du_sommaire(chemin_travail, p, lignes[p], minimum=1)
        entrees = extraire_entrees(lignes, pages_sommaire) if pages_sommaire else []
        ctx = Contexte(doc, lignes, pages_sommaire)
        nb_pages = len(doc)
    analyse = Analyse(chemin_travail=chemin_travail, entrees=entrees,
                      pages_sommaire=pages_sommaire, nb_pages=nb_pages,
                      pages_ocr=len(pages_ocr), avertissements=avertissements, ctx=ctx)
    if not entrees:
        return analyse
    attribuer_niveaux(entrees)
    _signaler(progression, 0.65, "Recherche des chapitres…")
    recaler_entrees(entrees, ctx, progression)
    _signaler(progression, 0.95, "Analyse terminée.")
    return analyse


# =============================================================================
# Étape 6 — Écriture des signets et des liens (dans une COPIE du PDF)
# =============================================================================
def generer_pdf(analyse, chemin_sortie, liens_retour=True):
    """Écrit les signets et les liens du sommaire dans une copie du PDF de travail."""
    entrees = analyse.entrees
    normaliser_niveaux(entrees)
    with pymupdf.open(analyse.chemin_travail) as doc:
        n = len(doc)
        existants = _liens_existants(doc)
        doc.set_toc([[e.niveau, e.titre, min(max(e.page_pdf, 0), n - 1) + 1] for e in entrees])
        for e in entrees:
            if 0 <= e.page_sommaire < n:
                _lier_ligne_du_sommaire(doc[e.page_sommaire], e, min(max(e.page_pdf, 0), n - 1))
        if liens_retour and analyse.pages_sommaire:
            premiere_sommaire = min(analyse.pages_sommaire)
            pages_chapitres = sorted({e.page_pdf for e in entrees if e.niveau == 1
                                      and 0 <= e.page_pdf < n
                                      and e.page_pdf not in analyse.pages_sommaire})
            for p in pages_chapitres:
                _ajouter_lien_retour(doc[p], premiere_sommaire)
        _effacer_cadres(doc, existants)
        doc.save(chemin_sortie, garbage=1, deflate=True)
    return chemin_sortie


def _poser_lien(page, zone, cible):
    """Pose un lien interne (son cadre est rendu invisible par _effacer_cadres)."""
    page.insert_link({"kind": pymupdf.LINK_GOTO, "page": cible, "from": zone,
                      "to": pymupdf.Point(0, 0), "zoom": 0})


def _liens_existants(doc):
    return {p: {l["xref"] for l in doc[p].get_links()} for p in range(len(doc))}


def _effacer_cadres(doc, existants):
    """Cadre d'épaisseur nulle pour NOS liens (quel que soit le lecteur PDF).
    Les liens qui existaient déjà dans le PDF ne sont pas touchés."""
    for p in range(len(doc)):
        for lien in doc[p].get_links():
            if lien["xref"] and lien["xref"] not in existants[p]:
                doc.xref_set_key(lien["xref"], "Border", "[0 0 0]")


def _lier_ligne_du_sommaire(page, entree, cible):
    """Lien invisible sur toute la ligne (titre, points de suite, numéro)."""
    for x0, y0, x1, y1 in entree.zones:
        marge = 0.15 * (y1 - y0)
        _poser_lien(page, pymupdf.Rect(x0, y0 - marge, x1, y1 + marge), cible)


def _ajouter_lien_retour(page, page_sommaire):
    """Petit lien discret « ↩ sommaire » en haut à droite de la page."""
    r = page.rect
    zone = pymupdf.Rect(r.x1 - 90, r.y0 + 4, r.x1 - 8, r.y0 + 16)
    page.insert_htmlbox(zone, '<span style="font-family:sans-serif;font-size:7pt;'
                              'color:#888888">&#8617; sommaire</span>',
                        css="* {text-align:right}")
    _poser_lien(page, zone, page_sommaire)


# =============================================================================
# Bilan, corrections, liste texte, miniatures
# =============================================================================
def bilan(entrees):
    """« 42 signets posés, 40 confirmés, 2 douteux »."""
    n = len(entrees)
    c = sum(e.statut == CONFIRME for e in entrees)
    s = lambda k: "s" if k > 1 else ""
    return f"{n} signet{s(n)} posé{s(n)}, {c} confirmé{s(c)}, {n - c} douteux"


def decaler(analyse, indice, delta, et_suivantes=False):
    """Décale d'une ou plusieurs pages une entrée (et éventuellement toutes les suivantes)."""
    fin = len(analyse.entrees) if et_suivantes else indice + 1
    for e in analyse.entrees[indice:fin]:
        e.page_pdf = min(max(e.page_pdf + delta, 0), analyse.nb_pages - 1)
        verifier_entree(e, analyse.ctx)
        e.remarque = "corrigé à la main"


def entrees_vers_texte(entrees):
    """Liste modifiable : 2 espaces par niveau, « | page PDF », commentaire après « # »."""
    lignes_titres = ["  " * (e.niveau - 1) + e.titre for e in entrees]
    largeur = min(70, max((len(t) for t in lignes_titres), default=10) + 2)
    sortie = ["# Liste des signets. Modifiez-la puis réimportez-la.",
              "# 2 espaces par niveau = hiérarchie ; le nombre après « | » est la page PDF",
              "# réelle (1 = première page du fichier) ; après « # » : commentaire.", ""]
    for t, e in zip(lignes_titres, entrees):
        commentaire = "   # douteux" if e.statut == DOUTEUX else ""
        sortie.append(f"{t.ljust(largeur)} | {e.page_pdf + 1}{commentaire}")
    return "\n".join(sortie) + "\n"


RE_LIGNE_LISTE = re.compile(r"^(?P<retrait>[ \t]*)(?P<titre>.*?\S)\s*\|\s*(?P<page>\d+)\s*(?:#.*)?$")


def texte_vers_entrees(texte, analyse):
    """Relit une liste modifiée à la main. Les liens du sommaire sont conservés pour
    les titres qu'on retrouve ; les nouvelles entrées n'ont que leur signet."""
    anciennes = {}
    for e in analyse.entrees:
        anciennes.setdefault(normaliser(e.titre), []).append(e)
    nouvelles = []
    for num_ligne, brute in enumerate(texte.splitlines(), start=1):
        if not brute.strip() or brute.lstrip().startswith("#"):
            continue
        m = RE_LIGNE_LISTE.match(brute.rstrip())
        if not m:
            raise ValueError(f"Ligne {num_ligne} illisible (il manque « | numéro ») : {brute.strip()}")
        retrait = m.group("retrait").replace("\t", "  ")
        page = int(m.group("page")) - 1
        if not 0 <= page < analyse.nb_pages:
            raise ValueError(f"Ligne {num_ligne} : page {page + 1} hors du livre "
                             f"(1 à {analyse.nb_pages}).")
        titre = m.group("titre").strip()
        memes_titres = anciennes.get(normaliser(titre))
        ancienne = memes_titres.pop(0) if memes_titres else None
        e = Entree(titre=titre, niveau=len(retrait) // 2 + 1, page_pdf=page,
                   page_imprimee=ancienne.page_imprimee if ancienne else "",
                   page_sommaire=ancienne.page_sommaire if ancienne else -1,
                   zones=list(ancienne.zones) if ancienne else [], remarque="liste importée")
        verifier_entree(e, analyse.ctx)
        nouvelles.append(e)
    if not nouvelles:
        raise ValueError("La liste ne contient aucun signet.")
    normaliser_niveaux(nouvelles)
    analyse.entrees = nouvelles
    return nouvelles


def vignette(analyse, page, largeur=220):
    """Image PNG (octets) d'une page, pour l'interface."""
    with pymupdf.open(analyse.chemin_travail) as doc:
        p = doc[min(max(page, 0), len(doc) - 1)]
        zoom = largeur / p.rect.width
        return p.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).tobytes("png")


# =============================================================================
# Ligne de commande
# =============================================================================
def _progression_console(fraction, message):
    sys.stdout.write(f"\r[{int(fraction * 100):3d} %] {message[:70]:<70}")
    sys.stdout.flush()


def main(arguments=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parseur = argparse.ArgumentParser(
        description="Ajoute des signets et un sommaire cliquable à un livre PDF.")
    parseur.add_argument("pdf", help="le livre à traiter")
    parseur.add_argument("-o", "--sortie", help="PDF à créer (défaut : livre_signets.pdf)")
    parseur.add_argument("--txt", action="store_true", help="écrit aussi la liste des signets (.txt)")
    parseur.add_argument("--liste", help="utilise une liste de signets corrigée à la main (.txt)")
    parseur.add_argument("--sans-retour", action="store_true", help="pas de liens « ↩ sommaire »")
    parseur.add_argument("--sans-ocr", action="store_true", help="ne pas lancer l'OCR")
    args = parseur.parse_args(arguments)

    base = os.path.splitext(args.pdf)[0]
    sortie = args.sortie or base + "_signets.pdf"
    dossier = tempfile.mkdtemp(prefix="signets_")
    try:
        analyse = analyser_livre(args.pdf, dossier, _progression_console, faire_ocr=not args.sans_ocr)
        print()
        for message in analyse.avertissements:
            print("Attention :", message)
        if analyse.pages_ocr:
            print(f"OCR effectué sur {analyse.pages_ocr} pages.")
        if args.liste:
            with open(args.liste, encoding="utf-8") as f:
                texte_vers_entrees(f.read(), analyse)
        if not analyse.entrees:
            print("Aucun sommaire trouvé dans ce livre (ni au début, ni à la fin).")
            print("Aucun PDF n'a été créé. Vous pouvez écrire la liste des signets à la main")
            print("(voir README) et relancer avec :  python signets.py livre.pdf --liste liste.txt")
            return 2
        if analyse.pages_sommaire:
            print("Sommaire trouvé pages", ", ".join(str(p + 1) for p in analyse.pages_sommaire))
        generer_pdf(analyse, sortie, liens_retour=not args.sans_retour)
        print(bilan(analyse.entrees))
        for e in analyse.entrees:
            if e.statut == DOUTEUX:
                print(f"  douteux : {e.titre[:60]!r} → page {e.page_pdf + 1} ({e.remarque})")
        if args.txt:
            with open(base + "_signets.txt", "w", encoding="utf-8") as f:
                f.write(entrees_vers_texte(analyse.entrees))
            print("Liste écrite :", base + "_signets.txt")
        print("PDF créé :", sortie)
        return 0
    finally:
        shutil.rmtree(dossier, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
