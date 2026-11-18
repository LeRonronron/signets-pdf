# -*- coding: utf-8 -*-
"""
Fabrique de FAUX LIVRES PDF « piégés » pour tester signets.py.

Pièges présents dans le livre :
  - couverture, page blanche, pages en chiffres romains (i, ii, iii) ;
  - sommaire sur deux pages, avec points de suite, indentation,
    et un titre long coupé sur deux lignes (la 2e ligne est en retrait,
    comme une section : il ne faut PAS la prendre pour une section) ;
  - en-têtes courants qui répètent le titre du chapitre / de la section ;
  - numéros de page tantôt en haut (pages courantes), tantôt en bas
    (pages d'ouverture de chapitre) ;
  - une note de bas de page « 1 Voir ... » (faux numéro de page) ;
  - une planche hors texte NON numérotée au milieu : le décalage
    page PDF − page imprimée passe de +5 à +6 ;
  - un index en deux colonnes (des lignes qui finissent par un numéro,
    mais ce n'est pas un sommaire).

Variantes produites (dans le dossier donné en argument) :
  livre_debut.pdf          sommaire au début
  livre_fin.pdf            sommaire à la fin du livre
  livre_scan.pdf           livre_debut « scanné » : pages en images, sans texte
  livre_sans_sommaire.pdf  aucun sommaire (l'outil doit le dire)
  livre_sans_folios.pdf    aucun numéro de page imprimé (plan de secours)
  + un fichier .json par variante avec les pages attendues.

Utilisation :  python tests/fabriquer_faux_livre.py dossier_sortie
"""
import json
import os
import sys

import pymupdf

LARGEUR, HAUTEUR = 420, 595          # format A5, en points
MARGE_G, MARGE_D = 45, 375           # marges gauche / droite du texte
COL_NUM = 375                        # bord droit des numéros du sommaire
HAUT_CORPS, BAS_CORPS, INTERLIGNE = 72, 540, 13

# --------------------------------------------------------------------------
# Plan du livre : (titre, niveau, page imprimée, placement)
#   placement : "ouverture" = nouvelle page avec grand titre
#               "haut"      = intertitre en haut de page
#               "milieu"    = intertitre au milieu de la page
# --------------------------------------------------------------------------
PLAN = [
    ("Préface", 1, "i", "ouverture"),
    ("Introduction", 1, "1", "ouverture"),
    ("Chapitre 1 – Espaces préhilbertiens", 1, "3", "ouverture"),
    ("1.1 Produit scalaire", 2, "4", "haut"),
    ("1.2 Orthonormalisation de Gram-Schmidt", 2, "6", "milieu"),
    ("1.3 Projection orthogonale", 2, "7", "haut"),
    ("1.4 Inégalité de Bessel", 2, "7", "milieu"),
    ("Chapitre 2 – Un titre extrêmement long sur les séries de Fourier "
     "et les espaces de Hilbert séparables", 1, "9", "ouverture"),
    ("2.1 Coefficients de Fourier", 2, "10", "haut"),
    ("2.2 Théorème de Parseval", 2, "12", "milieu"),
    ("2.3 Convergence ponctuelle et noyau de Dirichlet", 2, "13", "haut"),
    ("2.4 Phénomène de Gibbs", 2, "14", "milieu"),
    ("Chapitre 3 – Opérateurs compacts", 1, "16", "ouverture"),
    ("3.1 Spectre", 2, "17", "haut"),
    ("3.2 Alternative de Fredholm", 2, "19", "milieu"),
    ("3.3 Théorème spectral", 2, "21", "haut"),
    ("Chapitre 4 – Espaces Lp et dualité", 1, "23", "ouverture"),
    ("4.1 Inégalités de Hölder et de Minkowski", 2, "24", "haut"),
    ("4.2 Complétude : théorème de Riesz-Fischer", 2, "26", "milieu"),
    ("4.3 Dual de Lp pour 1 < p < q", 2, "28", "haut"),
    ("Chapitre 5 – Distributions", 1, "30", "ouverture"),
    ("5.1 Fonctions test", 2, "31", "haut"),
    ("5.2 Dérivation au sens des distributions", 2, "33", "milieu"),
    ("5.3 Transformée de Fourier des distributions tempérées", 2, "35", "haut"),
    ("Chapitre 6 – Équations aux dérivées partielles", 1, "37", "ouverture"),
    ("6.1 Équation de la chaleur", 2, "38", "haut"),
    ("6.2 Équation des ondes", 2, "40", "milieu"),
    ("6.3 Problème de Dirichlet", 2, "42", "haut"),
    ("Exercices corrigés", 1, "44", "ouverture"),
    ("Bibliographie", 1, "50", "ouverture"),
    ("Index", 1, "52", "ouverture"),
]
DERNIERE_PAGE_IMPRIMEE = 54
PLANCHE_APRES = 12                   # la planche est insérée après la page imprimée 12


def page_physique(imprimee):
    """Page PDF attendue (1 = première page du fichier) pour une page imprimée."""
    if imprimee in ("i", "ii", "iii"):
        return {"i": 3, "ii": 4, "iii": 5}[imprimee]
    n = int(imprimee)
    return n + 5 if n <= PLANCHE_APRES else n + 6


# --------------------------------------------------------------------------
# Texte de remplissage (avec quelques pièges : lignes finissant par un nombre)
# --------------------------------------------------------------------------
PHRASES = [
    "Soit E un espace vectoriel réel muni d'un produit scalaire noté (x | y).",
    "On vérifie aisément que l'application x -> ||x|| est une norme sur E.",
    "Pour tout entier n >= 2 la suite (u_n) est majorée par 2",
    "Le lemme suivant sera utilisé de manière essentielle au chapitre 3",
    "Rappelons que toute suite de Cauchy d'un espace complet converge.",
    "La démonstration repose sur l'inégalité de Cauchy-Schwarz et sur la",
    "bilinéarité du produit scalaire ; on laisse les détails au lecteur.",
    "Remarquons enfin que la constante obtenue est optimale : prendre p = 1",
    "Par densité, il suffit d'établir le résultat pour des fonctions",
    "continues à support compact, ce qui ne présente aucune difficulté.",
    "On en déduit que la série de terme général a_n b_n converge absolument.",
    "Exemple. Dans R^n muni du produit scalaire usuel, la base canonique",
    "est orthonormée et l'on retrouve le théorème de Pythagore pour n = 2",
]


def lignes_de_remplissage(graine, nombre):
    return [PHRASES[(graine * 7 + k) % len(PHRASES)] for k in range(nombre)]


# --------------------------------------------------------------------------
# Petites fonctions de dessin
# --------------------------------------------------------------------------
POLICES = {"helv": pymupdf.Font("helv"), "hebo": pymupdf.Font("hebo")}   # Unicode complet (tirets –)


def texte(page, x, y, chaine, taille=10, police="helv", couleur=(0, 0, 0)):
    ecrivain = pymupdf.TextWriter(page.rect)
    ecrivain.append((x, y), chaine, font=POLICES[police], fontsize=taille)
    ecrivain.write_text(page, color=couleur)


def largeur(chaine, taille=10, police="helv"):
    return POLICES[police].text_length(chaine, fontsize=taille)


def texte_droite(page, x_droite, y, chaine, taille=10, police="helv"):
    texte(page, x_droite - largeur(chaine, taille, police), y, chaine, taille, police)


def texte_centre(page, y, chaine, taille=10, police="helv"):
    texte(page, (LARGEUR - largeur(chaine, taille, police)) / 2, y, chaine, taille, police)


def couper(chaine, largeur_max, taille, police):
    """Coupe une chaîne en lignes de largeur maximale donnée."""
    lignes, courante = [], ""
    for mot in chaine.split():
        essai = (courante + " " + mot).strip()
        if courante and largeur(essai, taille, police) > largeur_max:
            lignes.append(courante)
            courante = mot
        else:
            courante = essai
    if courante:
        lignes.append(courante)
    return lignes


def titre_court_en_tete(titre):
    """Texte des en-têtes courants : « CHAPITRE 2. UN TITRE EXTRÊMEMENT LONG… »."""
    t = titre.replace(" – ", ". ").upper()
    if len(t) > 48:
        t = t[:46].rsplit(" ", 1)[0] + "…"
    return t


# --------------------------------------------------------------------------
# Les différentes sortes de pages
# --------------------------------------------------------------------------
def page_couverture(doc):
    p = doc.new_page(width=LARGEUR, height=HAUTEUR)
    p.draw_rect(pymupdf.Rect(30, 30, LARGEUR - 30, HAUTEUR - 30), color=(0.2, 0.2, 0.5), width=3)
    texte_centre(p, 200, "ANALYSE FONCTIONNELLE", 24, "hebo")
    texte_centre(p, 235, "Cours et exercices", 14)
    texte_centre(p, 480, "Éditions du Faux Livre", 11)


def page_blanche(doc):
    doc.new_page(width=LARGEUR, height=HAUTEUR)


def page_ouverture(doc, titre, folio, graine):
    """Première page d'un chapitre : grand titre, folio en bas, pas d'en-tête."""
    p = doc.new_page(width=LARGEUR, height=HAUTEUR)
    y = 140
    if " – " in titre:
        avant, apres = titre.split(" – ", 1)
        texte(p, MARGE_G, y, avant, 14, "hebo")
        y += 34
    else:
        apres = titre
    for morceau in couper(apres, 320, 20, "hebo"):
        texte(p, MARGE_G, y, morceau, 20, "hebo")
        y += 26
    y += 30
    for ligne in lignes_de_remplissage(graine, int((BAS_CORPS - y) / INTERLIGNE)):
        texte(p, MARGE_G, y, ligne, 9.5)
        y += INTERLIGNE
    texte_centre(p, 565, folio, 9)
    return p


def page_courante(doc, folio, en_tete, intertitres, graine, note=None):
    """Page ordinaire : en-tête courant + folio en haut, texte, intertitres éventuels."""
    p = doc.new_page(width=LARGEUR, height=HAUTEUR)
    # En-tête : folio à gauche sur les pages paires, à droite sur les impaires
    if int(folio) % 2 == 0:
        texte(p, MARGE_G, 40, folio, 9)
        texte(p, MARGE_G + 30, 40, en_tete, 8.5)
    else:
        texte_droite(p, MARGE_D, 40, folio, 9)
        texte_droite(p, MARGE_D - 30, 40, en_tete, 8.5)
    p.draw_line((MARGE_G, 45), (MARGE_D, 45), width=0.4)
    y = HAUT_CORPS
    remplissage = iter(lignes_de_remplissage(graine, 60))
    for position, titre in intertitres:
        cible = HAUT_CORPS if position == "haut" else HAUT_CORPS + 15 * INTERLIGNE
        while y < cible:
            texte(p, MARGE_G, y, next(remplissage), 9.5)
            y += INTERLIGNE
        y += 8 if position == "milieu" else 0
        texte(p, MARGE_G, y, titre, 12, "hebo")
        y += 22
    while y < BAS_CORPS:
        texte(p, MARGE_G, y, next(remplissage), 9.5)
        y += INTERLIGNE
    if note:
        p.draw_line((MARGE_G, 548), (MARGE_G + 80, 548), width=0.4)
        texte(p, MARGE_G, 560, note, 7.5)
    return p


def page_planche(doc):
    """Planche hors texte : un dessin, une légende, AUCUN numéro de page."""
    p = doc.new_page(width=LARGEUR, height=HAUTEUR)
    for k in range(1, 9):
        r = pymupdf.Rect(210 - 18 * k, 280 - 12 * k, 210 + 18 * k, 280 + 12 * k)
        p.draw_oval(r, color=(0.1, 0.3, 0.6), width=1.2)
    texte_centre(p, 480, "Lignes de niveau d'une fonction harmonique", 10)
    texte_centre(p, 540, "Planche I", 11, "hebo")


def page_index(doc, folio, premiere):
    p = doc.new_page(width=LARGEUR, height=HAUTEUR)
    y = HAUT_CORPS
    if premiere:
        texte(p, MARGE_G, 140, "Index", 20, "hebo")
        y = 200
    else:
        texte_droite(p, MARGE_D, 40, folio, 9)
        texte_droite(p, MARGE_D - 30, 40, "INDEX", 8.5)
    mots = ["Bessel (inégalité de), 7", "Cauchy-Schwarz, 4, 12", "Dirichlet (noyau de), 13",
            "Fredholm, 19", "Gibbs (phénomène de), 14", "Gram-Schmidt, 6", "Hölder, 24, 28",
            "Parseval, 12", "Riesz-Fischer, 26", "spectre, 17, 21", "tempérée, 35"]
    k = 0
    while y < BAS_CORPS:
        texte(p, MARGE_G, y, mots[k % len(mots)], 9)
        texte(p, 215, y, mots[(k + 5) % len(mots)], 9)
        y += 14
        k += 1
    if premiere:
        texte_centre(p, 565, folio, 9)


def page_preface(doc):
    p = page_ouverture(doc, "Préface", "i", 3)
    return p


def pages_notations(doc):
    """Pages ii et iii de la variante « sommaire à la fin »."""
    for folio in ("ii", "iii"):
        p = doc.new_page(width=LARGEUR, height=HAUTEUR)
        y = 120
        if folio == "ii":
            texte(p, MARGE_G, 90, "Notations", 18, "hebo")
        for sym, sens in [("N", "ensemble des entiers naturels"), ("R", "corps des réels"),
                          ("C", "corps des complexes"), ("Lp", "espace des fonctions p-intégrables"),
                          ("(x | y)", "produit scalaire"), ("||x||", "norme associée")] * 3:
            texte(p, MARGE_G, y, sym, 10)
            texte(p, MARGE_G + 60, y, sens, 10)
            y += 18
        texte_centre(p, 565, folio, 9)


# --------------------------------------------------------------------------
# Le sommaire
# --------------------------------------------------------------------------
def pages_sommaire(doc, folios, attendu):
    """Écrit le sommaire sur plusieurs pages. Note, pour chaque entrée, la page du
    sommaire et la hauteur de chacune de ses lignes (pour vérifier les liens)."""
    numero_page = 0
    p, y = None, None

    def nouvelle_page():
        nonlocal p, y, numero_page
        p = doc.new_page(width=LARGEUR, height=HAUTEUR)
        if numero_page == 0:
            texte(p, MARGE_G, 85, "Table des matières", 18, "hebo")
            y = 130
        else:
            texte_centre(p, 40, "TABLE DES MATIÈRES", 8.5)
            y = 80
        texte_centre(p, 565, folios[numero_page], 9)
        numero_page += 1

    nouvelle_page()
    for i, (titre, niveau, imprimee, _) in enumerate(PLAN):
        x0 = MARGE_G if niveau == 1 else MARGE_G + 17
        police, taille = ("hebo", 10.5) if niveau == 1 else ("helv", 10)
        largeur_titre = COL_NUM - x0 - 45
        morceaux = couper(titre, largeur_titre, taille, police)
        if y + 17 * len(morceaux) > 545:
            nouvelle_page()
        lignes_y = []
        for k, morceau in enumerate(morceaux):
            xm = x0 if k == 0 else x0 + 17          # retrait des lignes de suite
            texte(p, xm, y, morceau, taille, police)
            lignes_y.append(y - taille * 0.35)      # milieu approximatif de la ligne
            if k == len(morceaux) - 1:
                # points de suite puis numéro aligné à droite
                fin_titre = xm + largeur(morceau, taille, police) + 6
                x_num = COL_NUM - largeur(imprimee, taille, police)
                xp = (int(fin_titre / 5) + 1) * 5
                while xp < x_num - 6:
                    texte(p, xp, y, ".", taille)
                    xp += 5
                texte(p, x_num, y, imprimee, taille, police)
                y += 17
            else:
                y += 13
        attendu[i]["sommaire"] = {"page": doc.page_count, "lignes_y": lignes_y}


# --------------------------------------------------------------------------
# Assemblage
# --------------------------------------------------------------------------
def entrees_par_page_imprimee():
    """Pour chaque page imprimée : ce qui commence dessus."""
    debut = {}
    for titre, niveau, imprimee, placement in PLAN:
        debut.setdefault(imprimee, []).append((titre, niveau, placement))
    return debut


def corps_du_livre(doc):
    """Pages imprimées 1 à 54, avec la planche hors texte après la page 12."""
    debuts = entrees_par_page_imprimee()
    chapitre, section = "", ""
    for n in range(1, DERNIERE_PAGE_IMPRIMEE + 1):
        folio = str(n)
        ici = debuts.get(folio, [])
        ouverture = [t for t, niv, pl in ici if pl == "ouverture"]
        if ouverture:
            chapitre = ouverture[0]
            section = ""
            if chapitre == "Index":
                page_index(doc, folio, premiere=True)
            else:
                page_ouverture(doc, chapitre, folio, n)
        elif chapitre == "Index":
            page_index(doc, folio, premiere=False)
        else:
            intertitres = [(pl, t) for t, niv, pl in ici]
            if intertitres:
                section = intertitres[-1][1]
            if n % 2 == 0 or not section:
                en_tete = titre_court_en_tete(chapitre)
            else:
                en_tete = titre_court_en_tete(section.replace(" ", ". ", 1))
            note = "1 Voir aussi le chapitre 3." if n == 26 else None
            page_courante(doc, folio, en_tete, intertitres, n, note)
        if n == PLANCHE_APRES:
            page_planche(doc)


def fabriquer(variante):
    """variante : 'debut', 'fin' ou 'sans_sommaire'. Renvoie (doc, attendu)."""
    attendu = [{"titre": t, "niveau": niv, "page_imprimee": imp, "page_pdf": page_physique(imp)}
               for t, niv, imp, _ in PLAN]
    doc = pymupdf.open()
    page_couverture(doc)
    page_blanche(doc)
    page_preface(doc)
    if variante == "debut":
        pages_sommaire(doc, ["ii", "iii"], attendu)
    else:
        pages_notations(doc)
    corps_du_livre(doc)
    if variante == "fin":
        pages_sommaire(doc, ["55", "56"], attendu)
    if variante == "sans_sommaire":
        attendu = []
    return doc, attendu


def scanner(chemin_source, chemin_sortie, dpi=200):
    """Fabrique une version « scannée » : chaque page devient une simple image."""
    source = pymupdf.open(chemin_source)
    scan = pymupdf.open()
    for page in source:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        nouvelle = scan.new_page(width=page.rect.width, height=page.rect.height)
        nouvelle.insert_image(nouvelle.rect, pixmap=pix)
    scan.save(chemin_sortie, deflate=True)


def retirer_folios(chemin_source, chemin_sortie):
    """Variante « sans numéros de page » : on efface tous les folios (haut et bas de page).
    L'outil doit alors se rabattre sur la recherche des titres (décalage moyen)."""
    doc = pymupdf.open(chemin_source)
    for page in doc:
        for x0, y0, x1, y1, mot, *_ in page.get_text("words"):
            marge = y1 < 50 or y0 > 555
            if marge and (mot.isdigit() or mot in ("i", "ii", "iii")):
                page.add_redact_annot(pymupdf.Rect(x0, y0, x1, y1))
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE)
    doc.save(chemin_sortie)


def main(dossier):
    os.makedirs(dossier, exist_ok=True)
    for variante in ("debut", "fin", "sans_sommaire"):
        doc, attendu = fabriquer(variante)
        chemin = os.path.join(dossier, f"livre_{variante}.pdf")
        doc.save(chemin)
        with open(chemin[:-4] + ".json", "w", encoding="utf-8") as f:
            json.dump(attendu, f, ensure_ascii=False, indent=1)
        print(f"{chemin} : {doc.page_count} pages")
    scanner(os.path.join(dossier, "livre_debut.pdf"), os.path.join(dossier, "livre_scan.pdf"))
    with open(os.path.join(dossier, "livre_debut.json"), encoding="utf-8") as f:
        attendu = json.load(f)
    with open(os.path.join(dossier, "livre_scan.json"), "w", encoding="utf-8") as f:
        json.dump(attendu, f, ensure_ascii=False, indent=1)
    print(os.path.join(dossier, "livre_scan.pdf"), ": version scannée")
    retirer_folios(os.path.join(dossier, "livre_debut.pdf"), os.path.join(dossier, "livre_sans_folios.pdf"))
    with open(os.path.join(dossier, "livre_sans_folios.json"), "w", encoding="utf-8") as f:
        json.dump(attendu, f, ensure_ascii=False, indent=1)
    print(os.path.join(dossier, "livre_sans_folios.pdf"), ": sans aucun numéro de page imprimé")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "faux_livres")
