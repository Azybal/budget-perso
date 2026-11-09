# Budget perso — désinstallation
$Base = Join-Path $env:LOCALAPPDATA "BudgetPerso"
$vpy  = Join-Path $Base "python\Scripts\python.exe"

Write-Host "Désinstallation de Budget perso (ferme l'appli avant de continuer)."
Read-Host "Appuie sur Entrée pour continuer" | Out-Null

# Identifiants bancaires : retirés du Gestionnaire d'identification de Windows (toutes les banques)
if (Test-Path $vpy) {
    & $vpy (Join-Path $Base "programme\oublier_identifiants.py") 2>$null
}

# Raccourcis
$liens = @((Join-Path ([Environment]::GetFolderPath("Desktop")) "Budget perso.lnk"),
           (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Budget perso.lnk"))
foreach ($l in $liens) { if (Test-Path $l) { Remove-Item -Force $l } }

# Programme et Python dédié
foreach ($d in @("programme", "python")) {
    $p = Join-Path $Base $d
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}

$r = Read-Host "Supprimer aussi tes données (opérations, abonnements, crédits…) ? Tape OUI pour confirmer"
if ($r -ceq "OUI") {
    $p = Join-Path $Base "donnees"
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
    Write-Host "Données supprimées."
} else {
    Write-Host "Données conservées dans $Base\donnees (elles serviront si tu réinstalles)."
}
Write-Host "Budget perso est désinstallé." -ForegroundColor Green
