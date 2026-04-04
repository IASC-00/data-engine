"""
SQLite database for Data Engine leads.
"""

import sqlite3
import os

DB_PATH = os.path.expanduser("~/.data-engine/leads.db")


def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS leads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT NOT NULL,           -- opencorporates, yelp, google
            biz_name    TEXT NOT NULL,
            owner_name  TEXT,
            biz_type    TEXT,                    -- LLC, restaurant, property_manager, etc.
            address     TEXT,
            city        TEXT,
            state       TEXT,
            zip         TEXT,
            phone       TEXT,
            website     TEXT,
            email       TEXT,
            email_source TEXT,                   -- whois, scrape, guess, hunter, apollo
            email_verified INTEGER DEFAULT 0,    -- 1 = MX verified
            filing_date TEXT,                    -- SoS filing date
            yelp_rating REAL,
            yelp_category TEXT,
            enriched    INTEGER DEFAULT 0,       -- 1 = enrichment attempted
            outreach_sent INTEGER DEFAULT 0,
            campaign_week TEXT,                  -- e.g. '2026-W14'
            outreach_status TEXT DEFAULT 'pending', -- pending, contacted, interested, no_reply
            appforge_url TEXT,                   -- generated demo URL
            created_at  TEXT DEFAULT (datetime('now')),
            updated_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_state ON leads(state);
        CREATE INDEX IF NOT EXISTS idx_biz_type ON leads(biz_type);
        CREATE INDEX IF NOT EXISTS idx_enriched ON leads(enriched);
        CREATE INDEX IF NOT EXISTS idx_email ON leads(email);
        CREATE INDEX IF NOT EXISTS idx_outreach ON leads(outreach_sent);
    """)
    conn.commit()
    conn.close()


_VALID_COLUMNS = frozenset(
    {
        "source",
        "biz_name",
        "owner_name",
        "biz_type",
        "address",
        "city",
        "state",
        "zip",
        "phone",
        "website",
        "email",
        "email_source",
        "email_verified",
        "filing_date",
        "yelp_rating",
        "yelp_category",
        "enriched",
        "outreach_sent",
        "campaign_week",
        "outreach_status",
        "appforge_url",
    }
)


def _safe_data(data: dict) -> dict:
    """Strip any keys not in the schema allowlist before building dynamic SQL."""
    return {k: v for k, v in data.items() if k in _VALID_COLUMNS}


def upsert_lead(data: dict) -> int:
    """Insert lead or skip if biz_name + state already exists. Returns row id."""
    data = _safe_data(data)
    conn = get_conn()
    existing = conn.execute(
        "SELECT id FROM leads WHERE biz_name = ? AND state = ?",
        (data.get("biz_name", ""), data.get("state", "")),
    ).fetchone()
    if existing:
        conn.close()
        return existing["id"]

    cols = ", ".join(data.keys())
    placeholders = ", ".join("?" * len(data))
    conn.execute(
        f"INSERT INTO leads ({cols}) VALUES ({placeholders})", list(data.values())
    )
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return row_id


def update_lead(lead_id: int, data: dict):
    data = _safe_data(data)
    if not data:
        return
    sets = ", ".join(f"{k} = ?" for k in data.keys())
    conn = get_conn()
    conn.execute(
        f"UPDATE leads SET {sets}, updated_at = datetime('now') WHERE id = ?",
        list(data.values()) + [lead_id],
    )
    conn.commit()
    conn.close()


def get_unenriched(limit=50):
    conn = get_conn()
    # Prioritize leads with websites (most enrichable via scrape/hunter/apollo)
    rows = conn.execute(
        "SELECT * FROM leads WHERE enriched = 0 AND website IS NOT NULL AND website != '' ORDER BY id LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        rows = conn.execute(
            "SELECT * FROM leads WHERE enriched = 0 LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_stats():
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    with_email = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE email IS NOT NULL"
    ).fetchone()[0]
    enriched = conn.execute("SELECT COUNT(*) FROM leads WHERE enriched = 1").fetchone()[
        0
    ]
    outreach_sent = conn.execute(
        "SELECT COUNT(*) FROM leads WHERE outreach_sent = 1"
    ).fetchone()[0]
    by_state = conn.execute(
        "SELECT state, COUNT(*) as n FROM leads GROUP BY state ORDER BY n DESC"
    ).fetchall()
    by_source = conn.execute(
        "SELECT email_source, COUNT(*) as n FROM leads WHERE email_source IS NOT NULL GROUP BY email_source ORDER BY n DESC"
    ).fetchall()
    conn.close()
    return {
        "total": total,
        "with_email": with_email,
        "enriched": enriched,
        "outreach_sent": outreach_sent,
        "by_state": [dict(r) for r in by_state],
        "by_source": [dict(r) for r in by_source],
    }


def get_all_leads(state=None, with_email_only=False, campaign_only=False, limit=5000):
    conn = get_conn()
    query = "SELECT * FROM leads WHERE 1=1"
    params = []
    if state:
        query += " AND state = ?"
        params.append(state.upper())
    if with_email_only:
        query += " AND email IS NOT NULL AND email != ''"
    if campaign_only:
        query += " AND campaign_week IS NOT NULL"
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
