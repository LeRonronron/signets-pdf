#!/bin/sh
# Lance l'outil de signets en local (Mac / Linux) :  sh lancer.sh
# La première fois, installe les bibliothèques Python dans le dossier .venv
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
    echo "Première utilisation : installation des bibliothèques, patientez..."
    python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
fi
# « echo » répond à vide à la question « Email » que Streamlit pose au tout premier lancement
echo "" | .venv/bin/python -m streamlit run app.py
