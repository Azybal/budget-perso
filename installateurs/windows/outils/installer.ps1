# Budget perso — installation sous Windows (dans ton dossier utilisateur, sans droits administrateur)
$ErrorActionPreference = "Stop"
$Src    = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Base   = Join-Path $env:LOCALAPPDATA "BudgetPerso"
$AppDir = Join-Path $Base "programme"
$Venv   = Join-Path $Base "python"

function Etape($t) { Write-Host ""; Write-Host "==> $t" -ForegroundColor Cyan }

function Trouver-Python {
    try {
        $p = & py -3.12 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $p) { return $p.Trim() }
    } catch {}
    $cand = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path $cand) { return $cand }
    return $null
}

Write-Host "Installation de Budget perso" -ForegroundColor White
Write-Host "Tout s'installe dans : $Base"

Etape "Python 3.12"
$py = Trouver-Python
if (-not $py) {
    Write-Host "Python 3.12 n'est pas installé : installation depuis la source officielle (winget)…"
    try {
        winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
    } catch {}
    $py = Trouver-Python
    if (-not $py) {
        Write-Host "Impossible d'installer Python automatiquement." -ForegroundColor Red
        Write-Host "Installe Python 3.12 depuis https://www.python.org/downloads/windows/ (case « Add python.exe to PATH »),"
        Write-Host "puis relance Installer.bat."
        exit 1
    }
}
Write-Host "Python trouvé : $py"

Etape "Copie du programme"
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
Copy-Item -Recurse -Force (Join-Path $Src "programme\*") $AppDir

Etape "Environnement Python dédié (quelques minutes la première fois)"
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) { & $py -m venv $Venv }
$vpy = Join-Path $Venv "Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet --disable-pip-version-check
& $vpy -m pip install --quiet --disable-pip-version-check -r (Join-Path $AppDir "requirements.txt")
if ($LASTEXITCODE -ne 0) { Write-Host "L'installation des composants a échoué." -ForegroundColor Red; exit 1 }

Etape "Composant d'affichage de la fenêtre (Microsoft Edge WebView2)"
$wv = $null
$cle = "Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
foreach ($k in @("HKLM:\SOFTWARE\WOW6432Node\$cle", "HKLM:\SOFTWARE\$cle", "HKCU:\Software\$cle")) {
    try { $v = (Get-ItemProperty -Path $k -Name pv -ErrorAction Stop).pv; if ($v -and $v -ne "0.0.0.0") { $wv = $v; break } } catch {}
}
if ($wv) { Write-Host "WebView2 est présent (version $wv)." }
else {
    Write-Host "WebView2 est absent : installation depuis la source officielle (winget)…"
    try { winget install -e --id Microsoft.EdgeWebView2Runtime --accept-source-agreements --accept-package-agreements }
    catch { Write-Host "Installe « Microsoft Edge WebView2 Runtime » depuis https://developer.microsoft.com/microsoft-edge/webview2/" -ForegroundColor Yellow }
}

Etape "Vérification des composants de la fenêtre"
& $vpy -c "import webview, clr; import webview.platforms.winforms; print('Composants de la fenêtre : OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "La fenêtre ne pourra pas s'ouvrir : le message d'erreur ci-dessus indique pourquoi (prends-le en photo)." -ForegroundColor Red
}
Copy-Item -Force (Join-Path $Src "Depanner.bat") $Base -ErrorAction SilentlyContinue

Etape "Raccourcis (Bureau et menu Démarrer)"
$pyw    = Join-Path $Venv "Scripts\pythonw.exe"
$target = Join-Path $AppDir "BudgetPerso.pyw"
$ws = New-Object -ComObject WScript.Shell
$dossiers = @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))
foreach ($d in $dossiers) {
    $lnk = $ws.CreateShortcut((Join-Path $d "Budget perso.lnk"))
    $lnk.TargetPath = $pyw
    $lnk.Arguments = "`"$target`""
    $lnk.WorkingDirectory = $AppDir
    $lnk.IconLocation = (Join-Path $AppDir "budget.ico")
    $lnk.Description = "Budget perso"
    $lnk.Save()
}

Write-Host ""
Write-Host "C'est installé ! Ouvre « Budget perso » depuis le Bureau ou le menu Démarrer." -ForegroundColor Green
