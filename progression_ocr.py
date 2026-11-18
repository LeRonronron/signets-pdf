# -*- coding: utf-8 -*-
"""
Petit « plugin » pour ocrmypdf : il transmet l'avancement de l'OCR
(« OCR : page 120/400 ») à la fonction `rappel` définie par signets.py.

ocrmypdf charge ce fichier lui-même (paramètre plugins=...) ; il n'y a rien
à appeler directement ici.
"""
from ocrmypdf import hookimpl

# Fonction appelée à chaque progrès : rappel(fait, total, description)
rappel = None


class BarreVersRappel:
    """Fait semblant d'être une barre de progression et relaie les chiffres."""

    def __init__(self, *, total=None, desc=None, unit=None, disable=False, **kwargs):
        self.total = total
        self.desc = desc or ""
        self.fait = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def update(self, n=1, *, completed=None):
        self.fait = completed if completed is not None else self.fait + n
        if rappel is not None:
            try:
                rappel(self.fait, self.total, self.desc)
            except Exception:
                pass  # un souci d'affichage ne doit jamais casser l'OCR


@hookimpl
def get_progressbar_class():
    return BarreVersRappel
