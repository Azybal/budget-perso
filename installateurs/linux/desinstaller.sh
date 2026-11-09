#!/bin/bash
# Budget perso — désinstallation sous Linux
BASE="${XDG_DATA_HOME:-$HOME/.local/share}/budget-perso"
echo "Désinstallation de Budget perso (ferme l'appli avant de continuer)."
read -r -p "Appuie sur Entrée pour continuer… " _

# Identifiants bancaires : retirés du trousseau (toutes les banques)
if [ -x "$BASE/python/bin/python" ]; then
  "$BASE/python/bin/python" "$BASE/programme/oublier_identifiants.py" 2>/dev/null || true
fi
rm -f "${XDG_DATA_HOME:-$HOME/.local/share}/applications/budget-perso.desktop"
rm -rf "$BASE/programme" "$BASE/python" "$BASE/python-base" "$BASE/outils"

read -r -p "Supprimer aussi tes données (opérations, abonnements, crédits…) ? Tape OUI pour confirmer : " R
if [ "$R" = "OUI" ]; then
  rm -rf "$BASE/donnees"
  echo "Données supprimées."
else
  echo "Données conservées dans $BASE/donnees (elles serviront si tu réinstalles)."
fi
rmdir "$BASE" 2>/dev/null || true
echo "Budget perso est désinstallé."
