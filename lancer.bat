@echo off
rem ---------------------------------------------------------------------------
rem  Lance l'outil de signets sur ce PC (Windows) : double-cliquez sur ce fichier.
rem  La premiere fois, il installe les bibliotheques Python (quelques minutes).
rem  Ensuite, la page s'ouvre dans le navigateur : http://localhost:8501
rem ---------------------------------------------------------------------------
cd /d "%~dp0"
if exist "C:\Program Files\Tesseract-OCR\tesseract.exe" set "PATH=C:\Program Files\Tesseract-OCR;%PATH%"
rem Langues de l'OCR (francais + anglais) rangees dans le sous-dossier tessdata
if exist "%~dp0tessdata\fra.traineddata" set "TESSDATA_PREFIX=%~dp0tessdata"

rem Les bibliotheques sont-elles deja installees, et completes ?
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -c "import streamlit, pymupdf, rapidfuzz, ocrmypdf" 2>nul && goto lancer
)

echo Installation des bibliotheques Python, patientez quelques minutes...
if exist ".venv" rmdir /s /q ".venv"
py -3 -m venv .venv 2>nul || python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -c "import streamlit, pymupdf, rapidfuzz, ocrmypdf" 2>nul && goto lancer

echo.
echo ===========================================================================
echo  ERREUR : l'installation des bibliotheques a echoue.
echo.
echo  Cause la plus frequente : ce dossier est range trop "profond" sur le disque
echo  et Windows refuse les chemins de plus de 260 caracteres.
echo  Deplacez le dossier, par exemple vers C:\signets-pdf ou dans Documents,
echo  puis double-cliquez de nouveau sur lancer.bat.
echo.
echo  Autre cause possible : Python n'est pas installe. Installez-le avec :
echo      winget install Python.Python.3.12
echo ===========================================================================
pause
exit /b 1

:lancer
rem "echo." repond a vide a la question "Email" que Streamlit pose au premier lancement
echo.| .venv\Scripts\python.exe -m streamlit run app.py
pause
