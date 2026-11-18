# Passer au « vrai site » : nom de domaine, serveur, référencement

Résultat visé :
- **https://VOTRE-DOMAINE** : la page d'accueil (dossier `site/`), faite pour être trouvée sur Google ;
- **https://app.VOTRE-DOMAINE** : l'outil lui-même ;
- HTTPS automatique et gratuit, pages légales, aucun journal des visites.

Budget : environ **10 à 15 € par an** pour le domaine et **4 à 8 € par mois** pour le serveur.
Les prix sont des ordres de grandeur, à vérifier au moment d'acheter.

---

## Étape 0 — Avant de mettre en ligne : compléter les pages légales

Dans `site/mentions-legales.html` et `site/confidentialite.html`, remplacez ce qui est entre crochets
(surligné en jaune sur la page) : nom ou choix de l'anonymat, adresse e-mail de contact.
Si vous éditez le site à titre personnel et non professionnel, la loi vous permet de ne pas publier
votre nom et votre adresse, à condition que l'hébergeur connaisse votre identité.
Le fichier explique les deux possibilités.

## Étape 1 — Acheter le nom de domaine (≈ 10 à 15 € par an)

Chez **Cloudflare Registrar** (prix coûtant), **OVH** ou **Gandi**. Par exemple `signets-pdf.fr`.

## Étape 2 — Louer le serveur (≈ 5 à 8 € par mois)

Choix retenu : **OVHcloud VPS-1** (2 cœurs, 4 Go, Gravelines, France), sans engagement,
4,49 € HT soit environ 5,39 € TTC par mois.
1. Commandez sur https://www.ovhcloud.com/fr/vps/ : **VPS-1**, **Aucun engagement**, système
   **Ubuntu 24.04**.
2. Dans l'espace client (**Bare Metal Cloud → VPS**), utilisez **Réinstaller mon VPS** avec Ubuntu 24.04
   et collez votre **clé SSH publique** : la connexion se fait alors sans mot de passe.
3. Notez l'**adresse IPv4** du VPS (quatre nombres).
   Sur OVH, l'utilisateur s'appelle `ubuntu` : connectez-vous avec `ssh ubuntu@ADRESSE-IP`, puis
   lancez les commandes avec `sudo`.

(Hetzner Cloud est une bonne alternative, un peu moins chère, mais demande une vérification de compte.)

## Étape 3 — Faire pointer le domaine vers le serveur

Chez le vendeur du domaine, rubrique **DNS**, créez trois enregistrements de type **A** :

| Nom | Type | Valeur |
|---|---|---|
| `@` (le domaine nu) | A | l'adresse IP du serveur |
| `www` | A | l'adresse IP du serveur |
| `app` | A | l'adresse IP du serveur |

Si vous êtes chez Cloudflare, mettez ces enregistrements en **« DNS only »** (nuage gris), sinon le
certificat HTTPS ne pourra pas être obtenu. La prise en compte prend de quelques minutes à quelques heures.

## Étape 4 — Installer le site sur le serveur

Dans PowerShell, sur votre PC :

```bash
ssh ubuntu@ADRESSE-IP-DU-SERVEUR
```

puis passez administrateur :

```bash
sudo -i
```

Puis, sur le serveur, copiez ces commandes l'une après l'autre :

```bash
apt-get update && apt-get install -y git
```

```bash
git clone https://github.com/LeRonronron/signets-pdf.git && cd signets-pdf/deploiement
```

```bash
cp .env.exemple .env && nano .env
```

Dans l'éditeur `nano`, remplissez `DOMAINE=` (par exemple `signets-pdf.com`).
Enregistrez avec **Ctrl+O**, **Entrée**, puis quittez avec **Ctrl+X**. Enfin :

```bash
sh installer.sh
```

La première fois, comptez 5 à 10 minutes (installation de Docker, puis construction de l'outil avec
Tesseract). À la fin, le script affiche les deux adresses du site.

## Mettre à jour le site

Après une modification envoyée sur GitHub, sur le serveur :

```bash
cd signets-pdf && git pull && sh deploiement/installer.sh
```

---

## Étape 5 — Le référencement

1. **Google Search Console** (https://search.google.com/search-console) : ajoutez une propriété de type
   **Domaine**, puis validez-la avec l'enregistrement DNS « TXT » que Google indique. Ensuite, menu
   **Sitemaps** : envoyez `https://VOTRE-DOMAINE/sitemap.xml`.
2. **Bing Webmaster Tools** (https://www.bing.com/webmasters) : bouton « Importer depuis Google Search
   Console ». Bing alimente aussi DuckDuckGo et Ecosia.
3. **Faire connaître le site** : chaque lien depuis un site sérieux aide Google.
   - forums et communautés de maths (les-mathematiques.net, groupes de profs et d'étudiants) ;
   - Reddit (r/france, r/etudiants, r/LaTeX…), en présentant l'outil honnêtement ;
   - annuaires d'outils : AlternativeTo (en alternative à « Calibre » ou « JPdfBookmarks ») ;
   - un court tutoriel ou une vidéo de démonstration de 30 secondes.
4. **Patience** : comptez quelques semaines pour l'indexation, et plusieurs mois pour un trafic notable.

La page d'accueil est déjà prête pour Google : titre et description travaillés, données structurées
(application gratuite, FAQ), sitemap, robots.txt, image d'aperçu pour les partages, et adaptation au
téléphone.

## Et la version gratuite sur Streamlit Cloud ?

Elle peut rester en ligne en parallèle, ou être supprimée depuis https://share.streamlit.io
(menu ⋮ → Delete). Les deux versions utilisent le même code.
