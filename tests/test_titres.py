# -*- coding: utf-8 -*-
"""
Nettoyage des titres lus par OCR : faux points de suite et majuscules bizarres.
Exemples tirés d'un vrai livre scanné.     python tests/test_titres.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import signets  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CAS = [
    # (titre lu par l'OCR, titre attendu)
    ("Relations binaires fondamentales 0 0.0 00002 eee", "Relations binaires fondamentales"),
    ("Ensembles ordonnés 2 2 ee eee", "Ensembles ordonnés"),
    ("Treillis 2 ee", "Treillis"),
    ("Bon ordre et axiome du choix 0 0.02 eee ee eee", "Bon ordre et axiome du choix"),
    ("Arithmétique 2 2. ee ees", "Arithmétique"),
    ("GYOUPES 2 ee ee eee eee eee eee eens", "Gyoupes"),
    ("Lois de composition interne 2 0.0.0.0. 2 eee eee ee ees", "Lois de composition interne"),
    ("Axiomes de la structure de groupe 0.0020005", "Axiomes de la structure de groupe"),
    ("Centre d'un groupe 2.2 ee ...", "Centre d'un groupe"),
    ("Sous-groupes 0.2 ee ees", "Sous-groupes"),
    ("Ordre d'un élément dans un groupe - 00.0,5", "Ordre d'un élément dans un groupe"),
    ("Groupes simples et groupes résolubles 0.00-", "Groupes simples et groupes résolubles"),
    ("Anneaux et COrpS 0 ccc cee ee eee eee ees", "Anneaux et Corps"),
    ("Espaces vectoriels 0 ce eee ee ee eee ene", "Espaces vectoriels"),
    ("Topologie générale ........ 0... cc ccc ee tee ene", "Topologie générale"),
    ("Suites de fonctions ............ ccc ccc cence cence ceeee", "Suites de fonctions"),
    ("Topologie de RR 2... .. ee ee ee", "Topologie de RR"),
    ("Différents ensembles de nombres réels 2 20-0-00", "Différents ensembles de nombres réels"),
    ("Intégration oeeeee?e#e#e##s # # @ ® eeee#ses # # @ @ sv fe #", "Intégration"),
    ("Séries numériqueS 2 cece ee eee ee eee a", "Séries numériques"),
    ("Morphismes et isomorphismes de groupes 20", "Morphismes et isomorphismes de groupes"),
    ("Dérivées supérieures et inférieures 0004", "Dérivées supérieures et inférieures"),
    ("Dérivées et extremums 2 ee ns", "Dérivées et extremums"),
    ("Espérance mathématique et variance --04", "Espérance mathématique et variance"),
    ("Probabilités |", "Probabilités"),
    ("Corps 2", "Corps"),
    ("Intégration 2", "Intégration"),
    ("Théorémes @inversion", "Théorémes @inversion"),
    # Ce qui ne doit PAS bouger
    ("Produit de E et F", "Produit de E et F"),
    ("Espaces Lp", "Espaces Lp"),
    ("Géométrie en dimension 3", "Géométrie en dimension 3"),
    ("Exercice 12", "Exercice 12"),
    ("Équations du second degré", "Équations du second degré"),
    ("Chapitre 2", "Chapitre 2"),
    ("Chapitre 16 – Espaces métriques", "Chapitre 16 – Espaces métriques"),
    ("4.3 Dual de Lp pour 1 < p < q", "4.3 Dual de Lp pour 1 < p < q"),
    ("Exercices du chapitre 3", "Exercices du chapitre 3"),
    ("Annexe A", "Annexe A"),
    ("Théorème de Stone-Weierstrass", "Théorème de Stone-Weierstrass"),
    ("ANNEAUX ET CORPS", "Anneaux et corps"),
    ("PARTIE II – ALGÈBRE", "Partie II – Algèbre"),
]

erreurs = 0
for lu, attendu in CAS:
    obtenu = signets._assembler_titre([lu])
    ok = obtenu == attendu
    erreurs += not ok
    print(f"{'  ' if ok else '✗ '}{lu!r:62} → {obtenu!r}" + ("" if ok else f"   (attendu {attendu!r})"))
print("TOUT EST JUSTE" if not erreurs else f"{erreurs} ERREUR(S)")
sys.exit(1 if erreurs else 0)
