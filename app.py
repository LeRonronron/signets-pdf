# -*- coding: utf-8 -*-
"""
Interface web (Streamlit) de l'outil de signets.
Toute la logique est dans signets.py ; ce fichier ne fait que l'affichage.

Lancer en local :   streamlit run app.py
"""
import os
import shutil
import tempfile
import threading
import time

import streamlit as st

import signets

DOSSIER_BASE = os.path.join(tempfile.gettempdir(), "signets_web")
DUREE_MAX_FICHIERS = 2 * 3600      # sécurité : fichiers abandonnés effacés après 2 h

st.set_page_config(page_title="Signets PDF", page_icon="📑", layout="centered")


# -----------------------------------------------------------------------------
# Un seul livre à la fois (pour ne pas saturer la machine gratuite)
# -----------------------------------------------------------------------------
@st.cache_resource
def verrou_global():
    return threading.Lock()


def nettoyer_vieux_dossiers():
    """Efface les dossiers de travail abandonnés (onglet fermé avant le téléchargement)."""
    os.makedirs(DOSSIER_BASE, exist_ok=True)
    for nom in os.listdir(DOSSIER_BASE):
        chemin = os.path.join(DOSSIER_BASE, nom)
        if time.time() - os.path.getmtime(chemin) > DUREE_MAX_FICHIERS:
            shutil.rmtree(chemin, ignore_errors=True)


def tout_effacer():
    """Supprime les fichiers de l'utilisateur et oublie l'analyse."""
    dossier = st.session_state.get("dossier")
    if dossier:
        shutil.rmtree(dossier, ignore_errors=True)
    for cle in ("dossier", "analyse", "pdf_final", "a_revoir", "pdf_a_jour", "id_fichier", "nom"):
        st.session_state.pop(cle, None)
    st.session_state["efface"] = True


# -----------------------------------------------------------------------------
# Traitement
# -----------------------------------------------------------------------------
def lancer(fichier, liens_retour):
    verrou = verrou_global()
    if not verrou.acquire(blocking=False):
        st.warning("Un autre livre est en cours de traitement. Réessayez dans quelques minutes.")
        return
    try:
        tout_effacer()
        st.session_state.pop("efface", None)
        dossier = tempfile.mkdtemp(prefix="livre_", dir=DOSSIER_BASE)
        st.session_state["dossier"] = dossier
        st.session_state["nom"] = os.path.splitext(fichier.name)[0]
        st.session_state["id_fichier"] = fichier.file_id
        chemin = os.path.join(dossier, "livre.pdf")
        with open(chemin, "wb") as f:
            shutil.copyfileobj(fichier, f, length=16 * 1024 * 1024)

        barre = st.progress(0.0, text="Démarrage…")
        analyse = signets.analyser_livre(
            chemin, dossier, progression=lambda frac, msg: barre.progress(frac, text=msg))
        st.session_state["analyse"] = analyse
        st.session_state["a_revoir"] = [i for i, e in enumerate(analyse.entrees)
                                        if e.statut == signets.DOUTEUX]
        if analyse.sommaire_trouve:
            barre.progress(0.97, text="Écriture des signets et des liens…")
            generer(liens_retour)
        barre.progress(1.0, text="Terminé.")
    except Exception as erreur:
        st.error(f"Le traitement a échoué : {erreur}")
    finally:
        verrou.release()


def generer(liens_retour):
    analyse = st.session_state["analyse"]
    sortie = os.path.join(st.session_state["dossier"], "livre_signets.pdf")
    signets.generer_pdf(analyse, sortie, liens_retour=liens_retour)
    st.session_state["pdf_final"] = sortie
    st.session_state["pdf_a_jour"] = True


def a_regenerer():
    st.session_state["pdf_a_jour"] = False


# -----------------------------------------------------------------------------
# Affichage
# -----------------------------------------------------------------------------
def afficher_bilan(analyse):
    for message in analyse.avertissements:
        st.warning(message)
    if not analyse.sommaire_trouve:
        st.error("**Aucun sommaire trouvé** dans ce livre (ni au début, ni à la fin). "
                 "Aucun PDF n'a été produit.\n\nVous pouvez écrire la liste des signets à la "
                 "main (format ci-dessous, rubrique « Liste des signets ») et l'importer.")
        return
    infos = f"Sommaire trouvé page(s) {', '.join(str(p + 1) for p in analyse.pages_sommaire)}"
    if analyse.pages_ocr:
        infos += f" · OCR effectué sur {analyse.pages_ocr} pages"
    st.caption(infos)
    texte = signets.bilan(analyse.entrees)
    douteux = sum(e.statut == signets.DOUTEUX for e in analyse.entrees)
    (st.warning if douteux else st.success)(f"**{texte}**")


def afficher_telechargement():
    if "pdf_final" not in st.session_state:
        return
    a_jour = st.session_state.get("pdf_a_jour", True)
    if not a_jour:
        st.info("Vous avez fait des corrections : cliquez sur « Régénérer le PDF » (plus bas) "
                "avant de télécharger.")
    with open(st.session_state["pdf_final"], "rb") as f:
        donnees = f.read()
    st.download_button("Télécharger le PDF avec signets", data=donnees,
                       file_name=f"{st.session_state['nom']}_signets.pdf",
                       mime="application/pdf", type="primary", on_click=tout_effacer,
                       icon=":material/download:", disabled=not a_jour, width="stretch")
    st.caption("Après le téléchargement, vos fichiers sont effacés du serveur.")


def afficher_corrections(analyse):
    a_revoir = st.session_state.get("a_revoir", [])
    if not a_revoir:
        return
    st.subheader("Corriger les signets douteux")
    st.caption("La miniature montre la page visée. Décalez avec −1 / +1 jusqu'à tomber sur le "
               "bon début de chapitre, puis cliquez sur « Régénérer le PDF ».")
    for i in a_revoir:
        e = analyse.entrees[i]
        with st.container(border=True):
            col_image, col_texte = st.columns([1, 2])
            with col_image:
                st.image(signets.vignette(analyse, e.page_pdf, 260), width="stretch")
            with col_texte:
                icone = "✅" if e.statut == signets.CONFIRME else "⚠️"
                st.markdown(f"{icone} **{e.titre}**")
                imprimee = f" (imprimée : {e.page_imprimee})" if e.page_imprimee else ""
                st.markdown(f"Page PDF **{e.page_pdf + 1}**{imprimee}  \n*{e.remarque}*")
                b1, b2 = st.columns(2)
                if b1.button("− 1 page", key=f"moins_{i}", width="stretch"):
                    signets.decaler(analyse, i, -1)
                    a_regenerer()
                    st.rerun()
                if b2.button("+ 1 page", key=f"plus_{i}", width="stretch"):
                    signets.decaler(analyse, i, +1)
                    a_regenerer()
                    st.rerun()
                n = st.number_input("Décaler de N pages (négatif = vers le début)",
                                    value=1, step=1, key=f"n_{i}")
                if st.button("Décaler de N à partir de cette entrée (et toutes les suivantes)",
                             key=f"suite_{i}", width="stretch"):
                    signets.decaler(analyse, i, int(n), et_suivantes=True)
                    a_regenerer()
                    st.rerun()


def afficher_liste_texte(analyse, liens_retour):
    with st.expander("Liste des signets (fichier texte, en secours)"):
        st.markdown(
            "Format : un signet par ligne, **2 espaces par niveau**, puis `| page PDF` "
            "(1 = première page du fichier). Après `#`, un commentaire.\n"
            "```\nIntroduction                          | 11\n"
            "Chapitre 1 – Espaces préhilbertiens   | 15\n"
            "  1.1 Produit scalaire                | 15\n"
            "  1.2 Orthonormalisation              | 22   # douteux\n```")
        if analyse.entrees:
            st.download_button("Télécharger la liste", signets.entrees_vers_texte(analyse.entrees),
                               file_name=f"{st.session_state['nom']}_signets.txt", mime="text/plain")
        liste = st.file_uploader("Réimporter une liste corrigée (.txt)", type=["txt"], key="liste")
        if liste is not None and st.button("Utiliser cette liste"):
            try:
                signets.texte_vers_entrees(liste.getvalue().decode("utf-8-sig"), analyse)
                st.session_state["a_revoir"] = [i for i, e in enumerate(analyse.entrees)
                                                if e.statut == signets.DOUTEUX]
                generer(liens_retour)
                st.rerun()
            except ValueError as erreur:
                st.error(str(erreur))


# -----------------------------------------------------------------------------
# Page
# -----------------------------------------------------------------------------
def main():
    nettoyer_vieux_dossiers()
    st.title("📑 Signets pour livres PDF")
    st.write("Déposez un livre PDF : l'outil ajoute les signets (table des matières "
             "cliquable dans la barre latérale) et rend le sommaire imprimé cliquable.")

    fichier = st.file_uploader("Déposer le PDF", type=["pdf"])
    if fichier is None and "analyse" in st.session_state:
        tout_effacer()                      # fichier retiré : on efface tout
        st.session_state.pop("efface", None)
    lancer_clique = st.button("Lancer", type="primary", disabled=fichier is None,
                              width="stretch")
    zone_traitement = st.container()

    if st.session_state.pop("efface", False):
        st.success("Téléchargement lancé. Vos fichiers ont été effacés du serveur.")

    st.divider()
    liens_retour = st.checkbox("Ajouter un petit lien « ↩ sommaire » en haut de chaque chapitre",
                               value=True, on_change=a_regenerer, key="liens_retour")

    if lancer_clique and fichier is not None:
        with zone_traitement:
            lancer(fichier, liens_retour)

    analyse = st.session_state.get("analyse")
    if analyse is None:
        return
    with zone_traitement:
        afficher_bilan(analyse)
        afficher_telechargement()
    afficher_corrections(analyse)
    if analyse.sommaire_trouve or analyse.entrees:
        if st.button("🔄 Régénérer le PDF", width="stretch",
                     disabled=st.session_state.get("pdf_a_jour", True)):
            with st.spinner("Écriture du PDF…"):
                generer(liens_retour)
            st.rerun()
    afficher_liste_texte(analyse, liens_retour)


main()
