#!/bin/sh
# ---------------------------------------------------------------------------
# Installe (ou met à jour) le site sur un serveur Ubuntu 24.04.
#   Première fois :   sudo sh installer.sh
#   Mise à jour   :   git pull  puis  sudo sh installer.sh
# ---------------------------------------------------------------------------
set -e
cd "$(dirname "$0")"

# 1. Réglages
if [ ! -f .env ]; then
    echo "Il manque le fichier .env : copiez .env.exemple en .env et remplissez-le."
    exit 1
fi
. ./.env
if [ -z "$DOMAINE" ] || [ -z "$EMAIL" ]; then
    echo "Remplissez DOMAINE et EMAIL dans le fichier .env."
    exit 1
fi

# 2. Docker (une seule fois)
if ! command -v docker >/dev/null 2>&1; then
    echo "Installation de Docker..."
    apt-get update
    apt-get install -y docker.io docker-compose-v2
    systemctl enable --now docker
fi

# 3. Mémoire de secours (swap de 2 Go) : l'OCR d'un gros scan peut être gourmand
if [ "$(swapon --show | wc -l)" -eq 0 ]; then
    echo "Création d'un fichier d'échange de 2 Go..."
    fallocate -l 2G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi

# 4. Pare-feu : seulement SSH, HTTP et HTTPS
if command -v ufw >/dev/null 2>&1; then
    ufw allow OpenSSH
    ufw allow 80/tcp
    ufw allow 443
    ufw --force enable
fi

# 5. Page d'accueil : on remplace __DOMAINE__ par le vrai nom de domaine
rm -rf site_public
cp -r ../site site_public
find site_public -type f \( -name "*.html" -o -name "*.xml" -o -name "*.txt" \) \
    -exec sed -i "s/__DOMAINE__/$DOMAINE/g" {} +

# 6. Construction et démarrage (redémarre tout seul après un redémarrage du serveur)
docker compose up -d --build
docker image prune -f >/dev/null

echo ""
echo "C'est en ligne :"
echo "  page d'accueil : https://$DOMAINE"
echo "  outil          : https://app.$DOMAINE"
echo "(Le premier certificat HTTPS peut prendre une minute.)"
