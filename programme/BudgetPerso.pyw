"""Budget perso — lanceur (Windows, macOS, Linux).

Ouvre l'interface dans une vraie fenêtre (pas le navigateur), démarre le moteur local et gère la
connexion aux banques. Tout reste sur cet ordinateur :
- les données sont dans le dossier de l'appli (accessible seulement à ton compte) ;
- les identifiants bancaires sont rangés dans le trousseau sécurisé du système (Gestionnaire d'identification
  Windows, Trousseau macOS, trousseau GNOME/KDE sous Linux), jamais dans un fichier ;
- aucun serveur extérieur n'est contacté, à part les sites de tes banques pendant une synchronisation
  et GitHub pour savoir s'il existe une mise à jour.
"""
import json
import os
import secrets
import subprocess
import sys
import threading
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
MOTEUR = os.path.join(HERE, "moteur")
sys.path.insert(0, MOTEUR)

# Clé secrète propre à ce lancement : le moteur local ne répond qu'à cette fenêtre.
TOKEN = secrets.token_urlsafe(32)
os.environ["BUDGET_TOKEN"] = TOKEN

import core  # noqa: E402
import server  # noqa: E402  (lit BUDGET_TOKEN à l'import)
import keyring  # noqa: E402
import webview  # noqa: E402
import mise_a_jour  # noqa: E402

SERVICE = "BudgetPerso"
with open(os.path.join(HERE, "banques.json"), encoding="utf-8") as f:
    BANQUES = {b["module"]: b for b in json.load(f)}
LISTE = os.path.join(os.path.dirname(core.DB_PATH), "banques_connectees.json")  # noms seulement, aucun secret


# --------------------------------------------------------------------------- trousseau du système
def trousseau_sur():
    """Refuse les trousseaux non chiffrés (fichier en clair) : mieux vaut ne rien enregistrer."""
    name = type(keyring.get_keyring()).__name__.lower()
    return not any(w in name for w in ("fail", "plaintext", "null"))


def banques_connectees():
    try:
        with open(LISTE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _enregistrer_liste(lst):
    os.makedirs(os.path.dirname(LISTE), exist_ok=True)
    with open(os.open(LISTE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(lst, f, ensure_ascii=False)


def lire_identifiants(module):
    try:
        raw = keyring.get_password(SERVICE, module)
        return json.loads(raw) if raw else None
    except Exception:  # noqa: BLE001
        return None


def oublier(module):
    try:
        keyring.delete_password(SERVICE, module)
    except Exception:  # noqa: BLE001
        pass
    _enregistrer_liste([b for b in banques_connectees() if b["module"] != module])


def migrer_ancienne_version():
    """Version 1 (Crédit Agricole seul) : identifiants rangés sous « credit-agricole »."""
    try:
        raw = keyring.get_password(SERVICE, "credit-agricole")
    except Exception:  # noqa: BLE001
        return
    if not raw:
        return
    old = json.loads(raw)
    keyring.set_password(SERVICE, "cragr", json.dumps({"module": "cragr", "nom": "Crédit Agricole", "params": old}))
    keyring.delete_password(SERVICE, "credit-agricole")
    lst = banques_connectees()
    if not any(b["module"] == "cragr" for b in lst):
        _enregistrer_liste(lst + [{"module": "cragr", "nom": "Crédit Agricole"}])


def derniere_synchro():
    try:
        with open(os.path.join(os.path.dirname(core.DB_PATH), "bank.json"), encoding="utf-8") as f:
            return datetime.fromisoformat(json.load(f)["last_sync"])
    except Exception:  # noqa: BLE001
        return None


def python_console():
    """Sous Windows, pythonw.exe n'a pas de sortie : on lance la synchro avec python.exe (sans fenêtre)."""
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        alt = exe[: -len("pythonw.exe")] + "python.exe"
        if os.path.exists(alt):
            return alt
    return exe


SANS_FENETRE = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


# --------------------------------------------------------------------------- fonctions appelées par la page
class Api:
    """window.pywebview.api.* — les identifiants passent de la fenêtre au programme en mémoire, sans réseau."""

    def __init__(self):
        self._window = None
        self._proc = None
        self._lock = threading.Lock()
        self._running = False

    def _push(self, obj):
        if self._window:
            self._window.evaluate_js("window.bankEvent && window.bankEvent(%s)" % json.dumps(obj, ensure_ascii=False))

    # --- banques
    def banques(self):
        """Banques proposées et champs à remplir pour chacune."""
        return sorted(BANQUES.values(), key=lambda b: core.strip_accents(b["nom"]).lower())

    def status(self):
        return {"connectees": banques_connectees(), "syncing": self._running, "trousseau_ok": trousseau_sur(),
                "systeme": {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")}

    def connect(self, module, valeurs):
        b = BANQUES.get(module)
        if not b:
            return {"ok": False, "erreur": "Choisis ta banque."}
        if not trousseau_sur():
            return {"ok": False, "erreur": "Aucun trousseau sécurisé n'est disponible sur cet ordinateur (sous Linux : "
                                           "installe et ouvre GNOME Keyring ou KWallet). Les identifiants ne seront pas enregistrés."}
        import re
        params = {}
        for c in b["champs"]:
            v = str((valeurs or {}).get(c["id"], c.get("default", ""))).strip()
            if c["type"] == "bool":
                v = "true" if v in ("true", "1", "on", "True") else "false"
            if not v and c["type"] != "bool":
                return {"ok": False, "erreur": f"Remplis « {c['label']} »."}
            if c.get("regexp") and v and not re.fullmatch(c["regexp"].strip("^$"), v):
                return {"ok": False, "erreur": f"« {c['label']} » n'a pas le bon format."}
            params[c["id"]] = v
        keyring.set_password(SERVICE, module, json.dumps({"module": module, "nom": b["nom"], "params": params}))
        params.clear()
        lst = [x for x in banques_connectees() if x["module"] != module] + [{"module": module, "nom": b["nom"]}]
        _enregistrer_liste(lst)
        self._sync(auto=False, seulement=[module])
        return {"ok": True}

    def disconnect(self, module):
        oublier(module)
        self._push({"event": "state", "connected": bool(banques_connectees()), "syncing": self._running})
        return {"ok": True}

    def message(self, cmd):
        if cmd == "sync":
            self._sync(auto=False)
        elif cmd == "state":
            self._push({"event": "state", "connected": bool(banques_connectees()), "syncing": self._running})
        return True

    # --- double authentification : réponse de l'utilisateur transmise au script de synchro
    def answer(self, valeurs):
        return self._ecrire(json.dumps(valeurs or {}))

    def cancel_question(self):
        return self._ecrire(json.dumps({"_annuler": True}))

    def _ecrire(self, line):
        p = self._proc
        if p and p.poll() is None:
            try:
                p.stdin.write((line + "\n").encode("utf-8"))
                p.stdin.flush()
                return True
            except Exception:  # noqa: BLE001
                pass
        return False

    # --- mises à jour
    def version(self):
        return mise_a_jour.version_actuelle()

    def restart(self):
        flags = (0x00000008 | SANS_FENETRE) if os.name == "nt" else 0  # DETACHED_PROCESS
        subprocess.Popen([sys.executable, os.path.join(HERE, "BudgetPerso.pyw")], cwd=HERE, creationflags=flags,
                         start_new_session=(os.name != "nt"))
        if self._window:
            self._window.destroy()
        return True

    def _updates_loop(self):
        import time
        time.sleep(20)  # laisse l'appli démarrer tranquillement
        while True:
            res = mise_a_jour.verifier_et_installer()
            if res:
                self._push({"event": "update_installed", **res})
                return  # la nouvelle version prendra le relais au redémarrage
            time.sleep(6 * 3600)

    # --- synchronisation : une banque après l'autre, chacune dans un processus séparé
    def _sync(self, auto, seulement=None):
        with self._lock:
            if self._running:
                return
            lst = [b for b in banques_connectees() if not seulement or b["module"] in seulement]
            if not lst:
                if not auto:
                    self._push({"event": "need_connect"})
                return
            self._running = True
        self._push({"event": "status", "message": "Synchronisation…"})
        threading.Thread(target=self._run_all, args=(lst, auto), daemon=True).start()

    def _run_all(self, lst, auto):
        try:
            for b in lst:
                creds = lire_identifiants(b["module"])
                if creds:
                    self._run_one(b, creds, auto)
        finally:
            self._running = False
            self._push({"event": "finished"})

    def _run_one(self, b, creds, auto):
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONWARNINGS="ignore")
        env.pop("BUDGET_TOKEN", None)
        proc = subprocess.Popen([python_console(), "-u", os.path.join(MOTEUR, "bank_sync.py")], cwd=MOTEUR, env=env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                creationflags=SANS_FENETRE)
        self._proc = proc
        try:
            proc.stdin.write((json.dumps(creds) + "\n").encode("utf-8"))  # canal privé, en mémoire
            proc.stdin.flush()
        except Exception:  # noqa: BLE001
            pass
        creds.clear()
        for raw in proc.stdout:
            try:
                ev = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            ev["auto"] = auto
            if ev.get("event") == "error":
                if ev.get("kind") == "identifiants":
                    # Identifiants refusés : on les efface pour ne pas réessayer en boucle (blocage de l'accès)
                    oublier(b["module"])
                    ev["message"] = ev.get("message", "") + "\n\nTes identifiants ont été effacés : reconnecte cette banque."
                elif auto and ev.get("kind") == "indisponible":
                    ev["message"] = ""  # au lancement, on ne dérange pas pour un site momentanément indisponible
            self._push(ev)
        try:
            proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        proc.wait()
        self._proc = None


def icone_dock_macos():
    """Sous macOS, met l'icône de Budget perso dans le Dock (au lieu de celle de Python)."""
    if sys.platform != "darwin":
        return
    try:
        from Foundation import NSBundle
        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "Budget perso"  # nom affiché dans la barre des menus
        from AppKit import NSApplication, NSImage
        img = NSImage.alloc().initWithContentsOfFile_(os.path.join(HERE, "budget.png"))
        NSApplication.sharedApplication().setApplicationIconImage_(img)
    except Exception:  # noqa: BLE001
        pass


def main():
    migrer_ancienne_version()
    srv = server.ThreadingHTTPServer((server.HOST, 0), server.Handler)
    server.PORT = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    api = Api()
    win = webview.create_window("Budget perso", f"http://127.0.0.1:{server.PORT}/?t={TOKEN}", js_api=api,
                                width=1240, height=860, min_size=(420, 500), text_select=True)
    api._window = win
    first = {"done": False}

    def on_loaded():
        if first["done"]:
            return
        first["done"] = True
        ls = derniere_synchro()
        # Synchro automatique au lancement si la dernière date de plus de 6 heures
        if banques_connectees() and (not ls or (datetime.now() - ls).total_seconds() > 6 * 3600):
            api._sync(auto=True)
        threading.Thread(target=api._updates_loop, daemon=True).start()

    win.events.loaded += on_loaded
    icone_dock_macos()
    # private_mode : la fenêtre ne garde rien sur le disque (ni cache ni cookies)
    kwargs = {"private_mode": True, "icon": os.path.join(HERE, "budget.png")}
    if sys.platform.startswith("linux"):
        kwargs["gui"] = "qt"
    webview.start(**kwargs)
    if api._proc and api._proc.poll() is None:
        api._proc.terminate()
    srv.shutdown()


if __name__ == "__main__":
    main()
