"""Cœur du logiciel de budget : base SQLite, import CSV/OFX, catégories, abonnements.

Uniquement la bibliothèque standard de Python (3.9+) : aucune dépendance à installer.
"""
import csv
import functools
import hashlib
import io
import os
import re
import sqlite3
import statistics
import unicodedata
from datetime import date, datetime, timedelta

APP_DIR = os.path.dirname(os.path.abspath(__file__))
def _data_dir():
    """Dossier des données, accessible seulement à ton compte :
    Windows %LOCALAPPDATA%\\BudgetPerso\\donnees, macOS ~/Library/Application Support/BudgetPerso/donnees,
    Linux ~/.local/share/budget-perso/donnees."""
    import sys
    if os.name == "nt":
        return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "BudgetPerso", "donnees")
    if sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "BudgetPerso", "donnees")
    base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "budget-perso", "donnees")


DB_PATH = os.environ.get("BUDGET_DB", os.path.join(_data_dir(), "budget.db"))

# --------------------------------------------------------------------------- #
# Catégories par défaut (mots-clés recherchés dans le libellé, en majuscules)
# --------------------------------------------------------------------------- #
DEFAULT_RULES = {
    "Courses": ["CARREFOUR", "LECLERC", "AUCHAN", "LIDL", "INTERMARCHE", "MONOPRIX",
                "FRANPRIX", "CASINO", "ALDI", "SUPER U", "HYPER U", "PICARD", "BIOCOOP",
                "NATURALIA", "GRAND FRAIS", "NETTO", "PRIMEUR", "BOULANGERIE"],
    "Restaurants & sorties": ["RESTAURANT", "UBER EATS", "UBER *EATS", "DELIVEROO", "JUST EAT",
                              "MCDONALD", "BURGER KING", "KFC", "STARBUCKS", "BRASSERIE",
                              "CAFE", "BAR ", "SUSHI", "PIZZA"],
    "Transport": ["SNCF", "RATP", "NAVIGO", "UBER", "BOLT", "BLABLACAR", "TOTAL", "ESSO",
                  "SHELL", "BP ", "AVIA", "PEAGE", "VINCI", "SANEF", "APRR", "PARKING",
                  "LIME", "TIER", "OUIGO", "TRAINLINE", "AIR FRANCE", "EASYJET", "RYANAIR"],
    "Logement": ["LOYER", "EDF", "ENGIE", "TOTALENERGIES", "VEOLIA", "SUEZ", "EAU DE",
                 "SYNDIC", "FONCIA", "NEXITY", "ASSURANCE HABITATION", "TAXE FONCIERE"],
    "Télécom & internet": ["FREE MOBILE", "FREE TELECOM", "ORANGE", "SFR", "BOUYGUES",
                           "SOSH", "RED BY SFR", "B&YOU"],
    "Abonnements & streaming": ["NETFLIX", "SPOTIFY", "DEEZER", "DISNEY", "CANAL+", "CANAL +",
                                "AMAZON PRIME", "PRIME VIDEO", "APPLE.COM", "APPLE COM",
                                "ICLOUD", "YOUTUBE", "GOOGLE", "MICROSOFT", "ADOBE",
                                "DROPBOX", "ANTHROPIC", "CLAUDE.AI", "OPENAI", "CHATGPT",
                                "MAX ", "PARAMOUNT", "CRUNCHYROLL", "AUDIBLE", "KINDLE",
                                "PLAYSTATION", "XBOX", "NINTENDO", "STEAM", "NOTION"],
    "Santé": ["PHARMACIE", "DOCTOLIB", "MEDECIN", "DENTISTE", "OPTIC", "MUTUELLE",
              "LABORATOIRE", "HOPITAL", "KINE", "CPAM"],
    "Sport & loisirs": ["BASIC FIT", "BASIC-FIT", "FITNESS PARK", "DECATHLON", "ON AIR",
                        "CINEMA", "UGC", "PATHE", "GAUMONT", "FNAC", "CULTURA", "TICKETMASTER"],
    "Shopping": ["AMAZON", "AMZN", "ZALANDO", "VINTED", "LEBONCOIN", "IKEA", "H&M", "ZARA",
                 "UNIQLO", "SEPHORA", "LEROY MERLIN", "CASTORAMA", "DARTY", "BOULANGER",
                 "ALIEXPRESS", "SHEIN", "TEMU", "APPLE STORE"],
    "Assurances & banque": ["ASSURANCE", "AXA", "MAIF", "MACIF", "MATMUT", "ALLIANZ",
                            "GROUPAMA", "FRAIS", "COTISATION", "COMMISSION", "AGIOS"],
    "Impôts & administration": ["DGFIP", "IMPOT", "TRESOR PUBLIC", "AMENDE", "ANTAI", "URSSAF"],
    "Retraits d'espèces": ["RETRAIT DAB", "RETRAIT", "DAB "],
    "Revenus": ["SALAIRE", "VIR SALAIRE", "PAIE", "CAF ", "POLE EMPLOI", "FRANCE TRAVAIL",
                "REMBOURSEMENT", "VIREMENT RECU"],
    "Épargne & virements internes": ["VIR LIVRET", "LIVRET A", "LDDS", "PEA", "ASSURANCE VIE",
                                     "VIREMENT INTERNE", "VIR INTERNE", "EPARGNE"],
}
UNCATEGORIZED = "À classer"
MERCHANT_VERSION = 2  # à incrémenter quand normalize_merchant change
TRANSFER_CATEGORIES = {"Épargne & virements internes"}
INCOME_CATEGORIES = {"Revenus", "Salaire"}

LOANS_DDL = """CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    total_due REAL,                   -- montant total à rembourser (vide = à préciser)
    repaid_initial REAL NOT NULL DEFAULT 0,  -- déjà remboursé à la date de référence
    reference_date TEXT NOT NULL,     -- date à laquelle « déjà remboursé » était exact
    monthly_payment REAL,             -- mensualité
    payment_day INTEGER,              -- jour du mois du prélèvement
    merchant TEXT,                    -- libellé du prélèvement associé (suivi automatique)
    note TEXT
);
"""

SCHEMA = LOANS_DDL + """
CREATE TABLE IF NOT EXISTS coming (
    id INTEGER PRIMARY KEY,
    account TEXT NOT NULL,            -- compte concerné
    date TEXT NOT NULL,               -- date annoncée par la banque
    label TEXT NOT NULL,
    merchant TEXT NOT NULL,
    amount REAL NOT NULL,             -- négatif = débit
    fetched_at TEXT NOT NULL          -- date de la synchro qui l'a récupérée
);
CREATE TABLE IF NOT EXISTS debts (
    id INTEGER PRIMARY KEY,
    person TEXT NOT NULL,             -- qui me doit de l'argent
    total REAL NOT NULL,              -- montant total dû
    repaid_initial REAL NOT NULL DEFAULT 0,  -- déjà rendu à la date de référence
    reference_date TEXT NOT NULL,
    keyword TEXT,                     -- texte des virements reçus de cette personne (suivi automatique)
    note TEXT
);
CREATE TABLE IF NOT EXISTS planned (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    amount REAL NOT NULL,             -- montant positif
    sign INTEGER NOT NULL DEFAULT -1, -- -1 dépense, +1 rentrée
    date TEXT NOT NULL,               -- date prévue
    keyword TEXT,                     -- texte du libellé bancaire pour reconnaître le paiement
    created_at TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS loan_candidates_hidden (
    merchant TEXT PRIMARY KEY
);
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    source TEXT DEFAULT 'import',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    date TEXT NOT NULL,
    label TEXT NOT NULL,
    merchant TEXT NOT NULL,
    amount REAL NOT NULL,
    category TEXT,
    category_manual INTEGER DEFAULT 0,
    note TEXT,
    hash TEXT UNIQUE NOT NULL,
    imported_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_merchant ON transactions(merchant);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY,
    keyword TEXT NOT NULL,
    category TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    UNIQUE(keyword, category)
);
CREATE TABLE IF NOT EXISTS budgets (
    category TEXT PRIMARY KEY,
    monthly_limit REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS budget_categories (
    name TEXT PRIMARY KEY,
    monthly_limit REAL,
    position INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS manual_subscriptions (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    amount REAL NOT NULL,
    frequency TEXT NOT NULL DEFAULT 'mensuel',
    next_date TEXT NOT NULL,
    category TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS salary_confirmations (
    tx_id INTEGER PRIMARY KEY,
    confirmed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscription_edits (
    merchant TEXT PRIMARY KEY,
    amount REAL,
    next_date TEXT,
    frequency TEXT,
    edited_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subscription_overrides (
    merchant TEXT PRIMARY KEY,
    status TEXT NOT NULL  -- 'ignored' ou 'confirmed'
);
"""


def _secure_paths(path):
    """Données lisibles uniquement par ton compte macOS (dossier 700, fichiers 600)."""
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    try:
        os.chmod(d, 0o700)
        for name in os.listdir(d):
            full = os.path.join(d, name)
            if os.path.isfile(full):
                os.chmod(full, 0o600)
    except OSError:
        pass


def connect(path=None):
    path = path or DB_PATH
    os.umask(0o077)
    _secure_paths(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA secure_delete = ON")  # les données effacées sont écrasées sur le disque
    had_salary_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='salary_confirmations'").fetchone()
    conn.executescript(SCHEMA)
    if not had_salary_table:
        conn.execute("INSERT OR IGNORE INTO salary_confirmations(tx_id, confirmed_at) "
                     "SELECT id, ? FROM transactions WHERE category = 'Salaire' AND amount > 0",
                     (datetime.now().isoformat(timespec="seconds"),))
        conn.commit()
    global CYCLE_DAY
    try:
        CYCLE_DAY = max(1, min(28, int(get_setting(conn, "jour_debut_mois"))))
    except (TypeError, ValueError):
        CYCLE_DAY = 1
    sub_cols = {r[1] for r in conn.execute("PRAGMA table_info(manual_subscriptions)")}
    for col, typ in (("payment_day", "INTEGER"), ("keyword", "TEXT"), ("tolerance", "REAL"),
                     ("kind", "TEXT DEFAULT 'abonnement'"), ("status", "TEXT DEFAULT 'actif'"),
                     ("cancelled_on", "TEXT"), ("sign", "INTEGER DEFAULT -1")):
        if col not in sub_cols:
            conn.execute(f"ALTER TABLE manual_subscriptions ADD COLUMN {col} {typ}")
    loan_cols = {r[1] for r in conn.execute("PRAGMA table_info(loans)")}
    if "payment_day" not in loan_cols:  # ancienne version de la table : on la reconstruit
        conn.execute("ALTER TABLE loans RENAME TO loans_old")
        conn.executescript(LOANS_DDL)
        conn.execute("INSERT INTO loans(id, name, total_due, repaid_initial, reference_date, monthly_payment, merchant, note) "
                     "SELECT id, name, total_due, repaid_initial, reference_date, monthly_payment, merchant, note FROM loans_old")
        conn.execute("DROP TABLE loans_old")
        conn.commit()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(accounts)")}
    if "balance" not in cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN balance REAL")
        conn.execute("ALTER TABLE accounts ADD COLUMN balance_at TEXT")
    if "kind" not in cols:
        conn.execute("ALTER TABLE accounts ADD COLUMN kind TEXT")
    for r in conn.execute("SELECT id, name FROM accounts WHERE kind IS NULL").fetchall():
        conn.execute("UPDATE accounts SET kind = ? WHERE id = ?", (guess_kind(r["name"]), r["id"]))
    if conn.execute("PRAGMA user_version").fetchone()[0] < MERCHANT_VERSION:
        for r in conn.execute("SELECT id, label FROM transactions").fetchall():
            conn.execute("UPDATE transactions SET merchant = ? WHERE id = ?", (normalize_merchant(r["label"]), r["id"]))
        conn.execute(f"PRAGMA user_version = {MERCHANT_VERSION}")
        conn.commit()
        recategorize_all(conn)
    if conn.execute("SELECT COUNT(*) FROM rules").fetchone()[0] == 0:
        for cat, words in DEFAULT_RULES.items():
            for w in words:
                conn.execute("INSERT OR IGNORE INTO rules(keyword, category) VALUES (?, ?)", (w, cat))
        conn.commit()
    return conn


# --------------------------------------------------------------------------- #
# Normalisation des libellés
# --------------------------------------------------------------------------- #
def strip_accents(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


_PREFIXES = [
    r"^PAIEMENT PAR CARTE( X\d{3,4})?", r"^AVOIR CARTE( X\d{3,4})?", r"^PAIEMENT CB", r"^PAIEMENT",
    r"^CARTE X?\d*", r"^CB\*?", r"^ACHAT CB", r"^FACTURE CARTE",
    r"^VIREMENT EMIS( (WERO|VIR INST|WEB|SEPA))?( VERS)?", r"^VIREMENT EN VOTRE FAVEUR( (WERO|VIR INST|SEPA))?( DE)?",
    r"^VIR SEPA RECU", r"^VIR SEPA EMIS", r"^VIR SEPA", r"^VIREMENT SEPA", r"^VIREMENT", r"^VIR INST", r"^VIR",
    r"^PRLV SEPA", r"^PRELEVEMENT SEPA", r"^PRELEVEMENT", r"^PRLV", r"^DU \d{2}\d{2}\d{2,4}",
    r"^(MONSIEUR|MADAME|MADEMOISELLE|MLLE|MLE|MME|MR|M\.)\b",
]


def normalize_merchant(label):
    """Nom de marchand stable à partir d'un libellé bancaire (sert aux regroupements et aux abonnements)."""
    s = strip_accents(label).upper()
    s = re.sub(r"\s+", " ", s).strip()
    # Ce qui suit une parenthèse, un « - » ou la répétition du type d'opération n'est que de la référence
    s = re.split(r"\(| - | PRELEVEMENT | VOTRE RUM| ICS ?:", s)[0]
    for _ in range(3):
        for p in _PREFIXES:
            s = re.sub(p, "", s).strip(" :-*/")
    s = re.sub(r"\b\d{1,2}[/.]\d{1,2}([/.]\d{2,4})?\b", " ", s)  # dates
    s = re.sub(r"\bX{1,}\d{3,}\b", " ", s)                        # n° de carte masqué
    s = re.sub(r"\b[A-Z]*\d[A-Z0-9/]{5,}\b", " ", s)              # références
    s = re.sub(r"\b\d+\b", " ", s)                                # nombres isolés
    s = re.sub(r"[^A-Z&+'. ]", " ", s)
    words = []
    for w in s.split():
        w = w.strip(".'")
        if w and w not in words:  # « UNEO UNEO » -> « UNEO »
            words.append(w)
    return " ".join(words[:3]) if words else strip_accents(label).upper()[:30]


def categorize(conn, label, amount):
    up = " " + re.sub(r"\s+", " ", strip_accents(label).upper()) + " "
    merchant = " " + normalize_merchant(label) + " "  # un mot-clé « marchand » doit toujours retrouver ses opérations
    rules = conn.execute(
        "SELECT keyword, category FROM rules ORDER BY priority DESC, LENGTH(keyword) DESC").fetchall()
    for r in rules:
        kw = r["keyword"].upper()
        if kw in up or kw in merchant:
            cat = r["category"]
            if cat in INCOME_CATEGORIES and amount < 0:
                continue
            return cat
    if amount > 0:
        return "Revenus"
    return UNCATEGORIZED


# --------------------------------------------------------------------------- #
# Parsing des fichiers
# --------------------------------------------------------------------------- #
def decode_bytes(raw):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_amount(s):
    if s is None:
        return None
    s = str(s).strip().replace(" ", "").replace(" ", "").replace(" ", "")
    s = s.replace("€", "").replace("EUR", "").replace("+", "")
    if not s:
        return None
    neg = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = s.strip("-()")
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return -v if neg else v


def parse_date(s):
    s = str(s).strip()
    head = s.split(" ")[0].split("T")[0]
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%Y/%m/%d", "%d-%m-%y"):
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    m = re.match(r"(\d{4})(\d{2})(\d{2})", s)  # format OFX 20240131120000[...]
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _norm_header(h):
    h = (h or "").strip().lower()
    for a, b in (("é", "e"), ("è", "e"), ("ê", "e"), ("à", "a"), ("ô", "o"), ("û", "u")):
        h = h.replace(a, b)
    return h


def _find_col(headers, candidates, exclude=()):
    for i, h in enumerate(headers):
        if any(c in h for c in candidates) and not any(e in h for e in exclude):
            return i
    return None


def parse_csv(text):
    lines = text.splitlines()
    # Certaines banques ajoutent des lignes d'en-tête (n° de compte, solde...) : on cherche
    # la première ligne qui ressemble à une ligne d'en-têtes.
    start = 0
    for i, line in enumerate(lines[:30]):
        nl = _norm_header(line)
        if "date" in nl and any(k in nl for k in ("montant", "amount", "debit", "credit", "libelle", "label", "description")):
            start = i
            break
    body = "\n".join(lines[start:])
    sample = body[:4000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if sample.count(";") > sample.count(",") else ","
    rows = list(csv.reader(io.StringIO(body), delimiter=delim))
    if not rows:
        return []
    headers = [_norm_header(h) for h in rows[0]]
    c_date = _find_col(headers, ["date operation", "date op", "date de l'operation", "date"],
                       exclude=["valeur"]) or _find_col(headers, ["date"])
    c_label = _find_col(headers, ["libelle", "label", "description", "intitule", "nature", "detail", "beneficiaire", "payee", "memo"])
    c_amount = _find_col(headers, ["montant", "amount", "somme", "valeur (eur)"], exclude=["date"])
    c_debit = _find_col(headers, ["debit"])
    c_credit = _find_col(headers, ["credit"])
    if c_date is None or c_label is None or (c_amount is None and c_debit is None and c_credit is None):
        raise ValueError(
            "Colonnes non reconnues. En-têtes trouvés : " + ", ".join(rows[0]) +
            ". Il faut au moins une date, un libellé et un montant (ou débit/crédit).")
    out = []
    for r in rows[1:]:
        if len(r) <= max(c for c in (c_date, c_label) if c is not None):
            continue
        d = parse_date(r[c_date])
        if not d:
            continue
        label = r[c_label].strip()
        # Ajoute les colonnes de libellé complémentaires (ex. « Libellé » + « Détail »)
        extra = _find_col(headers, ["detail", "complement", "libelle operation"])
        if extra is not None and extra != c_label and extra < len(r) and r[extra].strip():
            label = (label + " " + r[extra].strip()).strip()
        amt = None
        if c_amount is not None and c_amount < len(r):
            amt = parse_amount(r[c_amount])
        if amt is None:
            deb = parse_amount(r[c_debit]) if c_debit is not None and c_debit < len(r) else None
            cre = parse_amount(r[c_credit]) if c_credit is not None and c_credit < len(r) else None
            if deb:
                amt = -abs(deb)
            elif cre:
                amt = abs(cre)
        if amt is None or not label:
            continue
        out.append({"date": d, "label": label, "amount": round(amt, 2)})
    return out


def parse_ofx(text):
    out = []
    for block in re.findall(r"<STMTTRN>(.*?)(?:</STMTTRN>|(?=<STMTTRN>)|(?=</BANKTRANLIST>))", text, re.S | re.I):
        def tag(name):
            m = re.search(r"<" + name + r">([^<\r\n]*)", block, re.I)
            return m.group(1).strip() if m else ""
        d = parse_date(tag("DTPOSTED"))
        amt = parse_amount(tag("TRNAMT").replace(",", "."))
        label = " ".join(x for x in (tag("NAME"), tag("MEMO")) if x).strip()
        if d and amt is not None and label:
            out.append({"date": d, "label": label, "amount": round(amt, 2)})
    return out


def parse_file(filename, raw):
    text = decode_bytes(raw)
    name = (filename or "").lower()
    if name.endswith((".ofx", ".qfx")) or "<OFX>" in text.upper()[:2000]:
        return parse_ofx(text)
    return parse_csv(text)


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #
def get_or_create_account(conn, name, source="import"):
    name = (name or "Compte principal").strip() or "Compte principal"
    row = conn.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO accounts(name, source) VALUES (?, ?)", (name, source))
    return cur.lastrowid


def insert_transactions(conn, account_name, txs, source="import"):
    acc = get_or_create_account(conn, account_name, source)
    seen = {}
    added = skipped = 0
    for t in txs:
        base = "|".join([str(acc), t["date"].isoformat(), f"{t['amount']:.2f}", t["label"].upper().strip()])
        n = seen.get(base, 0)
        seen[base] = n + 1
        h = hashlib.sha1(f"{base}|{n}".encode()).hexdigest()
        merchant = normalize_merchant(t["label"])
        cat = categorize(conn, t["label"], t["amount"])
        try:
            conn.execute(
                "INSERT INTO transactions(account_id, date, label, merchant, amount, category, hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (acc, t["date"].isoformat(), t["label"], merchant, t["amount"], cat, h))
            added += 1
        except sqlite3.IntegrityError:
            skipped += 1
    conn.commit()
    return {"ajoutees": added, "doublons_ignores": skipped, "compte": account_name}


def import_file(conn, filename, raw, account_name=None):
    txs = parse_file(filename, raw)
    if not txs:
        raise ValueError("Aucune opération trouvée dans ce fichier.")
    res = insert_transactions(conn, account_name or "Compte principal", txs)
    res["periode"] = [min(t["date"] for t in txs).isoformat(), max(t["date"] for t in txs).isoformat()]
    return res


def recategorize_all(conn):
    rows = conn.execute("SELECT id, label, amount FROM transactions WHERE category_manual = 0").fetchall()
    for r in rows:
        conn.execute("UPDATE transactions SET category = ? WHERE id = ?",
                     (categorize(conn, r["label"], r["amount"]), r["id"]))
    conn.commit()
    return len(rows)


# --------------------------------------------------------------------------- #
# Requêtes / analyses
# --------------------------------------------------------------------------- #
CYCLE_DAY = 1  # jour de début du mois budgétaire (réglage « jour_debut_mois », lu à chaque connexion)


def cycle_of(d):
    """Mois budgétaire d'une date, noté AAAA-MM du mois où il se termine.
    Avec un début le 25 : du 25/10 au 24/11 = « 2026-11 »."""
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    if CYCLE_DAY > 1 and d.day >= CYCLE_DAY:
        return f"{d.year + (d.month == 12):04d}-{d.month % 12 + 1:02d}"
    return f"{d.year:04d}-{d.month:02d}"


SALARY_EARLY_DAYS = 5  # un salaire versé jusqu à 5 jours avant le début du mois appartient à ce mois


def cycle_of_tx(d, category, amount):
    """Mois budgétaire d'une opération : comme cycle_of, sauf un salaire versé en avance (week-end)."""
    if isinstance(d, str):
        d = date.fromisoformat(d[:10])
    if CYCLE_DAY > 1 and category == "Salaire" and amount > 0:
        d = d + timedelta(days=SALARY_EARLY_DAYS)
    return cycle_of(d)


def _cycle_clause(start, end):
    """Filtre SQL d'une période, en déplaçant les salaires versés en avance vers le mois suivant."""
    if CYCLE_DAY <= 1 or not start or not end:
        q, p = "", []
        if start:
            q += " AND date >= ?"; p.append(start)
        if end:
            q += " AND date < ?"; p.append(end)
        return q, p
    s_early = (date.fromisoformat(start) - timedelta(days=SALARY_EARLY_DAYS)).isoformat()
    e_early = (date.fromisoformat(end) - timedelta(days=SALARY_EARLY_DAYS)).isoformat()
    q = (" AND ((date >= ? AND date < ? AND NOT (category = 'Salaire' AND amount > 0 AND date >= ?))"
         " OR (category = 'Salaire' AND amount > 0 AND date >= ? AND date < ?))")
    return q, [start, end, e_early, s_early, start]


def _month_bounds(month):
    """Début (inclus) et fin (exclue) d'un mois budgétaire."""
    y, m = map(int, month.split("-"))
    if CYCLE_DAY <= 1:
        start = date(y, m, 1)
        end = date(y + (m == 12), (m % 12) + 1, 1)
    else:
        py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
        start = date(py, pm, CYCLE_DAY)
        end = date(y, m, CYCLE_DAY)
    return start.isoformat(), end.isoformat()


def list_months(conn):
    return sorted({cycle_of(r[0]) for r in conn.execute("SELECT DISTINCT date FROM transactions")}, reverse=True)


def list_transactions(conn, start=None, end=None, category=None, search=None,
                      min_amount=None, max_amount=None, account=None, limit=500):
    q = ("SELECT t.id, t.date, t.label, t.merchant, t.amount, t.category, t.note, a.name AS account "
         "FROM transactions t JOIN accounts a ON a.id = t.account_id WHERE 1=1")
    p = []
    clause, cp = _cycle_clause(start, end)
    q += clause; p += cp
    if category:
        q += " AND t.category = ?"; p.append(category)
    if account:
        q += " AND a.name = ?"; p.append(account)
    if search:
        q += " AND (t.label LIKE ? OR t.merchant LIKE ? OR t.note LIKE ?)"
        p += [f"%{search}%"] * 3
    if min_amount is not None:
        q += " AND t.amount >= ?"; p.append(min_amount)
    if max_amount is not None:
        q += " AND t.amount <= ?"; p.append(max_amount)
    q += " ORDER BY t.date DESC, t.id DESC LIMIT ?"
    p.append(int(limit))
    return [dict(r) for r in conn.execute(q, p)]


def summary(conn, month=None, start=None, end=None):
    if month:
        start, end = _month_bounds(month)
    clause, p = _cycle_clause(start, end)
    q = "SELECT category, SUM(amount) s, COUNT(*) n FROM transactions WHERE 1=1" + clause + " GROUP BY category"
    income = expenses = transfers = 0.0
    cats = []
    budgets = _budget_limits(conn)
    for r in conn.execute(q, p):
        cat, s = r["category"], r["s"] or 0
        if cat in TRANSFER_CATEGORIES:
            transfers += s
            continue
        if s >= 0:
            income += s
        else:
            expenses += -s
            cats.append({"categorie": cat, "depense": round(-s, 2), "operations": r["n"],
                         "budget": budgets.get(cat)})
    cats.sort(key=lambda c: -c["depense"])
    for c in cats:
        c["part"] = round(100 * c["depense"] / expenses, 1) if expenses else 0
    depuis_salaire = None
    if month and month == cycle_of(date.today()):
        # Mois en cours : les dépenses du tableau de bord partent du dernier salaire arrivé sur le compte.
        r = conn.execute("SELECT MAX(date) FROM transactions WHERE category = 'Salaire' AND amount > 0 "
                         "AND date <= ?", (date.today().isoformat(),)).fetchone()
        if r and r[0]:
            ph = ",".join("?" * len(TRANSFER_CATEGORIES))
            tot = conn.execute(f"SELECT SUM(amount) FROM transactions WHERE amount < 0 AND date >= ? "
                               f"AND category NOT IN ({ph})", (r[0][:10], *TRANSFER_CATEGORIES)).fetchone()[0] or 0
            depuis_salaire = {"date": r[0][:10], "depenses": round(-tot, 2)}
    return {
        "periode": {"debut": start, "fin_exclue": end},
        "depuis_salaire": depuis_salaire,
        "revenus": round(income, 2),
        "depenses": round(expenses, 2),
        "solde": round(income - expenses, 2),
        "epargne_et_virements_internes": round(transfers, 2),
        "par_categorie": cats,
    }


def monthly_history(conn, months=12):
    agg = {}
    for r in conn.execute("SELECT date, amount, category FROM transactions"):
        if r["category"] in TRANSFER_CATEGORIES:
            continue
        a = agg.setdefault(cycle_of_tx(r["date"], r["category"], r["amount"]), [0.0, 0.0])
        if r["amount"] > 0:
            a[0] += r["amount"]
        else:
            a[1] -= r["amount"]
    keys = sorted(agg)[-months:]
    return [{"mois": k, "revenus": round(agg[k][0], 2), "depenses": round(agg[k][1], 2)} for k in keys]


FREQS = [("hebdomadaire", 7, 2, 52 / 12), ("4 semaines", 28, 1, 13 / 12), ("mensuel", 30.4, 4, 1.0),
         ("trimestriel", 91, 8, 1 / 3), ("annuel", 365, 20, 1 / 12)]
FREQ_FACTOR = {f[0]: f[3] for f in FREQS}
SAVINGS_WORDS = ("LIVRET", "LDDS", "LEP", "PEL", "CEL", "EPARGNE", "ASSURANCE VIE",
                 "ASSURANCE-VIE", "PEA", "TITRE", "COMPTE A TERME", "COMPTE ESPECE")


def add_period(d, freq, n=1):
    """Date d décalée de n périodes (même jour du mois pour mensuel/trimestriel/annuel)."""
    if freq == "hebdomadaire":
        return d + timedelta(days=7 * n)
    if freq == "4 semaines":
        return d + timedelta(days=28 * n)
    months = {"mensuel": 1, "trimestriel": 3, "annuel": 12}.get(freq, 1) * n
    y, m = divmod(d.month - 1 + months, 12)
    y += d.year
    m += 1
    last_day = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last_day))


def _account_kinds(conn):
    return {r["id"]: r["kind"] or guess_kind(r["name"]) for r in conn.execute("SELECT id, name, kind FROM accounts")}


def _detect_recurring(conn, sign=-1, include_ignored=False, include_transfers=False, account_kinds=None):
    """Paiements (sign=-1) ou rentrées (sign=+1) qui reviennent à intervalle régulier."""
    overrides = {r["merchant"]: r["status"] for r in conn.execute("SELECT * FROM subscription_overrides")}
    edits = {r["merchant"]: r for r in conn.execute("SELECT * FROM subscription_edits")} if sign < 0 else {}
    kinds = _account_kinds(conn)
    rows = conn.execute(
        "SELECT account_id, merchant, date, amount, category, label FROM transactions WHERE amount "
        + ("< 0" if sign < 0 else "> 0") + " ORDER BY merchant, date").fetchall()
    groups = {}
    for r in rows:
        if account_kinds and kinds.get(r["account_id"], "courant") not in account_kinds:
            continue
        groups.setdefault(r["merchant"], []).append(r)
    today = date.today()
    out = []
    for merchant, txs in groups.items():
        status = overrides.get(merchant) if sign < 0 else None
        if status == "ignored" and not include_ignored:
            continue
        if len(txs) < 2:
            continue
        amounts = [abs(t["amount"]) for t in txs]
        med = statistics.median(amounts)
        if sign < 0:
            similar = [t for t in txs if abs(abs(t["amount"]) - med) <= max(2.0, 0.15 * med)]
        else:
            # Un salaire peut varier fortement (primes, 13e mois) : on garde toutes les rentrées notables du même payeur.
            similar = [t for t in txs if abs(t["amount"]) >= 0.5 * med]
        if len(similar) < 2:
            continue
        if status != "confirmed":
            if similar[-1]["category"] in TRANSFER_CATEGORIES and not include_transfers:
                continue
            if len(similar) / len(txs) < 0.6:
                continue
        dates = [date.fromisoformat(t["date"]) for t in similar]
        gaps = [(b - a).days for a, b in zip(dates, dates[1:]) if (b - a).days > 0]
        if not gaps:
            continue
        g = statistics.median(gaps)
        freq = None
        for name, period, tol, monthly_factor in FREQS:
            if abs(g - period) <= tol:
                regular = sum(1 for x in gaps if abs(x - period) <= tol * 1.5) / len(gaps)
                if regular >= 0.6:
                    freq = (name, period, monthly_factor)
                break
        if not freq and status != "confirmed":
            continue
        if not freq:
            freq = ("mensuel", 30.4, 1.0)
        if freq[0] in ("mensuel", "hebdomadaire") and len(similar) < 3 and status != "confirmed":
            continue
        ed = edits.get(merchant)
        if ed and ed["frequency"] in FREQ_FACTOR:
            freq = next(f[:1] + f[1:2] + f[3:] for f in FREQS if f[0] == ed["frequency"])
        last = dates[-1]
        nxt = add_period(last, freq[0])
        active = (today - last).days <= freq[1] * 1.6
        last_amount = abs(similar[-1]["amount"])
        if sign > 0:  # montant attendu : médiane des 3 dernières rentrées
            last_amount = statistics.median([abs(t["amount"]) for t in similar[-3:]])
        edited = False
        # Prix / date modifiés à la main : valables jusqu'au prochain prélèvement réellement constaté.
        if ed and last.isoformat() <= ed["edited_at"][:10]:
            if ed["amount"] is not None:
                last_amount, edited = ed["amount"], True
            if ed["next_date"]:
                nxt, edited, active = date.fromisoformat(ed["next_date"]), True, True
        out.append({
            "id": None,
            "marchand": merchant,
            "libelle_exemple": similar[-1]["label"],
            "categorie": similar[-1]["category"],
            "frequence": freq[0],
            "montant": round(last_amount, 2),
            "cout_mensuel": round(last_amount * freq[2], 2),
            "cout_annuel": round(last_amount * freq[2] * 12, 2),
            "occurrences": len(similar),
            "premier_paiement": dates[0].isoformat(),
            "dernier_paiement": last.isoformat(),
            "prochain_prevu": nxt.isoformat(),
            "actif": active,
            "hausse_de_prix": round(last_amount - abs(similar[0]["amount"]), 2),
            "statut": status or "detecte",
            "modifie": edited,
        })
    out.sort(key=lambda s: (not s["actif"], -s["cout_mensuel"]))
    return out


PERIOD_DAYS = {"hebdomadaire": 7, "4 semaines": 28, "mensuel": 30, "trimestriel": 91, "annuel": 365}
STOP_AFTER_DAYS = 61  # règle de l'utilisateur : plus de 2 mois sans paiement = abonnement arrêté
KIND_LABELS = {"abonnement": "Abonnement", "charge": "Charge fixe", "revenu": "Rentrée"}


def _sub_terms(sub):
    return [t.strip() for t in _kw(sub["keyword"]).split("+") if t.strip()]


def _sub_matches(sub, label, merchant, amount):
    """Une opération correspond à une ligne de la liste si son libellé contient tous les mots-clés
    (séparés par « + ») et, si une tolérance est fixée, si son montant est proche du montant prévu."""
    terms = _sub_terms(sub)
    if not terms:
        return False
    if (amount < 0) != ((sub["sign"] or -1) < 0):
        return False
    txt = _kw(label) + " | " + _kw(merchant)
    if not all(t in txt for t in terms):
        return False
    tol = sub["tolerance"]
    return not tol or abs(abs(amount) - sub["amount"]) <= max(1.0, tol * sub["amount"])


def _sub_next(sub, last_d, today):
    """Prochaine échéance (peut être légèrement passée si le prélèvement est en attente)."""
    freq = sub["frequency"] or "mensuel"
    explicit = date.fromisoformat(sub["next_date"]) if sub["next_date"] else None
    if explicit and explicit >= today - timedelta(days=3) and (not last_d or explicit > last_d + timedelta(days=5)):
        return explicit
    if freq in ("hebdomadaire", "4 semaines") or not sub["payment_day"]:
        base = last_d or explicit or today
        d = add_period(base, freq) if last_d else base
        while d < today - timedelta(days=3):
            d = add_period(d, freq)
        return d
    day = sub["payment_day"]
    last_dom = (date(today.year + (today.month == 12), today.month % 12 + 1, 1) - timedelta(days=1)).day
    cand = date(today.year, today.month, min(day, last_dom))
    if freq != "mensuel" and last_d:  # trimestriel / annuel : à partir du dernier paiement
        cand = add_period(last_d, freq)
        while cand < today - timedelta(days=7):
            cand = add_period(cand, freq)
        return cand
    if (last_d and last_d >= cand - timedelta(days=12)) or cand < today - timedelta(days=7):
        cand = add_period(cand, "mensuel")
    return cand


def subscription_list(conn, today=None):
    """Liste de référence (abonnements, charges fixes, rentrées régulières), confrontée aux opérations."""
    today = today or date.today()
    rows = conn.execute("SELECT date, label, merchant, amount FROM transactions WHERE date >= ? ORDER BY date",
                        ((today - timedelta(days=400)).isoformat(),)).fetchall()
    out = []
    for sub in conn.execute("SELECT * FROM manual_subscriptions ORDER BY name"):
        pays = [r for r in rows if _sub_matches(sub, r["label"], r["merchant"], r["amount"])]
        last = pays[-1] if pays else None
        last_d = date.fromisoformat(last["date"]) if last else None
        freq = sub["frequency"] or "mensuel"
        status = sub["status"] or "actif"
        alerte = None
        if status == "resilie":
            if last_d and sub["cancelled_on"] and last_d > date.fromisoformat(sub["cancelled_on"]):
                alerte = f"Encore prélevé le {last_d.strftime('%d/%m')} après la résiliation"
        elif last_d:
            limit = STOP_AFTER_DAYS if freq in ("hebdomadaire", "4 semaines", "mensuel") else PERIOD_DAYS[freq] + STOP_AFTER_DAYS
            if (today - last_d).days > limit:
                status = "arrete"
        nxt = _sub_next(sub, last_d, today) if status == "actif" else None
        f = FREQ_FACTOR.get(freq, 1.0)
        last_amt = round(abs(last["amount"]), 2) if last else None
        out.append({
            "id": sub["id"], "marchand": sub["name"], "nom": sub["name"],
            "type": sub["kind"] or "abonnement", "sens": "rentree" if (sub["sign"] or -1) > 0 else "depense",
            "categorie": sub["category"] or "Abonnements & streaming", "frequence": freq,
            "jour": sub["payment_day"], "montant": round(sub["amount"], 2),
            "cout_mensuel": round(sub["amount"] * f, 2), "cout_annuel": round(sub["amount"] * f * 12, 2),
            "mot_cle": sub["keyword"], "tolerance": sub["tolerance"],
            "dernier_paiement": last_d.isoformat() if last_d else None, "dernier_montant": last_amt,
            "paiements_vus": len(pays), "prochain_prevu": nxt.isoformat() if nxt else None,
            "en_attente": bool(nxt and nxt < today),
            "statut": status, "resilie_le": sub["cancelled_on"], "alerte": alerte,
            "note": sub["note"], "actif": status == "actif",
            "hausse_de_prix": round(last_amt - sub["amount"], 2) if last_amt and (sub["tolerance"] or 0) == 0 else 0,
        })
    order = {"actif": 0, "arrete": 1, "resilie": 2}
    out.sort(key=lambda x: (order.get(x["statut"], 3), x["type"], -x["cout_mensuel"]))
    return out


def detect_subscriptions(conn, include_ignored=False):
    """Abonnements et charges fixes de la liste de référence (hors rentrées)."""
    return [x for x in subscription_list(conn) if x["sens"] == "depense"]


def subscription_suggestions(conn):
    """Paiements réguliers repérés dans les opérations mais absents de la liste (et des crédits)."""
    subs = conn.execute("SELECT * FROM manual_subscriptions").fetchall()
    loans = conn.execute("SELECT * FROM loans WHERE merchant IS NOT NULL").fetchall()
    res = []
    for d in _detect_recurring(conn, -1):
        if not d["actif"]:
            continue
        if any(_sub_matches(x, d["libelle_exemple"], d["marchand"], -d["montant"]) for x in subs):
            continue
        if any(_matches_loan(l, d["marchand"], d["libelle_exemple"], d["montant"]) for l in loans):
            continue
        res.append({k: d[k] for k in ("marchand", "libelle_exemple", "categorie", "frequence", "montant",
                                      "dernier_paiement", "occurrences")})
    return res


def add_manual_subscription(conn, name, amount, frequency="mensuel", next_date=None, category=None, note=None,
                            payment_day=None, keyword=None, tolerance=None, kind="abonnement", sign=-1,
                            status="actif", cancelled_on=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("Le nom est obligatoire.")
    amount = abs(float(amount))
    if frequency not in FREQ_FACTOR:
        raise ValueError("Fréquence inconnue : " + str(frequency))
    if next_date:
        date.fromisoformat(next_date)
    if payment_day in (None, "") and next_date and frequency == "mensuel":
        payment_day = date.fromisoformat(next_date).day
    cur = conn.execute(
        "INSERT INTO manual_subscriptions(name, amount, frequency, next_date, category, note, payment_day, keyword, "
        "tolerance, kind, sign, status, cancelled_on) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (name, amount, frequency, next_date or "", category or "Abonnements & streaming", note,
         int(payment_day) if payment_day not in (None, "") else None,
         (keyword or name).strip(), tolerance, kind or "abonnement", -1 if (sign or -1) < 0 else 1,
         status or "actif", cancelled_on))
    conn.commit()
    return {"id": cur.lastrowid, "nom": name}


def edit_subscription(conn, sub_id=None, merchant=None, amount=None, next_date=None, frequency=None,
                      name=None, category=None, payment_day=None, keyword=None, kind=None, note=None):
    """Change le prix, la date du prochain prélèvement, la fréquence… d'une ligne de la liste."""
    if not sub_id:
        raise ValueError("Abonnement non précisé")
    row = conn.execute("SELECT * FROM manual_subscriptions WHERE id = ?", (int(sub_id),)).fetchone()
    if not row:
        raise ValueError("Abonnement introuvable")
    if frequency and frequency not in FREQ_FACTOR:
        raise ValueError("Fréquence inconnue : " + str(frequency))
    freq = frequency or row["frequency"]
    if next_date:
        nd = date.fromisoformat(next_date)
        if freq == "mensuel" and payment_day in (None, ""):
            payment_day = nd.day  # le jour du mois suit la nouvelle date
    conn.execute(
        "UPDATE manual_subscriptions SET name=?, amount=?, frequency=?, next_date=?, category=?, payment_day=?, "
        "keyword=?, kind=?, note=? WHERE id=?",
        ((name or row["name"]).strip(), abs(float(amount)) if amount not in (None, "") else row["amount"], freq,
         next_date or row["next_date"], category or row["category"],
         int(payment_day) if payment_day not in (None, "") else row["payment_day"],
         (keyword or row["keyword"] or row["name"]).strip(), kind or row["kind"],
         note if note is not None else row["note"], int(sub_id)))
    conn.commit()
    return {"ok": True}


def set_subscription_state(conn, sub_id, status, cancelled_on=None):
    """status : 'resilie' (avec la date) ou 'actif' (réactiver)."""
    if status not in ("actif", "resilie"):
        raise ValueError("Statut inconnu")
    conn.execute("UPDATE manual_subscriptions SET status = ?, cancelled_on = ? WHERE id = ?",
                 (status, (cancelled_on or date.today().isoformat()) if status == "resilie" else None, int(sub_id)))
    conn.commit()
    return {"ok": True}


def delete_manual_subscription(conn, sub_id):
    n = conn.execute("DELETE FROM manual_subscriptions WHERE id = ?", (int(sub_id),)).rowcount
    conn.commit()
    return {"supprimes": n}


SETTINGS_DEFAULTS = {
    # Dépenses du quotidien dans le prévisionnel : « aucune » (choix de l'utilisateur), « habitudes » ou « budget »
    "estimation_depenses": "habitudes",
    "budget_quotidien_mensuel": "800",
    "jour_debut_mois": "1",
}


def get_setting(conn, key):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else SETTINGS_DEFAULTS.get(key)


def set_setting(conn, key, value):
    if key not in SETTINGS_DEFAULTS:
        raise ValueError("Réglage inconnu : " + key)
    if key == "estimation_depenses" and value not in ("aucune", "habitudes", "budget"):
        raise ValueError("Mode d'estimation inconnu")
    if key == "budget_quotidien_mensuel":
        value = str(abs(float(value)))
    if key == "jour_debut_mois":
        value = str(int(value))
        if not 1 <= int(value) <= 28:
            raise ValueError("Le mois doit commencer entre le 1er et le 28.")
        global CYCLE_DAY
        CYCLE_DAY = int(value)
    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    return {key: value}


# --------------------------------------------------------------------------- #
# Opérations à venir annoncées par la banque (« opérations à venir » de l'appli Crédit Agricole)
# --------------------------------------------------------------------------- #
def replace_coming(conn, account_name, items):
    """Remplace les opérations à venir d'un compte par celles que la banque vient d'annoncer."""
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute("DELETE FROM coming WHERE account = ?", (account_name,))
    for it in items:
        conn.execute("INSERT INTO coming(account, date, label, merchant, amount, fetched_at) VALUES (?,?,?,?,?,?)",
                     (account_name, it["date"].isoformat(), it["label"], normalize_merchant(it["label"]),
                      round(float(it["amount"]), 2), now))
    conn.commit()


def list_coming(conn):
    """Opérations à venir annoncées par la banque, sauf celles déjà passées sur le compte depuis la synchro."""
    out = []
    for c in conn.execute("SELECT * FROM coming ORDER BY date, id"):
        posted = conn.execute(
            "SELECT 1 FROM transactions WHERE abs(amount - ?) < 0.01 AND merchant = ? AND date >= ? AND imported_at > ? LIMIT 1",
            (c["amount"], c["merchant"], (date.fromisoformat(c["date"]) - timedelta(days=5)).isoformat(),
             c["fetched_at"].replace("T", " "))).fetchone()
        if posted:
            continue
        out.append({"id": c["id"], "compte": c["account"], "date": c["date"], "libelle": c["label"],
                    "marchand": c["merchant"], "montant": c["amount"], "recupere_le": c["fetched_at"]})
    return out


# --------------------------------------------------------------------------- #
# Personnes qui me doivent de l'argent
# --------------------------------------------------------------------------- #
def list_debts(conn):
    """Argent qu'on me doit. Remboursé = montant saisi + virements reçus de la personne depuis
    (hors rentrées régulières de la liste, comme une participation mensuelle)."""
    ref = conn.execute("SELECT * FROM manual_subscriptions").fetchall()
    out = []
    for d in conn.execute("SELECT * FROM debts ORDER BY person"):
        pays = []
        terms = [t.strip() for t in _kw(d["keyword"] or "").split("+") if t.strip()]
        if terms:
            for r in conn.execute("SELECT date, label, merchant, amount FROM transactions WHERE amount > 0 AND date > ? ORDER BY date",
                                  (d["reference_date"],)):
                txt = _kw(r["label"]) + " | " + _kw(r["merchant"])
                if all(t in txt for t in terms) and not any(_sub_matches(x, r["label"], r["merchant"], r["amount"]) for x in ref):
                    pays.append(r)
        auto = round(sum(r["amount"] for r in pays), 2)
        repaid = round(d["repaid_initial"] + auto, 2)
        rest = round(max(0.0, d["total"] - repaid), 2)
        out.append({"id": d["id"], "personne": d["person"], "montant_total": round(d["total"], 2),
                    "deja_rendu": repaid, "reste_du": rest,
                    "progression": round(100 * repaid / d["total"], 1) if d["total"] else 0,
                    "suivi_auto": d["keyword"], "rendu_auto": auto, "depuis": d["reference_date"],
                    "remboursements": [{"date": r["date"], "montant": r["amount"]} for r in pays],
                    "note": d["note"], "solde": rest <= 0})
    out.sort(key=lambda x: (x["solde"], -x["reste_du"]))
    return {"dettes": out, "total_du": round(sum(x["reste_du"] for x in out), 2)}


def save_debt(conn, debt_id=None, person=None, total=None, repaid=0, keyword=None, note=None, reference_date=None):
    person = (person or "").strip()
    if not person:
        raise ValueError("Indique qui te doit de l'argent.")
    total = abs(float(total))
    repaid = abs(float(repaid or 0))
    if repaid > total:
        raise ValueError("Le montant déjà rendu dépasse le total.")
    ref = reference_date or date.today().isoformat()
    vals = (person, total, repaid, ref, (keyword or "").strip() or None, note)
    if debt_id:
        conn.execute("UPDATE debts SET person=?, total=?, repaid_initial=?, reference_date=?, keyword=?, note=? WHERE id=?",
                     vals + (int(debt_id),))
    else:
        debt_id = conn.execute("INSERT INTO debts(person, total, repaid_initial, reference_date, keyword, note) "
                               "VALUES (?,?,?,?,?,?)", vals).lastrowid
    conn.commit()
    return {"id": debt_id, "personne": person}


def delete_debt(conn, debt_id):
    n = conn.execute("DELETE FROM debts WHERE id = ?", (int(debt_id),)).rowcount
    conn.commit()
    return {"supprimes": n}


# --------------------------------------------------------------------------- #
# Dépenses (ou rentrées) ponctuelles prévues
# --------------------------------------------------------------------------- #
def planned_list(conn):
    """Opérations ponctuelles prévues. Payée = une opération correspondante (libellé + montant à 1 € près)
    est apparue sur le compte depuis l'enregistrement."""
    out = []
    for p in conn.execute("SELECT * FROM planned ORDER BY date"):
        paid = None
        terms = [t.strip() for t in _kw(p["keyword"] or p["name"]).split("+") if t.strip()]
        for r in conn.execute("SELECT date, label, merchant, amount FROM transactions WHERE date >= ? ORDER BY date",
                              (p["created_at"][:10],)):
            if (r["amount"] < 0) != (p["sign"] < 0) or abs(abs(r["amount"]) - p["amount"]) > 1.0:
                continue
            txt = _kw(r["label"]) + " | " + _kw(r["merchant"])
            if all(t in txt for t in terms):
                paid = r["date"]
                break
        out.append({"id": p["id"], "nom": p["name"], "montant": round(p["amount"], 2),
                    "sens": "rentree" if p["sign"] > 0 else "depense", "date": p["date"],
                    "mot_cle": p["keyword"], "note": p["note"], "paye_le": paid,
                    "statut": "paye" if paid else "prevu"})
    return out


def save_planned(conn, planned_id=None, name=None, amount=None, when=None, keyword=None, note=None, sign=-1):
    name = (name or "").strip()
    if not name:
        raise ValueError("Le nom est obligatoire.")
    amount = abs(float(amount))
    date.fromisoformat(when)
    sign = 1 if (sign or -1) > 0 else -1
    if planned_id:
        conn.execute("UPDATE planned SET name=?, amount=?, date=?, keyword=?, note=?, sign=? WHERE id=?",
                     (name, amount, when, (keyword or name).strip(), note, sign, int(planned_id)))
    else:
        planned_id = conn.execute("INSERT INTO planned(name, amount, sign, date, keyword, created_at, note) VALUES (?,?,?,?,?,?,?)",
                                  (name, amount, sign, when, (keyword or name).strip(),
                                   datetime.now().isoformat(timespec="seconds"), note)).lastrowid
    conn.commit()
    return {"id": planned_id, "nom": name}


def delete_planned(conn, planned_id):
    n = conn.execute("DELETE FROM planned WHERE id = ?", (int(planned_id),)).rowcount
    conn.commit()
    return {"supprimes": n}


def _ref_upcoming(items, today, end):
    """Échéances des lignes actives de la liste de référence jusqu'à « end »."""
    res = []
    for it in items:
        if it["statut"] != "actif" or not it["prochain_prevu"]:
            continue
        d = date.fromisoformat(it["prochain_prevu"])
        while d <= end:
            res.append({"nom": it["nom"], "date": max(d, today).isoformat(), "montant": it["montant"],
                        "en_retard": d < today, "type": it["type"]})
            d = add_period(d, it["frequence"])
    return res


# --------------------------------------------------------------------------- #
# Crédits
# --------------------------------------------------------------------------- #
LOAN_WORDS = ("PRET", "CREDIT", "FINFROG", "FLOA", "COFIDIS", "CETELEM", "SOFINCO", "YOUNITED", "ONEY",
              "FRANFINANCE", "CARREFOUR BANQUE", "KLARNA", "ALMA", "SCALAPAY", "MENSUALITE", "ECHEANCE")


@functools.lru_cache(maxsize=50000)
def _kw(text):
    return re.sub(r"\s+", " ", strip_accents(text or "").upper()).strip()


def _matches_loan(loan, merchant, label, amount):
    """Une opération correspond à un crédit si son libellé contient celui du crédit
    et (si la mensualité est connue) si son montant est proche de la mensualité."""
    kw = _kw(loan["merchant"])
    if not kw:
        return False
    if kw not in _kw(merchant) and kw not in _kw(label) and _kw(merchant) not in kw:
        return False
    m = loan["monthly_payment"]
    return not m or abs(abs(amount) - m) <= max(2.0, 0.05 * m)


def _loan_for(conn, merchant, label, amount):
    for l in conn.execute("SELECT * FROM loans WHERE merchant IS NOT NULL"):
        if _matches_loan(l, merchant, label, amount):
            return l
    return None


def _next_due(day, today):
    """Prochaine date (aujourd'hui inclus) tombant le « day » du mois."""
    def at(y, m):
        last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
        return date(y, m, min(day, last))
    d = at(today.year, today.month)
    if d < today:
        d = at(today.year + (today.month == 12), today.month % 12 + 1)
    return d


def list_loans(conn, today=None):
    today = today or date.today()
    out = []
    for l in conn.execute("SELECT * FROM loans ORDER BY name"):
        payments = []
        if l["merchant"]:
            rows = conn.execute("SELECT date, merchant, label, amount FROM transactions WHERE amount < 0 AND date > ? ORDER BY date",
                                (l["reference_date"],)).fetchall()
            payments = [r for r in rows if _matches_loan(l, r["merchant"], r["label"], r["amount"])]
        auto = round(sum(-p["amount"] for p in payments), 2)
        repaid = round(l["repaid_initial"] + auto, 2)
        total = l["total_due"]
        remaining = round(max(0.0, total - repaid), 2) if total is not None else None
        monthly = l["monthly_payment"]
        done = remaining is not None and remaining <= 0
        nxt = _next_due(l["payment_day"], today) if l["payment_day"] and not done else None
        n_left = int(-(-remaining // monthly)) if monthly and remaining else 0  # arrondi supérieur
        end = add_period(nxt or today, "mensuel", n_left - 1) if n_left else None
        out.append({
            "id": l["id"], "nom": l["name"],
            "montant_total": round(total, 2) if total is not None else None,
            "deja_rembourse": repaid, "reste_a_rembourser": remaining,
            "progression": round(100 * repaid / total, 1) if total else None,
            "mensualite": round(monthly, 2) if monthly else None,
            "jour_prelevement": l["payment_day"],
            "mensualites_restantes": n_left,
            "prochaine_echeance": nxt.isoformat() if nxt else None,
            "fin_estimee": end.isoformat() if end else None,
            "prelevement_associe": l["merchant"],
            "remboursements_suivis_auto": auto,
            "dernier_remboursement": payments[-1]["date"] if payments else None,
            "rembourse_le": l["reference_date"], "rembourse_saisi": round(l["repaid_initial"], 2),
            "note": l["note"], "termine": done, "montant_a_preciser": total is None,
        })
    out.sort(key=lambda x: (x["termine"], x["montant_a_preciser"], -(x["reste_a_rembourser"] or 0)))
    return {
        "credits": out,
        "total_restant": round(sum(x["reste_a_rembourser"] or 0 for x in out), 2),
        "total_mensualites": round(sum(x["mensualite"] or 0 for x in out if not x["termine"]), 2),
        "montants_a_preciser": [x["nom"] for x in out if x["montant_a_preciser"]],
    }


def loan_installments(conn, today, end):
    """Échéances de crédit (jour de prélèvement connu) entre aujourd'hui et « end »."""
    res = []
    for l in list_loans(conn, today)["credits"]:
        if l["termine"] or not l["mensualite"] or not l["prochaine_echeance"]:
            continue
        d = date.fromisoformat(l["prochaine_echeance"])
        if d <= end:
            res.append({"nom": l["nom"], "date": d.isoformat(), "montant": l["mensualite"],
                        "en_retard": False, "credit": True, "libelle": l["prelevement_associe"]})
    return res


def loan_candidates(conn):
    """Prélèvements réguliers qui ressemblent à des remboursements de crédit (pour aider à les rattacher)."""
    res = []
    hidden = {r[0] for r in conn.execute("SELECT merchant FROM loan_candidates_hidden")}
    for r in _detect_recurring(conn, -1, include_ignored=True, include_transfers=True):
        if r["marchand"] in hidden or _loan_for(conn, r["marchand"], r["libelle_exemple"], r["montant"]):
            continue
        txt = strip_accents((r["marchand"] + " " + (r["libelle_exemple"] or "")).upper())
        res.append({"marchand": r["marchand"], "montant": r["montant"], "actif": r["actif"],
                    "dernier_paiement": r["dernier_paiement"],
                    "ressemble_a_un_credit": any(w in txt for w in LOAN_WORDS)})
    res.sort(key=lambda x: (not x["ressemble_a_un_credit"], not x["actif"], -x["montant"]))
    return res


def save_loan(conn, loan_id=None, name=None, total_due=None, repaid=None, monthly_payment=None,
              merchant=None, note=None, reference_date=None, payment_day=None):
    """Crée ou modifie un crédit. « repaid » = déjà remboursé aujourd'hui (ou à reference_date).
    total_due vide = montant total à préciser plus tard."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Le nom du crédit est obligatoire.")
    num = lambda v: abs(float(v)) if v not in (None, "") else None  # noqa: E731
    total_due, monthly_payment = num(total_due), num(monthly_payment)
    repaid = num(repaid) or 0.0
    if total_due is not None and repaid > total_due:
        raise ValueError("Le montant déjà remboursé dépasse le montant total.")
    payment_day = int(payment_day) if payment_day not in (None, "") else None
    if payment_day is not None and not 1 <= payment_day <= 31:
        raise ValueError("Le jour de prélèvement doit être entre 1 et 31.")
    ref = reference_date or date.today().isoformat()
    date.fromisoformat(ref)
    merchant = (merchant or "").strip() or None
    vals = (name, total_due, repaid, ref, monthly_payment, payment_day, merchant, note)
    if loan_id:
        conn.execute("UPDATE loans SET name=?, total_due=?, repaid_initial=?, reference_date=?, monthly_payment=?, "
                     "payment_day=?, merchant=?, note=? WHERE id=?", vals + (int(loan_id),))
    else:
        loan_id = conn.execute("INSERT INTO loans(name, total_due, repaid_initial, reference_date, monthly_payment, "
                               "payment_day, merchant, note) VALUES (?,?,?,?,?,?,?,?)", vals).lastrowid
    conn.commit()
    return {"id": loan_id, "nom": name}


def hide_loan_candidate(conn, merchant, hidden=True):
    """Retire (ou remet) un prélèvement de la liste des crédits suggérés."""
    if hidden:
        conn.execute("INSERT OR IGNORE INTO loan_candidates_hidden(merchant) VALUES (?)", (merchant,))
    else:
        conn.execute("DELETE FROM loan_candidates_hidden WHERE merchant = ?", (merchant,))
    conn.commit()
    return {"ok": True}


def delete_loan(conn, loan_id):
    n = conn.execute("DELETE FROM loans WHERE id = ?", (int(loan_id),)).rowcount
    conn.commit()
    return {"supprimes": n}


# --------------------------------------------------------------------------- #
# Soldes et prévisionnel
# --------------------------------------------------------------------------- #
def guess_kind(name):
    up = strip_accents(name or "").upper()
    return "epargne" if any(w in up for w in SAVINGS_WORDS) else "courant"


def set_manual_balance(conn, account_name, amount):
    acc = get_or_create_account(conn, account_name, "manuel")
    kind = conn.execute("SELECT kind FROM accounts WHERE id = ?", (acc,)).fetchone()["kind"]
    conn.execute("UPDATE accounts SET balance = ?, balance_at = ?, kind = COALESCE(kind, ?) WHERE id = ?",
                 (float(amount), datetime.now().isoformat(timespec="seconds"), guess_kind(account_name), acc))
    conn.commit()
    return {"compte": account_name, "solde": float(amount), "type": kind or guess_kind(account_name)}


SALARY_CATEGORY = "Salaire"


def pending_salaries(conn, days=35):
    """Salaires arrivés récemment mais pas encore confirmés par l'utilisateur."""
    since = (date.today() - timedelta(days=days)).isoformat()
    return [dict(r) for r in conn.execute(
        "SELECT t.id, t.date, t.label, t.merchant, t.amount, a.name AS account, t.account_id "
        "FROM transactions t JOIN accounts a ON a.id = t.account_id "
        "WHERE t.category = ? AND t.amount > 0 AND t.date >= ? "
        "AND t.id NOT IN (SELECT tx_id FROM salary_confirmations) ORDER BY t.date",
        (SALARY_CATEGORY, since))]


def confirm_salary(conn, tx_id, received=True):
    """received=True : salaire bien reçu, il entre dans le solde.
    received=False : ce n'est pas le salaire, l'opération est reclassée en « Revenus »."""
    row = conn.execute("SELECT id FROM transactions WHERE id = ?", (int(tx_id),)).fetchone()
    if not row:
        raise ValueError("Opération introuvable")
    if received:
        conn.execute("INSERT OR REPLACE INTO salary_confirmations(tx_id, confirmed_at) VALUES (?, ?)",
                     (int(tx_id), datetime.now().isoformat(timespec="seconds")))
    else:
        conn.execute("UPDATE transactions SET category = 'Revenus', category_manual = 1 WHERE id = ?", (int(tx_id),))
    conn.commit()
    return {"ok": True}


def balances(conn):
    """Solde de chaque compte. Pour un solde saisi à la main, on y ajoute les opérations importées depuis.
    Le salaire est compté dès qu'il apparaît sur le compte (règle de l'utilisateur : sa date varie selon le jour de la semaine)."""
    pending = []
    pending_by_acc = {}
    for p in pending:
        pending_by_acc[p["account_id"]] = pending_by_acc.get(p["account_id"], 0) + p["amount"]
    out = []
    for a in conn.execute("SELECT * FROM accounts ORDER BY id"):
        kind = a["kind"] or guess_kind(a["name"])
        cur = None
        if a["balance"] is not None:
            since = (a["balance_at"] or "")[:10]
            delta = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id = ? AND date > ?",
                                 (a["id"], since)).fetchone()[0] if since else 0
            cur = round(a["balance"] + delta - pending_by_acc.get(a["id"], 0), 2)
        out.append({"compte": a["name"], "type": kind, "source": a["source"], "solde": cur,
                    "solde_releve_le": a["balance_at"],
                    "salaire_a_confirmer": round(pending_by_acc.get(a["id"], 0), 2)})
    courant = [x for x in out if x["type"] == "courant" and x["solde"] is not None]
    epargne = [x for x in out if x["type"] == "epargne" and x["solde"] is not None]
    # Opérations à venir annoncées par la banque sur les comptes courants (paiements carte en attente, prélèvements…)
    courant_names = {x["compte"] for x in courant}
    coming = [c for c in list_coming(conn) if c["compte"] in courant_names]
    coming_total = round(sum(c["montant"] for c in coming), 2)
    solde_courant = round(sum(x["solde"] for x in courant), 2) if courant else None
    return {
        "comptes": out,
        "solde_courant": solde_courant,
        "operations_a_venir": len(coming),
        "total_operations_a_venir": coming_total,
        "solde_avec_operations_a_venir": round(solde_courant + coming_total, 2) if solde_courant is not None else None,
        "epargne": round(sum(x["solde"] for x in epargne), 2) if epargne else None,
        "connu": bool(courant),
        "salaires_a_confirmer": [{k: p[k] for k in ("id", "date", "merchant", "amount", "account")} for p in pending],
        "total_salaire_a_confirmer": round(sum(p["amount"] for p in pending), 2),
    }


def _upcoming(items, today, end, grace_days=5):
    """Échéances d'éléments récurrents entre aujourd'hui (moins quelques jours de retard toléré) et la fin du mois."""
    res = []
    for it in items:
        if not it["actif"] or it["statut"] == "ignored":
            continue
        d = date.fromisoformat(it["prochain_prevu"])
        if d < today - timedelta(days=grace_days):
            continue
        while d <= end:
            res.append({"nom": it["marchand"], "date": max(d, today).isoformat(), "montant": it["montant"],
                        "en_retard": d < today})
            d = add_period(d, it["frequence"])
    return sorted(res, key=lambda x: x["date"])


def forecast(conn, today=None):
    """Solde prévu à la fin du mois budgétaire (par ex. le 24 si le mois va du 25 au 24) sur les comptes courants,
    et, si le salaire tombe juste après, le solde une fois le salaire arrivé."""
    today = today or date.today()
    start_s, end_s = _month_bounds(cycle_of(today))
    if CYCLE_DAY > 1:
        # Mois « du 25 au 25 » : on s'arrête le 25 au soir, salaire compris, et on montre aussi la veille
        end = date.fromisoformat(end_s)
        res = _project(conn, today, end)
        veille = _project(conn, today, end - timedelta(days=1))
        res["veille"] = {"date": (end - timedelta(days=1)).isoformat(), "solde": veille["solde_prevu_fin_de_mois"]}
    else:
        end = date.fromisoformat(end_s) - timedelta(days=1)
        res = _project(conn, today, end)
        res["veille"] = None
    res["debut_du_mois"] = start_s
    res["jour_debut_mois"] = CYCLE_DAY
    return res


def _project(conn, today, end):
    """Solde prévu au soir du jour « end » : solde actuel − prélèvements, crédits et dépenses prévus
    + rentrées attendues − dépenses du quotidien estimées (selon le réglage)."""
    bal = balances(conn)
    courant = ("courant",)

    ref = subscription_list(conn, today)
    a_venir = _ref_upcoming([x for x in ref if x["sens"] == "depense"], today, end)
    loans_due = loan_installments(conn, today, end)
    loans_all = conn.execute("SELECT * FROM loans WHERE merchant IS NOT NULL").fetchall()
    planned = [p for p in planned_list(conn) if p["statut"] == "prevu" and date.fromisoformat(p["date"]) <= end]
    a_venir += [{"nom": p["nom"], "date": max(p["date"], today.isoformat()), "montant": p["montant"],
                 "en_retard": p["date"] < today.isoformat(), "type": "ponctuel"} for p in planned if p["sens"] == "depense"]
    a_venir = a_venir + loans_due
    # Opérations annoncées par la banque (comptes courants) : elles font foi et remplacent la prévision équivalente.
    kinds_by_name = {r["name"]: (r["kind"] or guess_kind(r["name"])) for r in conn.execute("SELECT name, kind FROM accounts")}
    bank_coming = [c for c in list_coming(conn) if kinds_by_name.get(c["compte"], "courant") == "courant"
                   and date.fromisoformat(c["date"]) <= end]
    ref_rows_all = conn.execute("SELECT * FROM manual_subscriptions").fetchall()
    loans_rows = conn.execute("SELECT * FROM loans WHERE merchant IS NOT NULL").fetchall()

    def _same(pred, c):
        """La prévision « pred » correspond-elle à l'opération annoncée « c » ?"""
        if abs((date.fromisoformat(pred["date"]) - date.fromisoformat(c["date"])).days) > 10:
            return False
        sign = -1 if c["montant"] < 0 else 1
        for x in ref_rows_all:
            if x["name"] == pred["nom"] and _sub_matches(x, c["libelle"], c["marchand"], c["montant"]):
                return True
        for l in loans_rows:
            if l["name"] == pred["nom"] and _matches_loan(l, c["marchand"], c["libelle"], c["montant"]):
                return True
        return pred.get("type") == "ponctuel" and abs(pred["montant"] - abs(c["montant"])) <= 1.0 and sign < 0
    for c in bank_coming:
        if c["montant"] < 0:
            a_venir = [p for p in a_venir if not _same(p, c)]
            a_venir.append({"nom": c["marchand"].title(), "libelle": c["libelle"], "date": max(c["date"], today.isoformat()),
                            "montant": round(-c["montant"], 2), "en_retard": False, "type": "banque"})
    a_venir = sorted(a_venir, key=lambda x: x["date"])
    revenus = _ref_upcoming([x for x in ref if x["sens"] == "rentree"], today, end)
    revenus += [{"nom": p["nom"], "date": max(p["date"], today.isoformat()), "montant": p["montant"],
                 "en_retard": p["date"] < today.isoformat(), "type": "ponctuel"} for p in planned if p["sens"] == "rentree"]
    for c in bank_coming:
        if c["montant"] > 0:
            revenus = [p for p in revenus if not _same(p, c)]
            revenus.append({"nom": c["marchand"].title(), "libelle": c["libelle"], "date": max(c["date"], today.isoformat()),
                            "montant": round(c["montant"], 2), "en_retard": False, "type": "banque"})
    revenus = sorted(revenus, key=lambda x: x["date"])
    # Salaire : détecté automatiquement, compté seulement une fois reçu et confirmé
    # Le salaire fait partie des rentrées régulières de la liste (montant habituel, vers le 25) : il est compté
    # dans le prévisionnel ; il entre dans le solde actuel le jour où il apparaît sur le compte.
    salaire_attendu = []
    ref_rows = conn.execute("SELECT * FROM manual_subscriptions").fetchall()

    # Dépenses courantes : tout ce qui n'est ni récurrent ni un virement interne, sur les comptes courants.
    # Estimation robuste : médiane des 3 derniers mois complets, au prorata des jours restants.
    kinds = _account_kinds(conn)
    month_start = date.fromisoformat(_month_bounds(cycle_of(today))[0])
    months = []
    m_end = month_start
    for _ in range(3):
        m_start = date.fromisoformat(_month_bounds(cycle_of(m_end - timedelta(days=1)))[0])
        rows = conn.execute("SELECT account_id, merchant, label, amount, category FROM transactions "
                            "WHERE amount < 0 AND date >= ? AND date < ?",
                            (m_start.isoformat(), m_end.isoformat())).fetchall()
        if rows:
            months.append(sum(-r["amount"] for r in rows
                              if kinds.get(r["account_id"], "courant") == "courant"
                              and r["category"] not in TRANSFER_CATEGORIES
                              and not any(_sub_matches(x, r["label"], r["merchant"], r["amount"]) for x in ref_rows)
                              and not any(_matches_loan(l, r["merchant"], r["label"], r["amount"]) for l in loans_all)))
        m_end = m_start
    habit = statistics.median(months) if months else 0.0
    mode = get_setting(conn, "estimation_depenses")
    monthly = habit if mode == "habitudes" else float(get_setting(conn, "budget_quotidien_mensuel")) if mode == "budget" else 0.0
    days_in_month = (date.fromisoformat(_month_bounds(cycle_of(today))[1]) - month_start).days
    days_left = (end - today).days
    daily = monthly / days_in_month
    variable = round(daily * days_left, 2)

    total_out = round(sum(x["montant"] for x in a_venir), 2)
    total_in = round(sum(x["montant"] for x in revenus), 2)
    total_sal = round(sum(x["montant"] for x in salaire_attendu), 2)
    current = bal["solde_courant"]
    pending_sal = bal["total_salaire_a_confirmer"]
    return {
        "aujourd_hui": today.isoformat(),
        "fin_du_mois": end.isoformat(),
        "jours_restants": days_left,
        "solde_actuel": current,
        "prelevements_a_venir": a_venir,
        "total_prelevements_a_venir": total_out,
        "revenus_attendus": revenus,
        "total_revenus_attendus": total_in,
        "depense_courante_par_jour": round(daily, 2),
        "depenses_courantes_mensuelles_habituelles": round(habit, 2),
        "mode_estimation": mode,
        "budget_quotidien_mensuel": float(get_setting(conn, "budget_quotidien_mensuel")),
        "depenses_courantes_estimees": variable,
        "solde_prevu_fin_de_mois": round(current - total_out + total_in - variable, 2) if current is not None else None,
        # Non compté tant que le salaire n'est pas reçu et confirmé :
        "salaire_attendu": salaire_attendu,
        "total_salaire_attendu": total_sal,
        "salaire_recu_a_confirmer": pending_sal,
        "solde_prevu_avec_salaire": round(current - total_out + total_in - variable + total_sal + pending_sal, 2)
        if current is not None else None,
    }


def set_subscription_status(conn, merchant, status):
    if status in (None, "", "detecte"):
        conn.execute("DELETE FROM subscription_overrides WHERE merchant = ?", (merchant,))
    else:
        conn.execute("INSERT OR REPLACE INTO subscription_overrides(merchant, status) VALUES (?, ?)",
                     (merchant, status))
    conn.commit()


def set_category(conn, tx_id, category, apply_to_merchant=False, create_rule=False):
    row = conn.execute("SELECT merchant FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if not row:
        raise ValueError(f"Opération {tx_id} introuvable")
    if apply_to_merchant:
        n = conn.execute("UPDATE transactions SET category = ?, category_manual = 1 WHERE merchant = ?",
                         (category, row["merchant"])).rowcount
    else:
        n = conn.execute("UPDATE transactions SET category = ?, category_manual = 1 WHERE id = ?",
                         (category, tx_id)).rowcount
    if create_rule:
        conn.execute("INSERT OR IGNORE INTO rules(keyword, category, priority) VALUES (?, ?, 10)",
                     (row["merchant"], category))
    conn.commit()
    return {"modifiees": n, "marchand": row["merchant"], "categorie": category}


def set_note(conn, tx_id, note):
    conn.execute("UPDATE transactions SET note = ? WHERE id = ?", (note, tx_id))
    conn.commit()


def add_rule(conn, keyword, category):
    conn.execute("INSERT OR IGNORE INTO rules(keyword, category, priority) VALUES (?, ?, 10)",
                 (keyword.upper(), category))
    conn.commit()
    return {"regle": keyword.upper(), "categorie": category, "recategorisees": recategorize_all(conn)}


# --------------------------------------------------------------------------- #
# Onglet Budget : budget par catégorie, rempli par les dépenses
# --------------------------------------------------------------------------- #
# Catégories principales proposées au départ (dans cet ordre), puis celles qui ont des dépenses.
MAIN_BUDGET_CATEGORIES = ["Logement", "Courses", "Transport", "Restaurants & sorties", "Télécom & internet",
                          "Abonnements & streaming", "Assurances & banque", "Santé", "Shopping",
                          "Sport & loisirs", "Impôts & administration", "Retraits d'espèces"]
NOT_BUDGETED = TRANSFER_CATEGORIES | INCOME_CATEGORIES


def _ensure_budget_categories(conn):
    """Remplit la liste la première fois (ensuite, c'est l'utilisateur qui la gère)."""
    if conn.execute("SELECT 1 FROM settings WHERE key = 'budget_categories_init'").fetchone():
        return
    names = list(MAIN_BUDGET_CATEGORIES)
    ph = ",".join("?" * len(NOT_BUDGETED))
    for r in conn.execute(f"SELECT category, SUM(amount) s FROM transactions WHERE amount < 0 AND category NOT IN ({ph}) "
                          f"AND category != ? GROUP BY category ORDER BY s", (*NOT_BUDGETED, UNCATEGORIZED)):
        if r["category"] and r["category"] not in names:
            names.append(r["category"])
    old = {r["category"]: r["monthly_limit"] for r in conn.execute("SELECT * FROM budgets")}
    for i, n in enumerate(names):
        conn.execute("INSERT OR IGNORE INTO budget_categories(name, monthly_limit, position) VALUES (?, ?, ?)",
                     (n, old.get(n), i))
    conn.execute("INSERT OR REPLACE INTO settings(key, value) VALUES ('budget_categories_init', '1')")
    conn.commit()


def _budget_limits(conn):
    _ensure_budget_categories(conn)
    return {r["name"]: r["monthly_limit"] for r in conn.execute(
        "SELECT name, monthly_limit FROM budget_categories WHERE monthly_limit IS NOT NULL")}


def budget_table(conn, month):
    """Tableau de l'onglet Budget : pour chaque catégorie, budget, dépensé et reste sur le mois budgétaire."""
    _ensure_budget_categories(conn)
    start, end = _month_bounds(month)
    clause, p = _cycle_clause(start, end)
    spent = {}
    for r in conn.execute("SELECT category, SUM(amount) s, COUNT(*) n FROM transactions WHERE 1=1" + clause +
                          " GROUP BY category", p):
        spent[r["category"]] = (max(0.0, -(r["s"] or 0)), r["n"])
    rows = []
    for r in conn.execute("SELECT name, monthly_limit FROM budget_categories ORDER BY position, name"):
        dep, n = spent.get(r["name"], (0.0, 0))
        lim = r["monthly_limit"]
        rows.append({"categorie": r["name"], "budget": lim, "depense": round(dep, 2), "operations": n,
                     "reste": round(lim - dep, 2) if lim is not None else None,
                     "progression": round(100 * dep / lim, 1) if lim else None})
    listed = {r["categorie"] for r in rows}
    autres = [{"categorie": c, "depense": round(d, 2), "operations": n} for c, (d, n) in spent.items()
              if c not in listed and c not in NOT_BUDGETED and d > 0]
    autres.sort(key=lambda a: -a["depense"])
    total_budget = sum(r["budget"] or 0 for r in rows)
    total_dep = sum(r["depense"] for r in rows)
    return {"mois": month, "periode": {"debut": start, "fin_exclue": end}, "categories": rows,
            "hors_budget": autres, "total_hors_budget": round(sum(a["depense"] for a in autres), 2),
            "total_budget": round(total_budget, 2), "total_depense": round(total_dep, 2),
            "total_reste": round(total_budget - sum(r["depense"] for r in rows if r["budget"] is not None), 2)}


def save_budget_category(conn, name, monthly_limit=None, old_name=None):
    """Ajoute une catégorie, ou modifie son nom et son budget. Renommer suit aussi les opérations et les règles."""
    _ensure_budget_categories(conn)
    name = (name or "").strip()
    if not name:
        raise ValueError("Donne un nom à la catégorie.")
    if name in NOT_BUDGETED:
        raise ValueError(f"« {name} » est une catégorie de rentrées ou de virements internes.")
    lim = None if monthly_limit in (None, "") or float(monthly_limit) <= 0 else round(float(monthly_limit), 2)
    if not old_name:
        if conn.execute("SELECT 1 FROM budget_categories WHERE name = ?", (name,)).fetchone():
            raise ValueError(f"La catégorie « {name} » existe déjà.")
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM budget_categories").fetchone()[0]
        conn.execute("INSERT INTO budget_categories(name, monthly_limit, position) VALUES (?, ?, ?)", (name, lim, pos))
    else:
        if not conn.execute("SELECT 1 FROM budget_categories WHERE name = ?", (old_name,)).fetchone():
            raise ValueError(f"Catégorie inconnue : {old_name}")
        if name != old_name:
            if old_name in (UNCATEGORIZED,):
                raise ValueError(f"« {old_name} » ne peut pas être renommée.")
            if conn.execute("SELECT 1 FROM budget_categories WHERE name = ?", (name,)).fetchone():
                raise ValueError(f"La catégorie « {name} » existe déjà.")
            conn.execute("UPDATE budget_categories SET name = ? WHERE name = ?", (name, old_name))
            conn.execute("UPDATE transactions SET category = ? WHERE category = ?", (name, old_name))
            conn.execute("UPDATE OR IGNORE rules SET category = ? WHERE category = ?", (name, old_name))
            conn.execute("DELETE FROM rules WHERE category = ?", (old_name,))
            conn.execute("UPDATE manual_subscriptions SET category = ? WHERE category = ?", (name, old_name))
            conn.execute("DELETE FROM budgets WHERE category = ?", (old_name,))
        conn.execute("UPDATE budget_categories SET monthly_limit = ? WHERE name = ?", (lim, name))
    conn.commit()
    return {"categorie": name, "budget": lim}


def budget_category_detail(conn, name, month, search=None):
    """Fenêtre de détail d'une catégorie : ses opérations du mois, ses mots-clés, et les dépenses à y ajouter."""
    _ensure_budget_categories(conn)
    start, end = _month_bounds(month)
    row = conn.execute("SELECT monthly_limit FROM budget_categories WHERE name = ?", (name,)).fetchone()
    lim = row["monthly_limit"] if row else None
    ops = list_transactions(conn, start=start, end=end, category=name, limit=2000)
    dep = round(max(0.0, -sum(o["amount"] for o in ops)), 2)
    rules = [{"mot_cle": r["keyword"].strip(), "perso": (r["priority"] or 0) > 0} for r in conn.execute(
        "SELECT keyword, priority FROM rules WHERE category = ? ORDER BY priority DESC, keyword", (name,))]
    if search and search.strip():
        cand = list_transactions(conn, search=search.strip(), max_amount=-0.0001, limit=400)
    else:
        cand = list_transactions(conn, start=start, end=end, max_amount=-0.0001, limit=2000)
    cand = [c for c in cand if c["category"] != name and c["category"] not in NOT_BUDGETED]
    if not (search and search.strip()):
        cand.sort(key=lambda c: c["category"] != UNCATEGORIZED)  # « À classer » d'abord, puis par date
    return {"categorie": name, "dans_le_tableau": row is not None, "mois": month,
            "periode": {"debut": start, "fin_exclue": end}, "budget": lim, "depense": dep,
            "reste": round(lim - dep, 2) if lim is not None else None,
            "operations": ops, "mots_cles": rules, "a_ajouter": cand[:200]}


def _clean_keyword(keyword):
    kw = re.sub(r"\s+", " ", strip_accents(keyword or "").upper()).strip()
    if len(kw) < 3:
        raise ValueError("Le mot-clé doit faire au moins 3 caractères.")
    return kw


def add_category_keyword(conn, category, keyword):
    """Toute opération dont le libellé contient ce mot-clé ira dans la catégorie (passées et à venir)."""
    kw = _clean_keyword(keyword)
    before = [r[0] for r in conn.execute("SELECT category FROM rules WHERE keyword = ? AND category != ?",
                                         (kw, category))]
    conn.execute("DELETE FROM rules WHERE keyword = ? AND category != ?", (kw, category))  # un mot-clé = une catégorie
    conn.execute("INSERT OR REPLACE INTO rules(keyword, category, priority) VALUES (?, ?, 10)", (kw, category))
    conn.commit()
    recategorize_all(conn)
    like = f"%{kw}%"
    n = conn.execute("SELECT COUNT(*) FROM transactions WHERE category = ? AND (UPPER(label) LIKE ? OR merchant LIKE ?)",
                     (category, like, like)).fetchone()[0]
    return {"mot_cle": kw, "categorie": category, "operations": n, "avant": before}


def delete_category_keyword(conn, category, keyword):
    conn.execute("DELETE FROM rules WHERE category = ? AND TRIM(UPPER(keyword)) = ?",
                 (category, re.sub(r"\s+", " ", (keyword or "").upper()).strip()))
    conn.commit()
    recategorize_all(conn)
    return {"supprime": keyword, "categorie": category}


def assign_to_category(conn, tx_id, category, always=False):
    """Range une dépense dans la catégorie ; « always » : aussi toutes celles du même marchand, et les prochaines."""
    row = conn.execute("SELECT merchant FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    if not row:
        raise ValueError(f"Opération {tx_id} introuvable")
    if not always:
        conn.execute("UPDATE transactions SET category = ?, category_manual = 1 WHERE id = ?", (category, tx_id))
        conn.commit()
        return {"operations": 1, "categorie": category}
    kw = row["merchant"]
    r = add_category_keyword(conn, category, kw)
    # Celles de ce marchand classées à la main ailleurs suivent aussi (la règle les gouverne désormais)
    n = conn.execute("UPDATE transactions SET category = ?, category_manual = 0 WHERE merchant = ?",
                     (category, kw)).rowcount
    conn.commit()
    return {"operations": n, "categorie": category, "mot_cle": r["mot_cle"], "avant": r["avant"]}


def delete_budget_category(conn, name):
    """Retire la catégorie du tableau Budget (les opérations gardent leur catégorie)."""
    _ensure_budget_categories(conn)
    conn.execute("DELETE FROM budget_categories WHERE name = ?", (name,))
    conn.execute("DELETE FROM budgets WHERE category = ?", (name,))
    conn.commit()
    return {"supprimee": name}


def set_budget(conn, category, monthly_limit):
    """Budget mensuel d'une catégorie (vide ou 0 = pas de budget) ; la catégorie rejoint le tableau Budget."""
    _ensure_budget_categories(conn)
    lim = None if monthly_limit is None or float(monthly_limit) <= 0 else float(monthly_limit)
    if conn.execute("SELECT 1 FROM budget_categories WHERE name = ?", (category,)).fetchone():
        conn.execute("UPDATE budget_categories SET monthly_limit = ? WHERE name = ?", (lim, category))
    elif lim is not None:
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM budget_categories").fetchone()[0]
        conn.execute("INSERT INTO budget_categories(name, monthly_limit, position) VALUES (?, ?, ?)",
                     (category, lim, pos))
    conn.commit()


def categories(conn):
    cats = set(DEFAULT_RULES) | {UNCATEGORIZED}
    cats |= {r[0] for r in conn.execute("SELECT DISTINCT category FROM rules")}
    cats |= {r[0] for r in conn.execute("SELECT name FROM budget_categories")}
    cats |= {r[0] for r in conn.execute("SELECT DISTINCT category FROM transactions WHERE category IS NOT NULL")}
    return sorted(cats)


def top_merchants(conn, start=None, end=None, limit=15):
    q = ("SELECT merchant, SUM(-amount) total, COUNT(*) n FROM transactions WHERE amount < 0 "
         "AND category NOT IN ({})".format(",".join("?" * len(TRANSFER_CATEGORIES))))
    p = list(TRANSFER_CATEGORIES)
    if start:
        q += " AND date >= ?"; p.append(start)
    if end:
        q += " AND date < ?"; p.append(end)
    q += " GROUP BY merchant ORDER BY total DESC LIMIT ?"
    p.append(limit)
    return [{"marchand": r["merchant"], "total": round(r["total"], 2), "operations": r["n"]}
            for r in conn.execute(q, p)]


def set_account_balance(conn, name, balance, kind=None):
    conn.execute("UPDATE accounts SET balance = ?, balance_at = ?, kind = COALESCE(?, kind) WHERE name = ?",
                 (balance, datetime.now().isoformat(timespec="seconds"), kind, name))
    conn.commit()


def accounts(conn):
    return [dict(r) for r in conn.execute(
        "SELECT a.name, a.source, a.balance AS solde, a.balance_at AS solde_au, COUNT(t.id) operations, "
        "ROUND(SUM(t.amount), 2) cumul, MIN(t.date) premiere, MAX(t.date) derniere FROM accounts a "
        "LEFT JOIN transactions t ON t.account_id = a.id GROUP BY a.id")]
