# ---------------------------------------------------------------------------
# Recette pour Hugging Face Spaces : elle décrit l'ordinateur virtuel sur lequel
# l'application tournera. Hugging Face la lit et fabrique cet ordinateur tout seul.
# ---------------------------------------------------------------------------

# 1. Point de départ : un Linux (Debian) avec Python 3.12 déjà installé
FROM python:3.12-slim

# 2. Logiciels de base : Tesseract (OCR) + langues française et anglaise, Ghostscript
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-fra tesseract-ocr-eng ghostscript \
    && rm -rf /var/lib/apt/lists/*

# 3. Hugging Face demande de travailler avec un utilisateur ordinaire (numéro 1000)
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1
WORKDIR /home/user/app

# 4. Bibliothèques Python (PyMuPDF, rapidfuzz, Streamlit, ocrmypdf)
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# 5. Le code de l'application
COPY --chown=user . .

# 6. Démarrage : Streamlit écoute sur le port 7860 (celui qu'attend Hugging Face).
#    Les deux options « false » sont nécessaires pour que l'envoi de fichiers
#    fonctionne dans la page de Hugging Face.
EXPOSE 7860
CMD ["streamlit", "run", "app.py", \
     "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true", \
     "--server.enableXsrfProtection=false", "--server.enableCORS=false"]
