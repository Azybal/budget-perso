"""Mises à jour automatiques de Budget perso.

1. Demande à GitHub s'il existe une version plus récente (aucune donnée personnelle n'est envoyée :
   seulement une requête « quelle est la dernière version ? »).
2. Télécharge le paquet et sa signature, et vérifie la signature avec la clé publique de l'auteur :
   un fichier modifié ou venant de quelqu'un d'autre est refusé.
3. Installe en gardant une copie de la version précédente, et la remet si quelque chose échoue.
Tes données (dossier « donnees ») ne sont jamais touchées.
"""
import base64
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
UA = "BudgetPerso-mises-a-jour"
MAX_TAILLE = 30 * 1024 * 1024


def _conf():
    try:
        with open(os.path.join(HERE, "mise_a_jour.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def version_actuelle():
    try:
        with open(os.path.join(HERE, "version.txt"), encoding="utf-8") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return 0


def _journal(msg):
    """Petit journal technique (sans données personnelles) pour comprendre un éventuel échec."""
    try:
        import core
        path = os.path.join(os.path.dirname(core.DB_PATH), "mises-a-jour.log")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}  {msg}\n")
    except Exception:  # noqa: BLE001
        pass


def _get(url, accept="application/octet-stream"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = r.read(MAX_TAILLE + 1)
    if len(data) > MAX_TAILLE:
        raise ValueError("fichier trop gros")
    return data


def chercher():
    """Renvoie la mise à jour disponible (ou None)."""
    conf = _conf()
    depot = conf.get("depot")
    if not depot:
        return None
    api = conf.get("api", "https://api.github.com")
    info = json.loads(_get(f"{api}/repos/{depot}/releases/latest", "application/vnd.github+json"))
    v = int(str(info.get("tag_name", "v0")).lstrip("v"))
    if v <= version_actuelle():
        return None
    assets = {a["name"]: a["browser_download_url"] for a in info.get("assets", [])}
    if "mise-a-jour.zip" not in assets or "mise-a-jour.zip.sig" not in assets:
        return None
    return {"version": v, "zip": assets["mise-a-jour.zip"], "sig": assets["mise-a-jour.zip.sig"],
            "notes": (info.get("body") or "").split("———")[0].strip()}  # sans la note d'installation


def telecharger_et_verifier(m):
    """Télécharge et vérifie la signature. Lève une exception si quoi que ce soit ne va pas."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    data = _get(m["zip"])
    sig = base64.b64decode(_get(m["sig"]).strip())
    cle = Ed25519PublicKey.from_public_bytes(base64.b64decode(_conf()["cle_publique"]))
    cle.verify(sig, data)  # InvalidSignature si le fichier n'est pas exactement celui signé par l'auteur
    z = zipfile.ZipFile(io.BytesIO(data))
    v = int(z.read("version.txt").decode("utf-8").strip())
    if v != m["version"] or v <= version_actuelle():
        raise ValueError("numéro de version incohérent")
    for n in z.namelist():
        parts = n.replace("\\", "/").split("/")
        if n.startswith(("/", "\\")) or ".." in parts or ":" in n:
            raise ValueError("chemin interdit dans le paquet : " + n)
    return z, v


def _copier(src, dst):
    for dirpath, _, files in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        os.makedirs(os.path.join(dst, rel), exist_ok=True)
        for fn in files:
            shutil.copy2(os.path.join(dirpath, fn), os.path.join(dst, rel, fn))


def installer(z):
    tmp = tempfile.mkdtemp(prefix="budgetperso-maj-")
    sauvegarde = HERE + ".precedent"
    try:
        z.extractall(tmp)
        if os.path.exists(sauvegarde):
            shutil.rmtree(sauvegarde)
        shutil.copytree(HERE, sauvegarde, ignore=shutil.ignore_patterns("__pycache__"))
        avant = open(os.path.join(HERE, "requirements.txt"), encoding="utf-8").read()
        try:
            _copier(tmp, HERE)
            apres = open(os.path.join(HERE, "requirements.txt"), encoding="utf-8").read()
            if apres != avant:  # nouveaux composants à installer
                exe = sys.executable
                if exe.lower().endswith("pythonw.exe"):
                    alt = exe[: -len("pythonw.exe")] + "python.exe"
                    exe = alt if os.path.exists(alt) else exe
                subprocess.run([exe, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r",
                                os.path.join(HERE, "requirements.txt")], check=True,
                               creationflags=0x08000000 if os.name == "nt" else 0)
        except Exception:
            _copier(sauvegarde, HERE)  # retour à la version précédente
            raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def verifier_et_installer():
    """Cherche, vérifie et installe. Renvoie {"version", "notes"} si une mise à jour a été installée, sinon None."""
    try:
        m = chercher()
        if not m:
            return None
        z, v = telecharger_et_verifier(m)
        installer(z)
        _journal(f"version {v} installée")
        return {"version": v, "notes": m["notes"]}
    except Exception as e:  # noqa: BLE001 — une mise à jour ratée ne doit jamais gêner l'utilisation
        _journal(f"échec : {type(e).__name__} : {e}")
        return None
