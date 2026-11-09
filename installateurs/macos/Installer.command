#!/bin/bash
# Budget perso — installation sous macOS (dans ton dossier utilisateur, sans mot de passe administrateur)
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
BASE="$HOME/Library/Application Support/BudgetPerso"
APPDIR="$BASE/programme"
VENV="$BASE/python"
APP="$HOME/Applications/Budget perso.app"
UV_VERSION="0.13.7"

etape() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }
echo "Installation de Budget perso"
echo "Tout s'installe dans : $BASE"
mkdir -p "$BASE/outils"

etape "Python 3.12 (OpenSSL 3, via l'outil officiel uv)"
case "$(uname -m)" in
  arm64) ARCH="aarch64-apple-darwin" ;;
  *)     ARCH="x86_64-apple-darwin" ;;
esac
UV="$BASE/outils/uv"
if [ ! -x "$UV" ] || ! "$UV" --version | grep -q "$UV_VERSION"; then
  TMP="$(mktemp -d)"
  URL="https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-$ARCH.tar.gz"
  curl -fsSL "$URL" -o "$TMP/uv.tar.gz"
  curl -fsSL "$URL.sha256" -o "$TMP/uv.sha256"
  ATTENDU="$(awk '{print $1}' "$TMP/uv.sha256")"
  OBTENU="$(shasum -a 256 "$TMP/uv.tar.gz" | awk '{print $1}')"
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

etape "Application « Budget perso » (dossier Applications de ton compte)"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cat > "$APP/Contents/MacOS/BudgetPerso" <<'LANCEUR'
#!/bin/bash
BASE="$HOME/Library/Application Support/BudgetPerso"
exec "$BASE/python/bin/python" "$BASE/programme/BudgetPerso.pyw"
LANCEUR
chmod 755 "$APP/Contents/MacOS/BudgetPerso"
cp "$APPDIR/budget.icns" "$APP/Contents/Resources/AppIcon.icns"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Budget perso</string>
  <key>CFBundleDisplayName</key><string>Budget perso</string>
  <key>CFBundleIdentifier</key><string>io.github.budget-perso</string>
  <key>CFBundleExecutable</key><string>BudgetPerso</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.finance</string>
</dict></plist>
PLIST
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || true
touch "$APP"

printf '\n\033[1;32mC'"'"'est installé ! Ouvre « Budget perso » depuis le Launchpad ou le dossier Applications de ton compte.\033[0m\n'
open "$HOME/Applications" >/dev/null 2>&1 || true
