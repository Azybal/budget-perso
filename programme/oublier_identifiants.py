"""Efface du trousseau du système tous les identifiants bancaires enregistrés par Budget perso.
Utilisé par les désinstallateurs."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "moteur"))

import core  # noqa: E402
import keyring  # noqa: E402

modules = {"credit-agricole"}  # ancienne version
try:
    with open(os.path.join(os.path.dirname(core.DB_PATH), "banques_connectees.json"), encoding="utf-8") as f:
        modules |= {b["module"] for b in json.load(f)}
except (OSError, ValueError):
    pass
for m in modules:
    try:
        keyring.delete_password("BudgetPerso", m)
    except Exception:  # noqa: BLE001
        pass
print("Identifiants bancaires effacés du trousseau.")
