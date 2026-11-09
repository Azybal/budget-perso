#!/bin/bash
# Budget perso — installation sous Linux (dans ton dossier utilisateur, sans sudo)
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
BASE="${XDG_DATA_HOME:-$HOME/.local/share}/budget-perso"
APPDIR="$BASE/programme"
VENV="$BASE/python"
UV_VERSION="0.13.7"

etape() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
echo "Installation de Budget perso"
echo "Tout s'installe dans : $BASE"
mkdir -p "$BASE/outils"

etape "Python 3.12 (OpenSSL 3, via l'outil officiel uv)"
case "$(uname -m)" in
  aarch64|arm64) ARCH="aarch64-unknown-linux-gnu" ;;
  x86_64|amd64)  ARCH="x86_64-unknown-linux-gnu" ;;
  *) echo "Processeur non pris en charge : $(uname -m)" >&2; exit 1 ;;
esac
UV="$BASE/outils/uv"
if [ ! -x "$UV" ] || ! "$UV" --version | grep -q "$UV_VERSION"; then
  TMP="$(mktemp -d)"
  URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$ARCH.tar.gz"
  curl -fsSL "$URL" -o "$TMP/uv.tar.gz"
  curl -fsSL "$URL.sha256" -o "$TMP/uv.sha256"
  ATTENDU="$(awk '{print $1}' "$TMP/uv.sha256")"
  OBTENU="$(sha256sum "$TMP/uv.tar.gz" | awk '{print $1}')"
  if [ "$ATTENDU" != "$OBTENU" ]; then echo "Téléchargement de uv corrompu : arrêt." >&2; exit 1; fi
  tar -xzf "$TMP/uv.tar.gz" -C "$TMP"
  cp "$TMP/uv-$ARCH/uv" "$UV"
  chmod 755 "$UV"
  rm -rf "$TMP"
fi
export UV_PYTHON_INSTALL_DIR="$BASE/python-base"
"$UV" python install 3.12 --quiet
PY="$("$UV" python find 3.12)"
echo "Python : $PY"

etape "Copie du programme"
mkdir -p "$APPDIR"
cp -R "$SRC/programme/." "$APPDIR/"

etape "Composants (quelques minutes la première fois)"
[ -x "$VENV/bin/python" ] || "$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip --quiet --disable-pip-version-check
"$VENV/bin/python" -m pip install --quiet --disable-pip-version-check -r "$APPDIR/requirements.txt"

etape "Raccourci dans le menu des applications"
DESK="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$DESK"
cat > "$DESK/budget-perso.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Budget perso
Comment=Budget personnel connecté à ta banque, 100 % local
Exec="$VENV/bin/python" "$APPDIR/BudgetPerso.pyw"
Icon=$APPDIR/budget.png
Terminal=false
Categories=Office;Finance;
EOF
chmod 644 "$DESK/budget-perso.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$DESK" >/dev/null 2>&1 || true

# Trousseau sécurisé : nécessaire pour enregistrer les identifiants bancaires
if ! "$VENV/bin/python" -c "import keyring,sys; n=type(keyring.get_keyring()).__name__.lower(); sys.exit(1 if any(w in n for w in ('fail','plaintext','null')) else 0)" 2>/dev/null; then
  printf '\n\033[1;33mAttention : aucun trousseau sécurisé détecté (GNOME Keyring ou KWallet).\033[0m\n'
  echo "Installe-en un pour pouvoir connecter ta banque (ex. : sudo apt install gnome-keyring)."
fi

printf '\n\033[1;32mC'"'"'est installé ! Ouvre « Budget perso » depuis le menu des applications.\033[0m\n'
