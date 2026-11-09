"""Serveur web local : interface + API JSON. Lancement : python3 server.py
Accessible uniquement depuis cet ordinateur (127.0.0.1).
"""
import hmac
import json
import os
import secrets
import sys
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

import core

HOST, PORT = "127.0.0.1", int(os.environ.get("BUDGET_PORT", "8765"))
STATIC = os.path.join(core.APP_DIR, "static")
BANK_STATE = os.path.join(os.path.dirname(core.DB_PATH), "bank.json")
# Clé secrète propre à chaque lancement : sans elle, aucune donnée n'est servie
# (protège contre les autres programmes et les sites web qui tenteraient d'interroger ce serveur local).
TOKEN = os.environ.pop("BUDGET_TOKEN", "") or secrets.token_urlsafe(32)
COOKIE = "bp_session"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, payload, ctype="application/json; charset=utf-8"):
        body = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        return self.headers.get("Host", "") in (f"{HOST}:{PORT}", f"localhost:{PORT}")

    def _authorized(self):
        if not self._host_ok():
            return False
        c = SimpleCookie(self.headers.get("Cookie", ""))
        val = c[COOKIE].value if COOKIE in c else ""
        return hmac.compare_digest(val, TOKEN)

    def _deny(self):
        self._send(403, "<p style='font:15px -apple-system;padding:40px;color:#888'>Accès refusé. "
                        "Ouvre Budget perso depuis l'appli.</p>".encode(), "text/html; charset=utf-8")

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/" and self._host_ok() and hmac.compare_digest(q.get("t", ""), TOKEN):
            # Échange la clé contre un cookie de session, puis l'efface de l'adresse.
            self.send_response(302)
            self.send_header("Set-Cookie", f"{COOKIE}={TOKEN}; HttpOnly; SameSite=Strict; Path=/")
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if not self._authorized():
            return self._deny()
        if not u.path.startswith("/api/"):
            path = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            full = os.path.normpath(os.path.join(STATIC, path))
            if not full.startswith(STATIC) or not os.path.isfile(full):
                return self._send(404, {"erreur": "introuvable"})
            ctype = "text/html; charset=utf-8" if full.endswith(".html") else "application/octet-stream"
            with open(full, "rb") as f:
                return self._send(200, f.read(), ctype)
        conn = core.connect()
        try:
            r = u.path[5:]
            if r == "months":
                data = core.list_months(conn)
            elif r == "summary":
                data = core.summary(conn, month=q.get("month"))
            elif r == "history":
                data = core.monthly_history(conn, int(q.get("months", 12)))
            elif r == "transactions":
                start, end = q.get("start"), q.get("end")
                if q.get("month"):
                    start, end = core._month_bounds(q["month"])
                kind = q.get("kind")
                data = core.list_transactions(conn, start=start, end=end, category=q.get("category"),
                                              search=q.get("search"), account=q.get("account"),
                                              max_amount=-0.0001 if kind == "depenses" else None,
                                              min_amount=0.0001 if kind == "revenus" else None,
                                              limit=int(q.get("limit", 5000)))
            elif r == "balance":
                data = core.balances(conn)
            elif r == "loans":
                data = core.list_loans(conn)
                data["prelevements_candidats"] = core.loan_candidates(conn)
            elif r == "forecast":
                data = core.forecast(conn)
            elif r == "subscriptions":
                data = core.subscription_list(conn)
            elif r == "settings":
                data = {k: core.get_setting(conn, k) for k in core.SETTINGS_DEFAULTS}
            elif r == "about":
                data = core.about(conn)
            elif r == "coming":
                data = core.list_coming(conn)
            elif r == "debts":
                data = core.list_debts(conn)
            elif r == "planned":
                data = core.planned_list(conn)
            elif r == "subscription-suggestions":
                data = core.subscription_suggestions(conn)
            elif r == "budget-category":
                data = core.budget_category_detail(conn, q["name"], q.get("month") or core.cycle_of(core.date.today()),
                                                   q.get("q"))
            elif r == "budget-table":
                data = core.budget_table(conn, q.get("month") or core.cycle_of(core.date.today()))
            elif r == "categories":
                data = core.categories(conn)
            elif r == "accounts":
                data = core.accounts(conn)
            elif r == "bank-status":
                try:
                    with open(BANK_STATE, encoding="utf-8") as f:
                        st = json.load(f)
                except (OSError, ValueError):
                    st = {}
                data = {"derniere_synchro": st.get("last_sync"), "resultat": st.get("last_result")}
            elif r == "merchants":
                start = end = None
                if q.get("month"):
                    start, end = core._month_bounds(q["month"])
                data = core.top_merchants(conn, start, end)
            else:
                return self._send(404, {"erreur": "route inconnue"})
            self._send(200, data)
        except Exception as e:  # noqa: BLE001
            self._send(400, {"erreur": str(e)})
        finally:
            conn.close()

    def do_POST(self):
        if not self._authorized():
            return self._deny()
        # Protection contre les requêtes venant d'autres sites
        origin = self.headers.get("Origin")
        if origin and not origin.startswith((f"http://{HOST}:{PORT}", f"http://localhost:{PORT}")):
            return self._send(403, {"erreur": "origine refusée"})
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        conn = core.connect()
        try:
            r = u.path[5:]
            if r == "import":
                data = core.import_file(conn, unquote(q.get("filename", "")), self._body(), q.get("account"))
            else:
                b = json.loads(self._body() or b"{}")
                if r == "category":
                    data = core.set_category(conn, int(b["id"]), b["category"],
                                             bool(b.get("apply_to_merchant")), bool(b.get("create_rule")))
                elif r == "note":
                    core.set_note(conn, int(b["id"]), b.get("note", ""))
                    data = {"ok": True}
                elif r == "subscription":
                    core.set_subscription_status(conn, b["merchant"], b.get("status"))
                    data = {"ok": True}
                elif r == "subscription/add":
                    data = core.add_manual_subscription(conn, b.get("name"), b.get("amount"), b.get("frequency", "mensuel"),
                                                        b.get("next_date"), b.get("category"), b.get("note"),
                                                        payment_day=b.get("payment_day"), keyword=b.get("keyword"),
                                                        tolerance=b.get("tolerance"), kind=b.get("kind") or "abonnement",
                                                        sign=1 if b.get("kind") == "revenu" else -1)
                elif r == "debt/save":
                    data = core.save_debt(conn, b.get("id"), b.get("person"), b.get("total"), b.get("repaid"),
                                          b.get("keyword"), b.get("note"))
                elif r == "debt/delete":
                    data = core.delete_debt(conn, b["id"])
                elif r == "planned/save":
                    data = core.save_planned(conn, b.get("id"), b.get("name"), b.get("amount"), b.get("date"),
                                             b.get("keyword"), b.get("note"), -1 if b.get("sens", "depense") == "depense" else 1)
                elif r == "planned/delete":
                    data = core.delete_planned(conn, b["id"])
                elif r == "settings":
                    data = core.set_setting(conn, b["key"], b["value"])
                elif r == "settings/reset":
                    data = core.reset_settings(conn, b.get("keys") or [])
                elif r == "export":
                    data = core.export_csv(conn, b["path"])
                elif r == "backup":
                    data = core.backup_db(conn, b["path"])
                elif r == "subscription/state":
                    data = core.set_subscription_state(conn, b["id"], b["status"], b.get("date"))
                elif r == "loan/save":
                    data = core.save_loan(conn, b.get("id"), b.get("name"), b.get("total_due"), b.get("repaid"),
                                          b.get("monthly_payment"), b.get("merchant"), b.get("note"),
                                          payment_day=b.get("payment_day"))
                elif r == "loan/hide-candidate":
                    data = core.hide_loan_candidate(conn, b["merchant"], b.get("hidden", True))
                elif r == "loan/delete":
                    data = core.delete_loan(conn, b["id"])
                elif r == "salary/confirm":
                    data = core.confirm_salary(conn, b["id"], bool(b.get("received", True)))
                elif r == "subscription/edit":
                    data = core.edit_subscription(conn, b.get("id"), None, b.get("amount"), b.get("next_date"),
                                                  b.get("frequency"), b.get("name"), b.get("category"),
                                                  keyword=b.get("keyword"), kind=b.get("kind"), note=b.get("note"))
                elif r == "subscription/delete":
                    data = core.delete_manual_subscription(conn, b["id"])
                elif r == "balance":
                    data = core.set_manual_balance(conn, b["account"], float(b["amount"]))
                elif r == "budget":
                    core.set_budget(conn, b["category"], b.get("limit"))
                    data = {"ok": True}
                elif r == "budget-category/save":
                    data = core.save_budget_category(conn, b.get("name"), b.get("limit"), b.get("old_name"))
                elif r == "budget-category/assign":
                    data = core.assign_to_category(conn, int(b["id"]), b["category"], bool(b.get("always")))
                elif r == "budget-category/keyword":
                    data = core.add_category_keyword(conn, b["category"], b["keyword"])
                elif r == "budget-category/keyword-delete":
                    data = core.delete_category_keyword(conn, b["category"], b["keyword"])
                elif r == "budget-category/delete":
                    data = core.delete_budget_category(conn, b["name"])
                elif r == "rule":
                    data = core.add_rule(conn, b["keyword"], b["category"])
                else:
                    return self._send(404, {"erreur": "route inconnue"})
            self._send(200, data)
        except Exception as e:  # noqa: BLE001
            self._send(400, {"erreur": str(e)})
        finally:
            conn.close()


def _watch_parent():
    """Mode appli : s'arrête tout seul si l'appli Mac qui l'a lancé disparaît."""
    import threading
    import time
    parent = os.getppid()

    def loop():
        while True:
            time.sleep(2)
            if os.getppid() != parent:
                os._exit(0)
    threading.Thread(target=loop, daemon=True).start()


def main():
    global PORT
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    PORT = srv.server_address[1]  # utile quand BUDGET_PORT=0 (port libre choisi par le système)
    url = f"http://{HOST}:{PORT}"
    if "--app" in sys.argv:
        _watch_parent()
    print(f"PORT={PORT}", flush=True)
    print(f"Budget perso en route sur {url}  (Ctrl+C pour arrêter)")
    print(f"Base de données : {core.DB_PATH}")
    if "--no-browser" not in sys.argv:
        webbrowser.open(f"{url}/?t={TOKEN}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
