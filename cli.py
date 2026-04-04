#!/usr/bin/env python3
"""
Data Engine CLI — `de` command
"""

import os
import sys
import time
import subprocess

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

sys.path.insert(0, os.path.dirname(__file__))
from engine.db import (
    init_db,
    upsert_lead,
    get_unenriched,
    update_lead,
    get_stats,
    get_all_leads,
    get_conn,
)
from engine.fetcher import fetch_all
from engine.enricher import enrich_lead
from engine.exporter import export_csv

console = Console()


@click.group()
def cli():
    """Data Engine — NE lead generation pipeline."""
    init_db()


@cli.command()
@click.option(
    "--cities",
    default=None,
    help="Comma-separated city names to fetch (default: all NE cities)",
)
@click.option(
    "--categories",
    default=None,
    help="Comma-separated categories: restaurant,real_estate,contractor,professional (default: all)",
)
def fetch(cities, categories):
    """Fetch new leads from OpenStreetMap (free, no key needed) and store in DB."""
    from engine.osm import fetch_osm, NE_CITIES, OSM_QUERIES

    city_filter = None
    if cities:
        names = [c.strip().lower() for c in cities.split(",")]
        city_filter = {
            k: v for k, v in NE_CITIES.items() if any(n in k.lower() for n in names)
        }

    cat_filter = None
    if categories:
        cat_filter = [
            c.strip() for c in categories.split(",") if c.strip() in OSM_QUERIES
        ]

    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"), console=console
    ) as p:
        task = p.add_task("Fetching OSM leads...", total=None)

        p.update(task, description="Fetching OpenStreetMap businesses...")
        all_leads = fetch_osm(categories=cat_filter, cities=city_filter)
        console.print(f"  [dim]OSM: {len(all_leads)} businesses found[/dim]")

        p.update(task, description="Saving to database...")
        new_count = 0
        for lead in all_leads:
            lead_id = upsert_lead(lead)
            if lead_id:
                new_count += 1

    stats = get_stats()
    console.print(f"\n[green]Done.[/green] {new_count} new leads added.")
    console.print(
        f"[dim]Total in DB: {stats['total']} | With email: {stats['with_email']}[/dim]"
    )


@cli.command()
@click.option("--limit", default=50, help="Max leads to enrich per run (default: 50)")
@click.option("--all", "enrich_all", is_flag=True, help="Enrich all unenriched leads")
def enrich(limit, enrich_all):
    """Run email enrichment chain on unenriched leads."""
    batch_size = 10000 if enrich_all else limit
    leads = get_unenriched(limit=batch_size)

    if not leads:
        console.print("[yellow]No unenriched leads found.[/yellow]")
        return

    console.print(f"Enriching [bold]{len(leads)}[/bold] leads...\n")
    found = 0

    with Progress(
        SpinnerColumn(), TextColumn("{task.description}"), console=console
    ) as p:
        task = p.add_task("", total=len(leads))
        for i, lead in enumerate(leads):
            p.update(
                task, description=f"[{i + 1}/{len(leads)}] {lead['biz_name'][:40]}"
            )
            enriched = enrich_lead(lead)
            update_lead(
                lead["id"],
                {
                    "enriched": enriched.get("enriched", 1),
                    "email": enriched.get("email"),
                    "email_source": enriched.get("email_source"),
                    "email_verified": enriched.get("email_verified", 0),
                    "website": enriched.get("website", lead.get("website")),
                },
            )
            if enriched.get("email"):
                found += 1
            time.sleep(0.2)  # polite delay

    coverage = round(found / len(leads) * 100) if leads else 0
    console.print(
        f"\n[green]Done.[/green] Found {found}/{len(leads)} emails ({coverage}% coverage)."
    )


@cli.command()
@click.option("--state", default=None, help="Filter by state code (e.g. PA, NJ)")
@click.option(
    "--email-only", is_flag=True, help="Only export leads with verified emails"
)
@click.option("--output", default=None, help="Output file path (default: Desktop)")
def export(state, email_only, output):
    """Export leads to CSV on Desktop."""
    path = export_csv(state=state, with_email_only=email_only, output_path=output)
    if path:
        console.print(f"[green]Exported → {path}[/green]")
    else:
        console.print("[yellow]No leads to export.[/yellow]")


@cli.command()
def stats():
    """Show lead pipeline statistics."""
    s = get_stats()
    coverage = round(s["with_email"] / s["total"] * 100) if s["total"] else 0

    console.print("\n[bold]Data Engine Stats[/bold]\n")
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_row("[dim]Total leads[/dim]", f"[white]{s['total']}[/white]")
    t.add_row(
        "[dim]With email[/dim]",
        f"[green]{s['with_email']}[/green] [dim]({coverage}%)[/dim]",
    )
    t.add_row("[dim]Enriched[/dim]", f"[sky_blue1]{s['enriched']}[/sky_blue1]")
    t.add_row("[dim]Outreach sent[/dim]", f"[violet]{s['outreach_sent']}[/violet]")
    console.print(t)

    if s["by_state"]:
        console.print("\n[dim]By state:[/dim]")
        for row in s["by_state"][:8]:
            console.print(f"  {row['state']:4} {row['n']}")

    if s["by_source"]:
        console.print("\n[dim]Email sources:[/dim]")
        for row in s["by_source"]:
            console.print(f"  {(row['email_source'] or 'none'):12} {row['n']}")
    console.print()


@cli.command()
@click.option("--limit", default=100, help="Number of leads to curate for this week")
def curate(limit):
    """Select the best 100 leads (both email and phone) for current week."""
    from datetime import datetime
    week_str = datetime.now().strftime("%Y-W%W")
    
    conn = get_conn()
    existing = conn.execute("SELECT id FROM leads WHERE campaign_week = ?", (week_str,)).fetchall()
    if len(existing) >= limit:
        console.print(f"[yellow]Week {week_str} already has {len(existing)} leads curated.[/yellow]")
        conn.close()
        return

    to_add = limit - len(existing)
    leads = conn.execute("""
        SELECT id, biz_name FROM leads 
        WHERE email IS NOT NULL AND email != '' 
        AND phone IS NOT NULL AND phone != '' 
        AND campaign_week IS NULL
        ORDER BY enriched DESC, filing_date DESC, id ASC
        LIMIT ?
    """, (to_add,)).fetchall()

    if not leads:
        console.print("[red]No suitable leads found with both email and phone.[/red]")
        conn.close()
        return

    for l in leads:
        conn.execute("UPDATE leads SET campaign_week = ? WHERE id = ?", (week_str, l['id']))
    
    conn.commit()
    conn.close()
    
    console.print(f"[green]Successfully curated {len(leads)} leads for week {week_str}.[/green]")


@cli.command()
def board():
    """Generate and open the lead dashboard in browser."""
    from dashboard.renderer import render_dashboard

    path = render_dashboard()
    console.print(f"[green]Dashboard → {path}[/green]")
    try:
        subprocess.Popen(["powershell.exe", "Start", path])
    except Exception:
        try:
            subprocess.Popen(["xdg-open", path])
        except Exception:
            console.print(f"[dim]Open manually: {path}[/dim]")


@cli.command()
@click.argument("lead_id", type=int)
def appforge(lead_id):
    """Generate a personalized AppForge demo app for a lead."""
    import httpx as _httpx

    conn_module = __import__("engine.db", fromlist=["get_conn"])
    conn = conn_module.get_conn()
    lead = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    conn.close()

    if not lead:
        console.print(f"[red]Lead {lead_id} not found.[/red]")
        return

    lead = dict(lead)
    biz_name = lead.get("biz_name", "Local Business")
    biz_type = (lead.get("yelp_category") or lead.get("biz_type") or "").lower()
    city = lead.get("city", "")

    # Choose app type + prompt based on business category
    biz_type_lower = biz_type.lower()
    if any(
        k in biz_type_lower
        for k in [
            "restaurant",
            "food",
            "bar",
            "coffee",
            "pizza",
            "cafe",
            "bistro",
            "grill",
            "diner",
            "eatery",
            "kitchen",
            "pub",
        ]
    ):
        app_type = "landing_page"
        prompt = (
            f"Build a sharp, modern website for {biz_name}, a bar/restaurant in {city}. "
            f"Hero: bold headline with the venue name, tagline, and a prominent 'Reserve a Table' or 'See Events' CTA. "
            f"Include: events/specials section (3 upcoming events with dates), a featured drinks/menu section, "
            f"hours + address block, and a simple reservation/contact form. "
            f"Design: deep charcoal background (#0d0d0d), warm amber accent (#f5a623), clean bold sans-serif. "
            f"Feels like a real {city} venue site — not a template. Every section should be distinct and polished."
        )
    elif any(
        k in biz_type_lower
        for k in [
            "real estate",
            "realty",
            "realtor",
            "estate agent",
            "property management",
            "rental",
            "landlord",
        ]
    ):
        app_type = "lead_capture"
        if any(
            k in biz_type_lower for k in ["property management", "rental", "landlord"]
        ):
            prompt = (
                f"Build a clean, professional tenant portal landing page for {biz_name} in {city}. "
                f"Hero: bold headline 'Maintenance Requests. Rent Payments. All in One Place.' "
                f"Include a maintenance request form (tenant name, unit, issue type dropdown, urgency, description). "
                f"Design: dark navy (#0a0e1a) background, crisp white text, electric blue (#3b82f6) accents. "
                f"Feels trustworthy and modern — not like a generic form. Add a subtle grid pattern to the hero."
            )
        else:
            prompt = (
                f"Build a high-converting real estate lead capture page for {biz_name} in {city}. "
                f"Hero: bold headline 'What's Your Home Worth in {city}?' with a free valuation CTA. "
                f"Include: home valuation form (address, beds/baths, contact info), "
                f"3 trust badges (homes sold, years experience, 5-star rating), "
                f"and a recent listings preview section. "
                f"Design: deep navy (#0d1b2a) background, gold (#c9a84c) accents, elegant serif headline font. "
                f"Feels premium — like a top {city} agent's site, not a template."
            )
    elif any(
        k in biz_type_lower
        for k in [
            "contractor",
            "plumber",
            "electrician",
            "builder",
            "carpenter",
            "painter",
            "roofer",
            "hvac",
        ]
    ):
        app_type = "landing_page"
        prompt = (
            f"Build a bold, trust-heavy landing page for {biz_name}, a contractor in {city}. "
            f"Hero: strong headline 'Licensed. Insured. Done Right.' with a 'Get a Free Quote' CTA. "
            f"Include: services grid (3-4 services with icons), before/after project photos placeholders, "
            f"Google review stars widget, and a quick quote form (name, service type, zip, phone). "
            f"Design: dark slate (#1a1a2e) background, high-vis orange (#f97316) accents, bold industrial feel. "
            f"Looks like a contractor who actually shows up on time."
        )
    else:
        app_type = "landing_page"
        prompt = (
            f"Build a sharp, modern landing page for {biz_name}, a local {biz_type} business in {city}. "
            f"Hero: punchy headline about what makes them the best choice in {city}, with a clear CTA button. "
            f"Include: 3 key services/offerings with icons, a short about section, "
            f"customer testimonials (3 cards), and a contact form. "
            f"Design: near-black background (#0f0f0f), bright accent color (#6366f1), "
            f"clean modern sans-serif. Feels premium and intentional — not like a template. "
            f"Every section should feel designed, not defaulted."
        )

    appforge_url = os.getenv("APPFORGE_URL", "http://localhost:5001")

    console.print(f"Generating demo for [bold]{biz_name}[/bold] ({app_type})...")
    try:
        # Create project
        r = _httpx.post(
            f"{appforge_url}/new",
            json={
                "name": f"{biz_name} Demo",
                "type": app_type,
                "client": biz_name,
                "prompt": prompt,
            },
            timeout=10,
        )
        project_id = r.json()["id"]

        # Trigger generation (streaming — wait for done)
        with _httpx.stream(
            "POST",
            f"{appforge_url}/generate/{project_id}",
            json={"message": prompt},
            timeout=120,
        ) as resp:
            for line in resp.iter_lines():
                if '"done": true' in line or '"done":true' in line:
                    break

        # Create shareable link
        share = _httpx.post(f"{appforge_url}/share/{project_id}", timeout=10).json()
        share_url = f"{appforge_url}/s/{share['token']}"

        # Save back to DB
        update_lead(lead_id, {"appforge_url": share_url})
        console.print(f"[green]Demo ready → {share_url}[/green]")

    except Exception as e:
        console.print(f"[red]AppForge error: {e}[/red]")
        console.print(
            "[dim]Make sure AppForge is running: cd ~/app-generator && python3 app.py[/dim]"
        )


@cli.command("import")
@click.argument("csv_file", type=click.Path(exists=True))
@click.option("--dry-run", is_flag=True, help="Preview without writing to DB")
def import_csv(csv_file, dry_run):
    """Import leads from a CSV file into the database."""
    import csv as _csv

    FIELD_MAP = {
        "biz_name": "biz_name",
        "business": "biz_name",
        "name": "biz_name",
        "owner_name": "owner_name",
        "owner": "owner_name",
        "biz_type": "biz_type",
        "type": "biz_type",
        "category": "biz_type",
        "address": "address",
        "city": "city",
        "state": "state",
        "zip": "zip",
        "phone": "phone",
        "email": "email",
        "email_source": "email_source",
        "email_verified": "email_verified",
        "website": "website",
        "filing_date": "filing_date",
        "appforge_url": "appforge_url",
    }

    with open(csv_file, newline="") as f:
        reader = _csv.DictReader(f)
        rows = list(reader)

    if not rows:
        console.print("[yellow]CSV is empty.[/yellow]")
        return

    imported, skipped = 0, 0
    for row in rows:
        lead = {"source": "csv_import"}
        for raw_key, val in row.items():
            key = FIELD_MAP.get(raw_key.strip().lower())
            if key and val.strip():
                lead[key] = val.strip()

        if not lead.get("biz_name"):
            skipped += 1
            continue

        if not dry_run:
            upsert_lead(lead)
        imported += 1

    if dry_run:
        console.print(
            f"[dim]Dry run: {imported} rows would import, {skipped} skipped (no biz_name).[/dim]"
        )
    else:
        console.print(
            f"[green]Imported {imported} leads[/green] ({skipped} skipped). Run [bold]de board[/bold] to refresh."
        )


@cli.command()
@click.option("--port", default=8080, help="Port to serve on (default: 8080)")
@click.option(
    "--no-regen", is_flag=True, help="Skip regenerating dashboard before serving"
)
def serve(port, no_regen):
    """Serve the lead dashboard over Tailscale at 100.124.85.89:<port>."""
    import http.server
    import socketserver
    import threading

    serve_dir = os.path.expanduser("~/.data-engine/serve")
    os.makedirs(serve_dir, exist_ok=True)

    if not no_regen:
        from dashboard.renderer import render_dashboard

        src = render_dashboard()
        import shutil

        shutil.copy(src, os.path.join(serve_dir, "index.html"))
        console.print(f"[dim]Dashboard regenerated.[/dim]")

    tailscale_ip = "100.124.85.89"
    console.print(f"\n[green]Serving lead dashboard[/green]")
    console.print(f"  Local  → [bold]http://localhost:{port}[/bold]")
    console.print(f"  Remote → [bold]http://{tailscale_ip}:{port}[/bold]")
    console.print(f"\n[dim]Ctrl+C to stop.[/dim]\n")

    os.chdir(serve_dir)
    handler = http.server.SimpleHTTPRequestHandler
    handler.log_message = lambda *a: None  # silence request logs

    with socketserver.TCPServer(("0.0.0.0", port), handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            console.print("\n[dim]Server stopped.[/dim]")


@cli.command()
@click.option("--days", default=7, help="Days back for filings")
def run(days):
    """Full weekly pipeline: fetch → enrich → export → board."""
    console.print("[bold]Running full pipeline...[/bold]\n")
    from click.testing import CliRunner

    runner = CliRunner()
    runner.invoke(fetch, ["--days", str(days)])
    runner.invoke(enrich, ["--limit", "100"])
    runner.invoke(export, ["--email-only"])
    runner.invoke(board, [])
    console.print("\n[green]Pipeline complete.[/green]")


if __name__ == "__main__":
    cli()
