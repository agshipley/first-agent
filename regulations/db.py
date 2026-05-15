import os
import sqlite3

# On Railway the working directory is the project root, so resolve relative to
# this file to get a stable path regardless of where the process is launched from.
DB_PATH = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "regulations.db"))

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS regulations (
    id                    INTEGER PRIMARY KEY,
    region                TEXT,
    jurisdiction          TEXT,
    type                  TEXT,
    county                TEXT,
    program_name          TEXT,
    reg_type              TEXT,
    code_citation         TEXT,
    adopted_effective     TEXT,
    mandatory             TEXT,
    trigger_scope         TEXT,
    threshold             TEXT,
    project_types_covered TEXT,
    on_site_rate          TEXT,
    in_lieu_rate          TEXT,
    fee_cap               TEXT,
    compliance_options    TEXT,
    exemptions            TEXT,
    administrator_fund    TEXT,
    layered_with          TEXT,
    source_url            TEXT,
    date_verified         TEXT,
    currency_risk_flags   TEXT,
    confidence            TEXT,
    notes                 TEXT
);
CREATE INDEX IF NOT EXISTS idx_region       ON regulations(region);
CREATE INDEX IF NOT EXISTS idx_jurisdiction ON regulations(jurisdiction);
CREATE INDEX IF NOT EXISTS idx_mandatory    ON regulations(mandatory);
CREATE INDEX IF NOT EXISTS idx_reg_type     ON regulations(reg_type);
"""

_COLUMNS = [
    "id", "region", "jurisdiction", "type", "county", "program_name",
    "reg_type", "code_citation", "adopted_effective", "mandatory",
    "trigger_scope", "threshold", "project_types_covered", "on_site_rate",
    "in_lieu_rate", "fee_cap", "compliance_options", "exemptions",
    "administrator_fund", "layered_with", "source_url", "date_verified",
    "currency_risk_flags", "confidence", "notes",
]


def init_db(records):
    """Create the table and seed records if the table is empty. Safe to call on every startup."""
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(_CREATE_SQL)
        existing = conn.execute("SELECT count(*) FROM regulations").fetchone()[0]
        if existing == 0:
            ph = ", ".join(f":{c}" for c in _COLUMNS)
            conn.executemany(
                f"INSERT OR REPLACE INTO regulations ({', '.join(_COLUMNS)}) VALUES ({ph})",
                records,
            )
            conn.commit()
    finally:
        conn.close()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
