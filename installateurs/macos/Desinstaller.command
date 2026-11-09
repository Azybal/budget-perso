#!/bin/bash
# Budget perso — désinstallation sous macOS
BASE="$HOME/Library/Application Support/BudgetPerso"
echo "Désinstallation de Budget perso (quitte l'appli avant de continuer)."
read -r -p "Appuie sur Entrée pour continuer… " _

# Identifiants bancaires : retirés du Trousseau (toutes les banques)
if [ -x "$BASE/python/bin/python" ]; then
  "$BASE/python/bin/python" "$BASE/programme/oublier_identifiants.py" 2>/dev/null || true
fi
rm -rf "$HOME/Applications/Budget perso.app" "$BASE/programme" "$BASE/python" "$BASE/python-base" "$BASE/outils"

read -r -p "Supprimer aussi tes données (opérations, abonnements, crédits…) ? Tape OUI pour confirmer : " R
if [ "$R" = "OUI" ]; then
  rm -rf "$BASE/donnees"
  echo "Données supprimées."
else
  echo "Données conservées dans $BASE/donnees (elles serviront si tu réinstalles)."
fi
rmdir "$BASE" 2>/dev/null || true
echo "Budget perso est désinstallé."
