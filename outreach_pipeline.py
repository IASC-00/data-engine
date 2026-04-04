#!/usr/bin/env python3
"""
Outreach Pipeline — Step-by-step delegation tool.

Steps:
  1  extract   Pull all qualified Philly leads, filter junk emails → outreach_leads.csv
  2  generate  Generate personalized Email 1 per lead via Ollama (or OpenRouter fallback)
  3  review    Open review CSV for approval (mark approved=1 in the file)
  4  export    Export approved leads to send-ready CSV for Atelier / manual sending
  5  mark      Mark leads as outreach_sent=1 after sending

Usage:
  python3 outreach_pipeline.py extract
  python3 outreach_pipeline.py generate
  python3 outreach_pipeline.py stats
  python3 outreach_pipeline.py export
  python3 outreach_pipeline.py mark --file outreach_approved.csv
  python3 outreach_pipeline.py send --limit 10
"""

import csv
import json
import os
import re
import sqlite3
import sys
import smtplib
import ssl
import time
import random
from email.message import EmailMessage
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────

DB_PATH = Path.home() / ".data-engine" / "leads.db"
LEADS_CSV = Path("/mnt/c/Users/iswai/Desktop/ClaudeCode/outreach_leads.csv")
GENERATED_CSV = Path("/mnt/c/Users/iswai/Desktop/ClaudeCode/outreach_generated.csv")
APPROVED_CSV = Path("/mnt/c/Users/iswai/Desktop/ClaudeCode/outreach_approved.csv")

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = "nvidia/nemotron-3-nano-30b-a3b:free"

TARGET_TYPES = {
    "Restaurant",
    "Cafe",
    "Bar",
    "Pub",
    "Property Management",
    "Estate Agent",
}
TARGET_CITY = "Philadelphia"

JUNK_PATTERNS = re.compile(
    r"@(wix|wixpress|godaddy|dynadot|namecheap|sentry|hostgator|bluehost|squarespace"
    r"|shopify|wordpress|cpanel|softaculous|mailchimp|sendgrid|amazonses"
    r"|googlemail\.com\.invalid)|"
    r"(noreply|no-reply|abuse|postmaster|mailer-daemon|bounce|unsubscribe|admin@(?!.*\.(?:com|net|org|io)$))",
    re.IGNORECASE,
)

EMAIL_TEMPLATE = """Write a short cold email to a {biz_type} owner named {owner}.

Business: {biz_name}
Location: {address}, Philadelphia

Email rules:
- 3 sentences max, plain text, no subject line
- Mention their specific business name
- Tell them you built an AI chatbot for a South Philly restaurant that handles guest questions and reservation requests automatically, 24/7, for a one-time fee with no monthly subscriptions
- End with one soft ask: "Worth a quick look?"
- Sign as: Ian, iswain.dev
- No buzzwords. No "leverage" or "streamline". Sound like a real person.

Write only the email body, nothing else."""


# ── Helpers ───────────────────────────────────────────────────────────────────


def is_junk(email: str) -> bool:
    return bool(JUNK_PATTERNS.search(email))


def ollama_available() -> bool:
    try:
        r = httpx.get("http://localhost:11434/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def generate_email(lead: dict) -> str:
    owner = lead.get("owner_name") or "there"
    # Strip common noise from owner names
    if owner and any(x in owner.lower() for x in ["llc", "inc", "corp", "ltd"]):
        owner = "there"

    prompt = EMAIL_TEMPLATE.format(
        biz_type=lead.get("biz_type", "business"),
        owner=owner,
        biz_name=lead["biz_name"],
        address=lead.get("address", "Philadelphia"),
    )

    # Try Ollama first
    if ollama_available():
        try:
            r = httpx.post(
                OLLAMA_URL,
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.7, "num_predict": 200},
                },
                timeout=30,
            )
            if r.status_code == 200:
                return r.json().get("response", "").strip()
        except Exception:
            pass

    # Fall back to OpenRouter free tier
    if OPENROUTER_KEY:
        try:
            r = httpx.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_KEY}",
                    "HTTP-Referer": "https://iswain.dev",
                },
                json={
                    "model": OPENROUTER_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 200,
                    "temperature": 0.7,
                },
                timeout=30,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

    return "[GENERATION FAILED — write manually]"


# ── Steps ─────────────────────────────────────────────────────────────────────


def step_extract():
    """Step 1: Pull qualified leads, filter junk, save to CSV."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, biz_name, owner_name, biz_type, address, city,
               email, phone, website
        FROM leads
        WHERE city LIKE ? AND biz_type IN ({})
          AND (email IS NOT NULL AND email != '' OR phone IS NOT NULL AND phone != '')
          AND outreach_sent = 0
        ORDER BY CASE WHEN email IS NOT NULL AND email != '' THEN 0 ELSE 1 END, biz_name
    """.format(",".join("?" * len(TARGET_TYPES))),
        [f"%{TARGET_CITY}%"] + list(TARGET_TYPES),
    )

    rows = cur.fetchall()
    conn.close()

    clean, skipped = [], 0
    for row in rows:
        lead_id, biz_name, owner, biz_type, address, city, email, phone, website = row
        if email and is_junk(email):
            skipped += 1
            continue
        clean.append(
            {
                "id": lead_id,
                "biz_name": biz_name or "",
                "owner_name": owner or "",
                "biz_type": biz_type or "",
                "address": address or "",
                "email": email or "",
                "phone": phone or "",
                "website": website or "",
            }
        )

    LEADS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(LEADS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                "biz_name",
                "owner_name",
                "biz_type",
                "address",
                "email",
                "phone",
                "website",
            ],
        )
        w.writeheader()
        w.writerows(clean)

    print(f"✓ Extracted {len(clean)} qualified leads ({skipped} junk emails removed)")
    print(f"  Saved to: {LEADS_CSV}")

    by_type = {}
    for lead in clean:
        by_type[lead["biz_type"]] = by_type.get(lead["biz_type"], 0) + 1
    for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"    {t}: {n}")


def step_generate():
    """Step 2: Generate Email 1 for each lead using Ollama or OpenRouter."""
    if not LEADS_CSV.exists():
        print("Run step 1 first: python3 outreach_pipeline.py extract")
        sys.exit(1)

    with open(LEADS_CSV, newline="", encoding="utf-8") as f:
        leads = list(csv.DictReader(f))

    # Skip already generated
    done = set()
    if GENERATED_CSV.exists():
        with open(GENERATED_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("email_1"):
                    done.add(row["id"])

    pending = [l for l in leads if l["id"] not in done]
    print(f"Generating emails for {len(pending)} leads ({len(done)} already done)...")
    print(f"Using: {'Ollama' if ollama_available() else 'OpenRouter free tier'}")

    results = []
    # Load existing generated if any
    if GENERATED_CSV.exists():
        with open(GENERATED_CSV, newline="", encoding="utf-8") as f:
            results = list(csv.DictReader(f))

    for i, lead in enumerate(pending, 1):
        print(f"  [{i}/{len(pending)}] {lead['biz_name']}...", end=" ", flush=True)
        email_body = generate_email(lead)
        results.append({**lead, "email_1": email_body, "approved": 0, "sent": 0})
        print("done")

        # Save incrementally every 10
        if i % 10 == 0:
            _save_generated(results)
            print(f"  (saved checkpoint at {i})")

    _save_generated(results)
    print(f"\n✓ Done. Review and approve in: {GENERATED_CSV}")
    print("  Set approved=1 for any lead you want to send to.")


def _save_generated(rows):
    fields = [
        "id",
        "biz_name",
        "owner_name",
        "biz_type",
        "address",
        "email",
        "phone",
        "website",
        "email_1",
        "approved",
        "sent",
    ]
    with open(GENERATED_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def step_stats():
    """Show pipeline status."""
    for label, path in [("Extracted", LEADS_CSV), ("Generated", GENERATED_CSV)]:
        if path.exists():
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            approved = sum(1 for r in rows if str(r.get("approved", "")) == "1")
            sent = sum(1 for r in rows if str(r.get("sent", "")) == "1")
            print(f"{label}: {len(rows)} total | {approved} approved | {sent} sent")
        else:
            print(f"{label}: not generated yet")


def step_export():
    """Step 4: Export approved leads to send-ready CSV."""
    if not GENERATED_CSV.exists():
        print("Run step 2 first: python3 outreach_pipeline.py generate")
        sys.exit(1)

    with open(GENERATED_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    approved = [
        r
        for r in rows
        if str(r.get("approved", "")) == "1" and str(r.get("sent", "")) != "1"
    ]
    if not approved:
        print("No approved leads yet. Open outreach_generated.csv and set approved=1.")
        sys.exit(0)

    with open(APPROVED_CSV, "w", newline="", encoding="utf-8") as f:
        fields = ["id", "biz_name", "owner_name", "email", "phone", "email_1"]
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(approved)

    print(f"✓ Exported {len(approved)} approved leads to: {APPROVED_CSV}")


def step_mark(file_path: str):
    """Step 5: Mark leads as sent in the DB."""
    path = Path(file_path)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    ids = [r["id"] for r in rows if r.get("id")]
    if not ids:
        print("No IDs found in file.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.executemany("UPDATE leads SET outreach_sent=1 WHERE id=?", [(i,) for i in ids])
    conn.commit()
    conn.close()

    # Update generated CSV
    if GENERATED_CSV.exists():
        with open(GENERATED_CSV, newline="", encoding="utf-8") as f:
            gen = list(csv.DictReader(f))
        sent_ids = set(ids)
        for row in gen:
            if row["id"] in sent_ids:
                row["sent"] = 1
        _save_generated(gen)

    print(f"✓ Marked {len(ids)} leads as sent in DB and generated CSV.")


def step_send(limit=10):
    """Step 6: Send approved emails through local ProtonMail bridge."""
    if not APPROVED_CSV.exists():
        print(f"Run step 4 first: file not found: {APPROVED_CSV}")
        sys.exit(1)

    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    smtp_port = int(os.getenv("SMTP_PORT", "1025"))

    if not smtp_user or not smtp_pass:
        print("Error: SMTP_USER and SMTP_PASS must be set in .env")
        sys.exit(1)

    # Load approved from export file to satisfy "Reads outreach_approved.csv"
    with open(APPROVED_CSV, newline="", encoding="utf-8") as f:
        approved_rows = list(csv.DictReader(f))

    # Also load generated CSV to accurately verify approved=1, sent=0 and mark sent status
    with open(GENERATED_CSV, newline="", encoding="utf-8") as f:
        all_generated = list(csv.DictReader(f))
    gen_map = {r["id"]: r for r in all_generated}

    to_send = []
    for r in approved_rows:
        g = gen_map.get(r.get("id"))
        if g and str(g.get("approved", "")) == "1" and str(g.get("sent", "")) == "0":
            to_send.append(g)

    to_send = to_send[:limit]
    if not to_send:
        print("No approved, unsent leads found.")
        sys.exit(0)

    print(f"Sending {len(to_send)} emails via 127.0.0.1:{smtp_port}...")

    # Bridge uses a self-signed local cert — disable verification for localhost
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    try:
        with smtplib.SMTP("127.0.0.1", smtp_port) as server:
            server.starttls(context=context)
            server.login(smtp_user, smtp_pass)

            for i, lead in enumerate(to_send, 1):
                recipient = lead.get("email", "").strip()
                if not recipient:
                    print(
                        f"  [{i}/{len(to_send)}] Skipping {lead.get('biz_name')} — no email address"
                    )
                    continue

                biz_name = lead.get("biz_name", "your business")
                msg = EmailMessage()
                msg["Subject"] = f"Quick question for {biz_name}"
                msg["From"] = smtp_user
                msg["To"] = recipient
                msg.set_content(lead.get("email_1", ""))

                print(
                    f"  [{i}/{len(to_send)}] Sending to {lead.get('biz_name')} ({msg['To']})... ",
                    end="",
                    flush=True,
                )
                server.send_message(msg)

                # Mark as sent immediately in generated tracking
                lead["sent"] = 1
                _save_generated(all_generated)
                print("sent")

                if i < len(to_send):
                    delay = random.randint(180, 420)  # 3 to 7 minutes
                    print(f"  Waiting {delay} seconds before next email...")
                    time.sleep(delay)

    except Exception as e:
        print(f"\\nSMTP Error: {e}")
        sys.exit(1)

    print("✓ Send run complete.")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "stats"

    if cmd == "extract":
        step_extract()
    elif cmd == "generate":
        step_generate()
    elif cmd == "stats":
        step_stats()
    elif cmd == "export":
        step_export()
    elif cmd == "send":
        limit = 10
        if len(sys.argv) > 2 and sys.argv[2] == "--limit":
            limit = int(sys.argv[3])
        step_send(limit)
    elif cmd == "mark":
        if len(sys.argv) < 4 or sys.argv[2] != "--file":
            print("Usage: python3 outreach_pipeline.py mark --file <csv>")
            sys.exit(1)
        step_mark(sys.argv[3])
    else:
        print(__doc__)
