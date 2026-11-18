# Signets PDF

**Le site : https://signets-pdf.streamlit.app**

Déposez un livre PDF, cliquez sur **Lancer**, puis téléchargez le livre avec :

- des **signets** (la table des matières cliquable dans la barre latérale du lecteur PDF) ;
- un **sommaire imprimé cliquable** : un clic sur « Chapitre 1 » dans le sommaire mène à la bonne page ;
- en option, un petit lien **« ↩ sommaire »** en haut de chaque chapitre.

L'outil n'appelle aucune IA ni aucune API. Il marche sur les PDF natifs et sur les scans (OCR avec Tesseract,
uniquement pour les pages sans texte). L'original n'est jamais modifié, et les fichiers sont effacés du
serveur après le téléchargement.

## Les fichiers

| Fichier | Rôle |
|---|---|
| `signets.py` | Toute la logique (utilisable seule en ligne de commande) |
| `progression_ocr.py` | Transmet l'avancement de l'OCR (« OCR : page 120/400 ») à l'interface |
| `app.py` | L'interface web (Streamlit) |
| `requirements.txt` | Les bibliothèques Python |
| `packages.txt` | Les logiciels à installer en ligne (Tesseract + français, Ghostscript) |
| `.streamlit/config.toml` | Réglages : fichiers jusqu'à 1 Go, pas de statistiques, journal minimal |
| `lancer.bat` / `lancer.sh` | Lancement local en un double-clic (Windows) / une commande (Mac, Linux) |
| `tests/` | Faux livres piégés et vérification automatique (copie locale) |
| `Dockerfile` | Pour un hébergement Docker (Hugging Face PRO, etc.), facultatif |
| `MISE_EN_LIGNE.md` | Comment le site est publié (Streamlit Community Cloud, gratuit) |

## Utilisation en local

**Windows** : double-cliquez sur `lancer.bat`. La première fois, il installe les bibliothèques (quelques
minutes). Ensuite la page s'ouvre dans le navigateur (`http://localhost:8501`).

**Mac / Linux** :

```bash
sh lancer.sh
```

**En ligne de commande** (sans interface) :

```bash
python signets.py livre.pdf
```

Cela crée `livre_signets.pdf` et affiche le bilan. Options utiles :

- `--txt` écrit aussi `livre_signets.txt`, la liste des signets, modifiable à la main ;
- `--liste ma_liste.txt` pose les signets d'une liste corrigée ;
- `--sans-retour` retire les liens « ↩ sommaire » ;
- `--sans-ocr` saute l'OCR.

**Pour les scans en local**, il faut Tesseract avec le français. Sous Windows :

1. Installez Tesseract : `winget install UB-Mannheim.TesseractOCR`, ou l'installeur de
   https://github.com/UB-Mannheim/tesseract/wiki en cochant « French » dans *Additional language data*.
2. Le français : le sous-dossier `tessdata` de ce dossier contient déjà les langues française et
   anglaise ; `lancer.bat` les utilise automatiquement (aucun droit administrateur nécessaire).
   **Sans le français, l'OCR lit mal les sommaires** (points de suite pris pour des lettres) :
   l'outil le signale par « Langue française de Tesseract absente ».

Ghostscript n'est pas nécessaire en local (ocrmypdf 17 sait s'en passer). En ligne, `packages.txt` fait tout installer.

## Format de la liste de signets (fichier texte)

```
Introduction                          | 11
Chapitre 1 – Espaces préhilbertiens   | 15
  1.1 Produit scalaire                | 15
  1.2 Orthonormalisation              | 22   # douteux
```

- 2 espaces par niveau = hiérarchie ;
- le nombre après `|` est la **page PDF réelle** (1 = première page du fichier) ;
- après `#`, un commentaire (ignoré).

## Comment ça marche (en bref)

1. **OCR** des seules pages sans texte (`ocrmypdf --skip-text`, langues fra+eng). Sur un sommaire scanné, si
   Tesseract a « oublié » la colonne des numéros de page, chaque numéro est relu isolément.
2. **Repérage du sommaire**, au début et à la fin du livre. Indices : « Table des matières », « Sommaire »,
   « Contents », et surtout des lignes qui finissent par un numéro (points de suite, numéros alignés à
   droite). Un index (numéros en désordre) est écarté.
3. **Extraction** des entrées : titre (même coupé sur deux lignes), page imprimée (y compris en chiffres
   romains), niveau (indentation, sinon numérotation 1 / 1.1 / 1.1.2), position de la ligne.
4. **Recalage** page imprimée → page PDF : PageLabels du PDF s'il y en a, sinon les numéros imprimés en haut
   ou en bas des pages. Seuls les numéros confirmés par les pages voisines comptent, ce qui absorbe les
   planches hors texte. Ensuite, recherche approximative du titre à ± 4 pages, en préférant les gros
   caractères et en ignorant les en-têtes courants. Si aucun numéro n'est lisible, l'outil utilise le
   décalage le plus fréquent.
5. **Auto-vérification** : chaque signet est « confirmé » (titre retrouvé sur la page) ou « douteux ».
   L'ordre des pages est contrôlé ; une incohérence est signalée, jamais corrigée en silence.
6. **Écriture** dans une copie : signets, liens invisibles sur chaque ligne du sommaire (les liens déjà
   présents sont conservés), liens « ↩ sommaire ».

## Vérifier l'outil

```bash
python tests/fabriquer_faux_livre.py faux_livres
```

```bash
python tests/verifier.py faux_livres
```

Le premier fabrique des faux livres piégés (couverture, page blanche, pages romaines, sommaire sur deux
pages avec titre coupé, en-têtes courants, planche hors texte qui fait passer le décalage de +5 à +6,
sommaire à la fin, version scannée, version sans numéros de page, version sans sommaire). Le second affiche
le tableau « attendu / obtenu » pour chaque signet et chaque lien.

## Pourquoi Streamlit plutôt que Flask ?

Streamlit permet d'écrire toute l'interface en Python, en une centaine de lignes, sans HTML ni JavaScript.
La zone de dépôt, la barre de progression, les miniatures, les boutons ± 1 et le téléchargement existent
déjà. Flask demanderait d'écrire les pages HTML et de gérer soi-même l'envoi des fichiers et
l'avancement. Ce serait plus souple, mais plus long et plus difficile à relire pour un non-développeur.
Autre avantage : Streamlit Community Cloud héberge gratuitement ce type d'application.
