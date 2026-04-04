#!/usr/bin/env python3
"""
Export agency metrics to agency_stats.json for the portfolio ROI dashboard.
Run manually or add to weekly_enrich.sh to keep stats current.

Usage:
    python3 export_agency_stats.py [--output /path/to/agency_stats.json]
"""

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

LEADS_DB = Path.home() / ".data-engine" / "leads.db"
AUDITS_DB = Path(__file__).parent / "data" / "audits.db"
AUDIT_GENERATOR_DB = (
    Path(__file__).parent.parent / "automation-audit-generator" / "data" / "audits.db"
)
DEFAULT_OUTPUT = Path(__file__).parent.parent / "portfolio" / "agency_stats.json"


QUALIFIED = "(email IS NOT NULL AND email != '') OR (phone IS NOT NULL AND phone != '')"


def query_leads(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM leads")
    total = cur.fetchone()[0]

    cur.execute(f"SELECT COUNT(*) FROM leads WHERE {QUALIFIED}")
    qualified = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM leads WHERE email IS NOT NULL AND email != ''")
    with_email = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM leads WHERE phone IS NOT NULL AND phone != ''")
    with_phone = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM leads WHERE website IS NOT NULL AND website != ''"
    )
    with_website = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM leads WHERE outreach_sent = 1")
    outreach_sent = cur.fetchone()[0]

    conn.close()

    email_hit_rate = round(with_email / with_website * 100, 1) if with_website else 0.0

    return {
        "total": total,
        "qualified": qualified,  # has email OR phone — actionable leads only
        "with_email": with_email,
        "with_phone": with_phone,
        "with_website": with_website,
        "email_hit_rate": email_hit_rate,
        "outreach_sent": outreach_sent,
    }


def query_audits(db_path: Path) -> dict:
    if not db_path.exists():
        return {"total_generated": 0}

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM audits")
    total = cur.fetchone()[0]
    conn.close()

    return {"total_generated": total}


def main():
    parser = argparse.ArgumentParser(description="Export agency stats to JSON")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    leads = query_leads(LEADS_DB)

    # Use audit-generator DB (Railway deployment has the real data)
    audit_db = AUDIT_GENERATOR_DB if AUDIT_GENERATOR_DB.exists() else AUDITS_DB
    audits = query_audits(audit_db)

    stats = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "leads": leads,
        "audits": audits,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(stats, indent=2))
    print(f"Wrote {args.output}")
    print(
        f"  leads: {leads['total']:,} total, {leads['qualified']:,} qualified (email or phone), "
        f"{leads['with_email']:,} emails ({leads['email_hit_rate']}% hit rate)"
    )
    print(f"  audits: {audits['total_generated']} generated")


if __name__ == "__main__":
    main()
