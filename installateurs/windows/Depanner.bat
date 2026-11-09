@echo off
chcp 65001 >nul
title Budget perso - dépannage
echo Lancement de Budget perso avec affichage des erreurs...
echo (garde cette fenêtre ouverte ; ferme Budget perso pour revenir ici)
echo.
set "PY=%LOCALAPPDATA%\BudgetPerso\python\Scripts\python.exe"
set "APP=%LOCALAPPDATA%\BudgetPerso\programme\BudgetPerso.pyw"
if not exist "%PY%" (
  echo Python de Budget perso introuvable : %PY%
  echo L'installation n'est pas allée au bout. Relance « Installer.bat ».
  goto fin
)
if not exist "%APP%" (
  echo Programme introuvable : %APP%
  echo Relance « Installer.bat ».
  goto fin
)
"%PY%" "%APP%"
echo.
echo ------------------------------------------------------------
echo Code de sortie : %ERRORLEVEL%
echo Si une erreur s'affiche ci-dessus, prends-la en photo.
echo Elle est aussi enregistrée dans %LOCALAPPDATA%\BudgetPerso\erreur.txt
:fin
echo.
pause
