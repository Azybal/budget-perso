"""Synchronisation directe avec la banque, via Woob, sans intermédiaire.

Lancé uniquement par l'appli « Budget perso », avec le Python isolé de l'appli :
    python bank_sync.py
Première ligne de l'entrée standard (JSON) : la banque et ses identifiants, lus dans le trousseau du système
(Trousseau macOS, Gestionnaire d'identification Windows, Secret Service Linux) par l'appli :
    {"module": "cragr", "nom": "Crédit Agricole", "params": {"website": "...", "login": "...", "password": "..."}}
(l'ancien format {"website", "login", "password"} reste accepté : Crédit Agricole).
Ils restent en mémoire le temps de la connexion : jamais écrits dans un fichier, jamais passés en argument
ni en variable d'environnement, jamais affichés.

Double authentification : si la banque demande un code (SMS, carte…), le script émet
{"event": "question", "fields": [...]} et attend une ligne JSON {"id_du_champ": "valeur"} sur l'entrée standard ;
si elle demande une validation dans son application, il émet {"event": "validation", ...} et attend qu'elle soit faite.

Sortie : une ligne JSON par événement, ex. {"event": "status", "message": "..."}.
"""
import json
import os
import sys
from datetime import datetime, timedelta

import core

WOOB_DIR = os.path.join(os.path.dirname(core.DB_PATH), "woob")
STATE_FILE = os.path.join(os.path.dirname(core.DB_PATH), "bank.json")
DEFAULT_WEBSITE = None  # la caisse régionale est choisie à la connexion
NOMS = {"cragr": "Crédit Agricole"}


def emit(event, **kw):
    sys.stdout.write(json.dumps({"event": event, **kw}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"
    with open(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_FILE)


def normalize_creds(creds):
    """Accepte l'ancien format (Crédit Agricole seul) et le nouveau (toute banque Woob)."""
    if "module" in creds:
        return creds["module"], creds.get("nom") or NOMS.get(creds["module"], creds["module"]), dict(creds.get("params") or {})
    return "cragr", "Crédit Agricole", {"website": creds.get("website") or DEFAULT_WEBSITE,
                                        "login": creds.get("login"), "password": creds.get("password")}


def build_backend(module, params):
    # Woob, ses modules et l'état des sessions vivent dans le dossier de données : rien dans ~/.config.
    from woob.core import Woob
    from woob.tools.storage import StandardStorage
    os.makedirs(os.path.join(WOOB_DIR, "sessions"), exist_ok=True)
    w = Woob(workdir=WOOB_DIR, datadir=WOOB_DIR)
    info = w.repositories.get_module_info(module)
    if not info or not info.is_installed():
        emit("status", message="Installation du module de connexion de la banque…")
        w.repositories.update_repositories()
        w.repositories.install(module)
    # La session est gardée (fichier local, lisible seulement par ton compte) pour que la banque
    # ne redemande pas une double authentification à chaque synchronisation.
    storage = StandardStorage(os.path.join(WOOB_DIR, "sessions", f"{module}.yaml"))
    return w.build_backend(module, params=params, name=module, storage=storage)


def enable_interactive(backend):
    """Mode interactif : la banque peut demander un code SMS ou une validation dans son appli."""
    if "request_information" in backend.config and backend.config["request_information"].get() is None:
        backend.config["request_information"].set({})


def account_name(bank, acc):
    label = (acc.label or "Compte").strip()
    suffix = str(acc.id or "")[-4:]
    return f"{bank} · {label}" + (f" ({suffix})" if suffix else "")


def account_kind(acc, name):
    """courant / epargne / carte, d'après le type fourni par la banque (sinon d'après le nom)."""
    t = getattr(acc, "type", None)
    try:
        from woob.capabilities.bank import Account
        if t in (Account.TYPE_CHECKING, Account.TYPE_JOINT):
            return "courant"
        if t == Account.TYPE_CARD:
            return "carte"
        if t not in (None, Account.TYPE_UNKNOWN):
            return "epargne"
    except Exception:  # noqa: BLE001
        pass
    return core.guess_kind(name)


def to_float(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def connect_accounts(backend, bank):
    """Récupère la liste des comptes en gérant la double authentification. Renvoie None en cas d'échec
    (l'erreur a déjà été signalée)."""
    from woob.exceptions import (ActionNeeded, BrowserIncorrectPassword, BrowserPasswordExpired,
                                 BrowserQuestion, BrowserRedirect, BrowserUnavailable, DecoupledValidation,
                                 NeedInteractive)
    for _ in range(6):
        try:
            return list(backend.iter_accounts())
        except BrowserQuestion as q:
            fields = [{"id": f.id, "label": str(f.label or getattr(f, "description", "") or f.id),
                       "masked": bool(getattr(f, "masked", False))} for f in q.fields]
            emit("question", banque=bank, fields=fields)
            line = sys.stdin.readline()
            if not line:
                emit("error", kind="validation", message=f"{bank} demande un code de vérification ({', '.join(f['label'] for f in fields)}), "
                                                         "mais cette version de l'appli ne peut pas le saisir.")
                return None
            answer = json.loads(line)
            if answer.get("_annuler"):
                emit("error", kind="annule", message="Connexion annulée.")
                return None
            for f in q.fields:
                backend.config[f.id].set(str(answer.get(f.id, "")))
        except DecoupledValidation as e:
            emit("validation", banque=bank,
                 message=(str(e) or "Valide la connexion dans l'application de ta banque.") + " L'appli attend ta validation…")
            if "resume" in backend.config:
                backend.config["resume"].set(True)
        except BrowserIncorrectPassword:
            emit("error", kind="identifiants",
                 message=f"Identifiants refusés par {bank}. Attention : après plusieurs erreurs, la banque bloque l'accès en ligne.")
            return None
        except BrowserPasswordExpired:
            emit("error", kind="action", message=f"{bank} demande de changer ton mot de passe : fais-le sur son site, puis reconnecte-toi.")
            return None
        except BrowserRedirect:
            emit("error", kind="action", message=f"{bank} demande une connexion par une page web spéciale, pas encore prise en charge.")
            return None
        except NeedInteractive:
            emit("error", kind="validation", message=f"{bank} demande une double authentification : relance la synchronisation depuis l'appli.")
            return None
        except ActionNeeded as e:
            emit("error", kind="action", message=f"{bank} demande une action : connecte-toi une fois sur son site depuis ton navigateur, "
                                                 f"puis relance la synchronisation. ({e})")
            return None
        except BrowserUnavailable as e:
            emit("error", kind="indisponible", message=f"Site de {bank} indisponible pour le moment : {e}")
            return None
    emit("error", kind="validation", message=f"{bank} : la double authentification n'a pas abouti. Réessaie dans un moment.")
    return None


def sync(creds, days_back=None):
    module, bank, params = normalize_creds(creds)
    state = load_state()
    emit("status", message=f"Connexion à {bank}…")
    try:
        backend = build_backend(module, params)
    except Exception as e:  # noqa: BLE001
        return emit("error", kind="interne", message=f"Module de connexion de {bank} indisponible : {type(e).__name__} : {e}")
    finally:
        params.clear()
    try:
        enable_interactive(backend)
        accounts = connect_accounts(backend, bank)
        if accounts is None:
            return

        # Première synchro de cette banque : tout l'historique fourni. Ensuite : 45 jours de recouvrement
        # (les doublons sont écartés automatiquement).
        ancien_format = "par_banque" not in state
        par_banque = state.setdefault("par_banque", {})
        last = (par_banque.get(module) or {}).get("last_sync")
        if not last and module == "cragr" and ancien_format:
            last = state.get("last_sync")  # compatibilité avec les synchros d'avant le multi-banques
        since = (datetime.fromisoformat(last).date() - timedelta(days=45)) if last and days_back is None else None

        conn = core.connect()
        total_added = 0
        summary = []
        try:
            for acc in accounts:
                name = account_name(bank, acc)
                emit("status", message=f"Lecture de « {name} »…")
                txs = []
                try:
                    for tr in backend.iter_history(acc):
                        d = tr.date or getattr(tr, "rdate", None)
                        if not d:
                            continue
                        d = d.date() if isinstance(d, datetime) else d
                        if since and d < since:
                            continue
                        amt = to_float(tr.amount)
                        label = (getattr(tr, "raw", None) or tr.label or "").strip()
                        if amt is None or not label:
                            continue
                        txs.append({"date": d, "label": label, "amount": amt})
                except NotImplementedError:
                    pass  # compte sans historique (ex. assurance-vie)
                res = core.insert_transactions(conn, name, txs, source="banque") if txs else {"ajoutees": 0}
                core.get_or_create_account(conn, name, "banque")
                kind = account_kind(acc, name)
                core.set_account_balance(conn, name, to_float(acc.balance), kind)
                if kind == "courant":
                    # Opérations à venir (paiements carte pas encore débités, prélèvements programmés)
                    try:
                        coming = []
                        for tr in backend.iter_coming(acc):
                            d = tr.date or getattr(tr, "rdate", None) or getattr(tr, "vdate", None) or datetime.now().date()
                            d = d.date() if isinstance(d, datetime) else d
                            amt = to_float(tr.amount)
                            label = (getattr(tr, "raw", None) or tr.label or "").strip()
                            if amt is not None and label:
                                coming.append({"date": d, "label": label, "amount": amt})
                        core.replace_coming(conn, name, coming)
                    except NotImplementedError:
                        pass
                    except Exception as e:  # noqa: BLE001 — la synchro continue même si cette page change
                        emit("status", message=f"Opérations à venir non lues ({type(e).__name__})")
                total_added += res["ajoutees"]
                summary.append({"compte": name, "solde": to_float(acc.balance), "nouvelles": res["ajoutees"]})
        finally:
            conn.close()
    finally:
        try:
            backend.deinit()  # enregistre l'état de session (évite une nouvelle double authentification)
        except Exception:  # noqa: BLE001
            pass

    now = datetime.now().isoformat(timespec="seconds")
    par_banque[module] = {"nom": bank, "last_sync": now, "nouvelles": total_added}
    state.update({"last_sync": now, "last_result": {"nouvelles": total_added, "comptes": summary}})
    if module == "cragr":
        state["website"] = (creds.get("params") or {}).get("website") or creds.get("website") or DEFAULT_WEBSITE
    save_state(state)
    emit("done", banque=bank, nouvelles=total_added, comptes=summary)


def main():
    os.umask(0o077)
    line = sys.stdin.readline()
    try:
        creds = json.loads(line)
        module, _, params = normalize_creds(creds)
        assert module and params
    except Exception:  # noqa: BLE001
        emit("error", kind="interne", message="Identifiants manquants.")
        return
    del line
    try:
        sync(creds)
    except Exception as e:  # noqa: BLE001
        # On n'affiche jamais les identifiants : uniquement le type d'erreur et son message.
        emit("error", kind="interne", message=f"{type(e).__name__} : {e}")
    finally:
        creds.clear()


if __name__ == "__main__":
    main()
