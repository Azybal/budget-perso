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
