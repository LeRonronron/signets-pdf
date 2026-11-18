# Le site en ligne (Streamlit Community Cloud, gratuit)

**Adresse du site : https://signets-pdf.streamlit.app**

Le site tourne sur **Streamlit Community Cloud**, l'hébergement gratuit des créateurs de Streamlit.
Il lit les fichiers du dépôt GitHub `LeRonronron/signets-pdf` et reconstruit le site tout seul
à chaque modification.

> Pourquoi pas Hugging Face ? Depuis 2026, Hugging Face réserve les Spaces « Docker » (ceux qui
> font tourner un programme) à l'abonnement payant PRO. Le `Dockerfile` reste dans le dossier
> local au cas où vous choisiriez un jour un hébergement Docker.

## Comment c'est branché

1. **GitHub** (https://github.com/LeRonronron/signets-pdf) contient les fichiers du site :
   `app.py`, `signets.py`, `progression_ocr.py`, `requirements.txt` (bibliothèques Python),
   `packages.txt` (Tesseract + français, Ghostscript) et `.streamlit/config.toml` (réglages).
2. **Streamlit Community Cloud** (https://share.streamlit.io), connecté à votre compte GitHub,
   construit et fait tourner le site à partir de ces fichiers.

## Mettre à jour le site

Il suffit de modifier un fichier sur GitHub :

1. Ouvrez le fichier sur https://github.com/LeRonronron/signets-pdf.
2. Cliquez sur le crayon (**Edit this file**), ou sur **Add file → Upload files** pour remplacer
   un fichier par la version de votre dossier `Documents\signets-pdf`.
3. **Commit changes**.

Streamlit Cloud voit le changement et relance le site en une ou deux minutes.

## Gérer le site

Sur https://share.streamlit.io (connexion avec GitHub), le menu **⋮** à côté de l'application permet de :
- **Reboot** : redémarrer le site s'il est bloqué ;
- **Settings → Sharing** : le rendre privé ou public ;
- **Delete** : le supprimer.

En cas d'erreur, le bouton **Manage app** (en bas à droite du site, quand vous êtes connecté)
montre le journal : copiez les dernières lignes rouges pour les faire corriger.

## Bon à savoir

- **Mise en veille** : sans visite pendant quelques jours, le site s'endort. Un bouton
  « Yes, get this app back up! » le réveille (environ une minute).
- **Un livre à la fois** : si quelqu'un traite déjà un livre, l'outil demande de patienter.
- **Confidentialité** : les fichiers sont traités dans un dossier temporaire et effacés au
  téléchargement (ou au bout de 2 h s'ils sont abandonnés). Rien n'est journalisé.
- **Gros fichiers** : la machine gratuite est modeste (quelques Go de mémoire). Pour les très gros
  scans (plusieurs centaines de Mo), la version locale (`lancer.bat`) est plus rapide et plus sûre.
