# -*- coding: utf-8 -*-
"""
Vérification automatique de signets.py sur les faux livres piégés.

    python tests/fabriquer_faux_livre.py faux_livres      (une fois)
    python tests/verifier.py faux_livres                   (toutes les variantes)
    python tests/verifier.py faux_livres debut fin         (seulement certaines)

Pour chaque variante : tableau « attendu / obtenu » pour chaque signet ET chaque
lien du sommaire, puis un résumé. Code de sortie 0 seulement si tout est juste.
Légende : (rien) = juste ; ≈ = juste, mais le titre ou le numéro imprimé a été mal
lu par l'OCR (sans conséquence sur la page) ; ✗ = erreur.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pymupdf  # noqa: E402
from rapidfuzz import fuzz  # noqa: E402
import signets  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def cible_du_lien(page, x, y):
    """Page visée par le lien qui couvre le point (x, y), ou None."""
    for lien in page.get_links():
        if lien["kind"] == pymupdf.LINK_GOTO and lien["from"].contains(pymupdf.Point(x, y)):
            return lien["page"] + 1
    return None


def bordures_invisibles(doc):
    """Tous les liens posés ont-ils une bordure nulle (rien de visible) ?"""
    for page in doc:
        for lien in page.get_links():
            bord = doc.xref_get_key(lien["xref"], "Border")
            epaisseur = doc.xref_get_key(lien["xref"], "BS/W")
            if bord[1].replace(" ", "") != "[000]" or epaisseur[1] not in ("0", "null"):
                return False
    return True


def verifier_variante(dossier, variante):
    pdf = os.path.join(dossier, f"livre_{variante}.pdf")
    with open(pdf[:-4] + ".json", encoding="utf-8") as f:
        attendu = json.load(f)
    print(f"\n=== Variante « {variante} » ({os.path.basename(pdf)}) ===")
    with tempfile.TemporaryDirectory() as tmp:
        analyse = signets.analyser_livre(pdf, tmp)
        for message in analyse.avertissements:
            print("  Attention :", message)
        if analyse.pages_ocr:
            print(f"  OCR effectué sur {analyse.pages_ocr} pages")
        if not attendu:
            ok = not analyse.sommaire_trouve
            print("  Aucun sommaire attendu →", "l'outil dit bien « aucun sommaire trouvé »"
                  if ok else f"ERREUR : {len(analyse.entrees)} entrées inventées")
            return 0 if ok else 1
        print("  Pages du sommaire trouvées :", [p + 1 for p in analyse.pages_sommaire])
        sortie = os.path.join(tmp, "sortie.pdf")
        signets.generer_pdf(analyse, sortie, liens_retour=True)
        erreurs = comparer(attendu, analyse, sortie)
        print("  Bilan de l'outil :", signets.bilan(analyse.entrees))
        erreurs += verifier_corrections(analyse)
    print("  RÉSULTAT :", "TOUT EST JUSTE" if erreurs == 0 else f"{erreurs} ERREUR(S)")
    return erreurs


def comparer(attendu, analyse, sortie):
    erreurs = 0
    obtenu = analyse.entrees
    if len(obtenu) != len(attendu):
        print(f"  ERREUR : {len(attendu)} entrées attendues, {len(obtenu)} obtenues")
        erreurs += 1
    doc = pymupdf.open(sortie)
    toc = doc.get_toc()
    print(f"  {'Titre':<42} {'niv':>7} {'imprimée':>9} {'signet':>9} {'lien(s)':>9}  statut")
    print(f"  {'':<42} {'att/obt':>7} {'att/obt':>9} {'att/obt':>9} {'att/obt':>9}")
    for i, a in enumerate(attendu):
        o = obtenu[i] if i < len(obtenu) else None
        t = toc[i] if i < len(toc) else [0, "", 0]
        liens = []
        if "sommaire" in a:
            page = doc[a["sommaire"]["page"] - 1]
            liens = [cible_du_lien(page, 200, y) for y in a["sommaire"]["lignes_y"]]
        # Exigences strictes : bonne entrée, bon niveau, signet ET liens vers la bonne page
        ressemblance = fuzz.ratio(signets.normaliser(o.titre), signets.normaliser(a["titre"])) if o else 0
        bon = (ressemblance >= 80 and o.niveau == a["niveau"] and t[0] == a["niveau"]
               and t[2] == a["page_pdf"] and all(l == a["page_pdf"] for l in liens))
        # Petites fautes de lecture (OCR) : signalées, sans compter comme erreur
        faute_ocr = bon and (ressemblance < 100 or o.page_imprimee.lower() != a["page_imprimee"])
        erreurs += not bon
        lien_txt = "/".join(str(l) for l in liens)
        print(f"{'  ' if bon and not faute_ocr else '≈ ' if bon else '✗ '}{a['titre'][:42]:<42} "
              f"{a['niveau']}/{o.niveau if o else '-':<3} "
              f"{a['page_imprimee']:>4}/{(o.page_imprimee if o else '-'):<4} "
              f"{a['page_pdf']:>4}/{t[2]:<4} {a['page_pdf']:>3}→{lien_txt:<5}  "
              f"{o.statut if o else ''}")
        if o is not None and ressemblance < 100:
            print(f"      titre lu : {o.titre!r}")
    if not bordures_invisibles(doc):
        print("  ERREUR : certains liens ont une bordure visible")
        erreurs += 1
    else:
        print("  Liens : aucune bordure visible ✓")
    retours = sum(1 for page in doc for l in page.get_links()
                  if l["kind"] == pymupdf.LINK_GOTO and l["page"] == min(analyse.pages_sommaire)
                  and page.number not in analyse.pages_sommaire)
    nb_chapitres = len({e.page_pdf for e in analyse.entrees if e.niveau == 1})
    print(f"  Liens « ↩ sommaire » : {retours} (pour {nb_chapitres} débuts de niveau 1)")
    if retours != nb_chapitres:
        erreurs += 1
    erreurs += rendu_inchange(analyse, doc)
    doc.close()
    return erreurs


def rendu_inchange(analyse, doc):
    """Les pages du sommaire et les pages sans « ↩ sommaire » doivent être identiques
    au pixel près à celles du PDF de départ (les liens sont invisibles)."""
    origine = pymupdf.open(analyse.chemin_travail)
    pages_retour = {e.page_pdf for e in analyse.entrees if e.niveau == 1}
    a_comparer = list(analyse.pages_sommaire) + [p for p in range(len(doc)) if p not in pages_retour][:15]
    differentes = [p + 1 for p in a_comparer
                   if doc[p].get_pixmap(dpi=72).samples != origine[p].get_pixmap(dpi=72).samples]
    origine.close()
    if differentes:
        print(f"  ERREUR : le rendu a changé sur les pages {differentes}")
        return 1
    print(f"  Rendu identique au pixel près ({len(a_comparer)} pages comparées, dont le sommaire) ✓")
    return 0


def verifier_corrections(analyse):
    """Les outils de correction : liste texte aller-retour, décalages ± N."""
    erreurs = 0
    avant = [(e.titre, e.niveau, e.page_pdf, tuple(map(tuple, e.zones))) for e in analyse.entrees]
    texte = signets.entrees_vers_texte(analyse.entrees)
    signets.texte_vers_entrees(texte, analyse)
    apres = [(e.titre, e.niveau, e.page_pdf, tuple(map(tuple, e.zones))) for e in analyse.entrees]
    if avant != apres:
        print("  ERREUR : la liste texte exportée puis réimportée ne redonne pas les mêmes signets")
        erreurs += 1
    i = len(analyse.entrees) // 2
    # Un signet volontairement faussé doit passer « douteux », puis redevenir « confirmé »
    signets.decaler(analyse, i, +1)
    devenu_douteux = analyse.entrees[i].statut == signets.DOUTEUX
    signets.decaler(analyse, i, -1)
    if not devenu_douteux or analyse.entrees[i].statut != signets.CONFIRME:
        print("  ERREUR : un signet décalé à tort n'est pas signalé douteux")
        erreurs += 1
    signets.decaler(analyse, i, +2, et_suivantes=True)
    if analyse.entrees[i].page_pdf != avant[i][2] + 2 or analyse.entrees[-1].page_pdf != avant[-1][2] + 2:
        print("  ERREUR : « décaler de +2 à partir de cette entrée » n'a pas décalé les suivantes")
        erreurs += 1
    signets.decaler(analyse, i, -2, et_suivantes=True)
    if [e.page_pdf for e in analyse.entrees] != [x[2] for x in avant]:
        print("  ERREUR : décaler de +2 puis −2 ne revient pas au point de départ")
        erreurs += 1
    else:
        print("  Corrections (liste texte, décalage ± N, détection d'un signet faussé) ✓")
    return erreurs


if __name__ == "__main__":
    dossier = sys.argv[1] if len(sys.argv) > 1 else "faux_livres"
    variantes = sys.argv[2:] or ["debut", "fin", "sans_folios", "sans_sommaire", "scan"]
    total = sum(verifier_variante(dossier, v) for v in variantes)
    print("\n" + ("TOUS LES TESTS SONT PASSÉS" if total == 0 else f"ÉCHEC : {total} erreur(s) au total"))
    sys.exit(1 if total else 0)
