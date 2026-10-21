"""0028 (G3): billing behind interfaces.

    billing_accounts   one per owner: plan, billing country, legal name,
                       GSTIN, state (place of supply), when it began
    credit_grants      credits given: the free trial, each month's plan
                       credits, top-ups
    invoices           every payment (fake providers, test mode) with its GST
                       split (CGST/SGST or IGST, or zero-rated export)

`down` drops the three tables (nothing refers to them)."""
from __future__ import annotations

from app.store.migrations._util import tables


def up(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS billing_accounts (
    owner        TEXT PRIMARY KEY,
    plan         TEXT,
    country      TEXT,
    legal_name   TEXT NOT NULL DEFAULT '',
    gstin        TEXT NOT NULL DEFAULT '',
    state_code   TEXT,
    created_at   TEXT NOT NULL
)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS credit_grants (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    owner      TEXT NOT NULL,
    kind       TEXT NOT NULL,
    credits    REAL NOT NULL,
    period     TEXT,
    reference  TEXT NOT NULL DEFAULT '',
    at         TEXT NOT NULL
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS credit_grants_owner ON credit_grants (owner, kind, period)")
    conn.execute("""CREATE TABLE IF NOT EXISTS invoices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    number       TEXT NOT NULL UNIQUE,
    owner        TEXT NOT NULL,
    provider     TEXT NOT NULL,
    checkout_id  TEXT NOT NULL,
    kind         TEXT NOT NULL,
    description  TEXT NOT NULL,
    currency     TEXT NOT NULL,
    subtotal     REAL NOT NULL,
    cgst         REAL NOT NULL DEFAULT 0,
    sgst         REAL NOT NULL DEFAULT 0,
    igst         REAL NOT NULL DEFAULT 0,
    total        REAL NOT NULL,
    tax_kind     TEXT NOT NULL,
    country      TEXT,
    state_code   TEXT,
    gstin        TEXT NOT NULL DEFAULT '',
    legal_name   TEXT NOT NULL DEFAULT '',
    test_mode    INTEGER NOT NULL DEFAULT 1,
    issued_at    TEXT NOT NULL
)""")


def down(conn) -> None:
    for table in ("invoices", "credit_grants", "billing_accounts"):
        if table in tables(conn):
            if table == "credit_grants":
                conn.execute("DROP INDEX IF EXISTS credit_grants_owner")
            conn.execute(f"DROP TABLE {table}")
