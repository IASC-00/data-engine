#!/usr/bin/env python3
"""
Data Engine MCP Server

Exposes lead pipeline data to Claude Code via MCP tools.
Run: python3 mcp_server.py (stdio transport, local only)

Register in ~/.claude/settings.json:
  "mcpServers": {
    "data_engine": {
      "command": "python3",
      "args": ["/home/iswai/data-engine/mcp_server.py"]
    }
  }
"""

import json
import sqlite3
import subprocess
import sys
import os
from contextlib import asynccontextmanager
from typing import Optional

from mcp.server.fastmcp import FastMCP, Context
from pydantic import BaseModel, Field, ConfigDict

DB_PATH = os.path.expanduser("~/.data-engine/leads.db")
DE_DIR = os.path.expanduser("~/data-engine")


# ── DB helper ─────────────────────────────────────────────────────────────────


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _run_de(*args: str, timeout: int = 60) -> str:
    """Run a data-engine CLI command with the correct working directory."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, '.'); from cli import cli; from click.testing import CliRunner; "
            f"r=CliRunner(); res=r.invoke(cli, {list(args)!r}); print(res.output); "
            f"sys.exit(res.exit_code or 0)",
        ],
        cwd=DE_DIR,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    output = result.stdout or result.stderr or ""
    return output.strip()


# ── MCP server ────────────────────────────────────────────────────────────────

mcp = FastMCP("data_engine_mcp")


# ── Tool 1: de_stats ──────────────────────────────────────────────────────────


@mcp.tool(
    name="de_stats",
    annotations={
        "title": "Data Engine Stats",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def de_stats() -> str:
    """Return pipeline statistics from the Data Engine lead database.

    Queries the leads.db SQLite database directly for real-time counts.
    Returns total leads, email coverage, enrichment status, outreach status,
    top states, top business types, and email source breakdown.

    Returns:
        str: JSON object with the following schema:
        {
            "total_leads": int,
            "with_email": int,
            "email_pct": float,
            "enriched": int,
            "outreach_sent": int,
            "appforge_demos": int,
            "by_state": [{"state": str, "count": int}, ...],  # top 10
            "by_biz_type": [{"biz_type": str, "count": int}, ...],  # top 10
            "email_sources": [{"source": str, "count": int}, ...]
        }

    Error response: "Error: <message>"
    """
    try:
        conn = _get_conn()
        cur = conn.cursor()

        total = cur.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        with_email = cur.execute(
            "SELECT COUNT(*) FROM leads WHERE email IS NOT NULL AND email != ''"
        ).fetchone()[0]
        enriched = cur.execute(
            "SELECT COUNT(*) FROM leads WHERE enriched = 1"
        ).fetchone()[0]
        outreach_sent = cur.execute(
            "SELECT COUNT(*) FROM leads WHERE outreach_sent = 1"
        ).fetchone()[0]
        appforge_demos = cur.execute(
            "SELECT COUNT(*) FROM leads WHERE appforge_url IS NOT NULL AND appforge_url != ''"
        ).fetchone()[0]

        by_state = [
            {"state": r[0], "count": r[1]}
            for r in cur.execute(
                "SELECT state, COUNT(*) c FROM leads GROUP BY state ORDER BY c DESC LIMIT 10"
            ).fetchall()
        ]
        by_biz_type = [
            {"biz_type": r[0], "count": r[1]}
            for r in cur.execute(
                "SELECT biz_type, COUNT(*) c FROM leads GROUP BY biz_type ORDER BY c DESC LIMIT 10"
            ).fetchall()
        ]
        email_sources = [
            {"source": r[0] or "unknown", "count": r[1]}
            for r in cur.execute(
                "SELECT email_source, COUNT(*) c FROM leads "
                "WHERE email IS NOT NULL AND email != '' "
                "GROUP BY email_source ORDER BY c DESC"
            ).fetchall()
        ]

        conn.close()
        return json.dumps(
            {
                "total_leads": total,
                "with_email": with_email,
                "email_pct": round(with_email / total * 100, 1) if total else 0,
                "enriched": enriched,
                "outreach_sent": outreach_sent,
                "appforge_demos": appforge_demos,
                "by_state": by_state,
                "by_biz_type": by_biz_type,
                "email_sources": email_sources,
            },
            indent=2,
        )
    except Exception as e:
        return f"Error: {e}"


# ── Tool 2: de_board_data ─────────────────────────────────────────────────────


class BoardDataInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    limit: Optional[int] = Field(
        default=25,
        description="Max leads to return (1–200)",
        ge=1,
        le=200,
    )
    offset: Optional[int] = Field(
        default=0,
        description="Pagination offset",
        ge=0,
    )
    has_email: Optional[bool] = Field(
        default=None,
        description="Filter to leads with (True) or without (False) email. Omit for all.",
    )
    has_phone: Optional[bool] = Field(
        default=None,
        description="Filter to leads with (True) or without (False) phone. Omit for all.",
    )
    biz_type: Optional[str] = Field(
        default=None,
        description="Filter by business type (e.g. 'Restaurant', 'Estate Agent'). Case-insensitive.",
    )
    state: Optional[str] = Field(
        default=None,
        description="Filter by 2-letter state code (e.g. 'NY', 'PA').",
    )
    outreach_sent: Optional[bool] = Field(
        default=None,
        description="True = already contacted, False = not yet contacted. Omit for all.",
    )
    has_appforge_url: Optional[bool] = Field(
        default=None,
        description="Filter to leads that have (True) or lack (False) an AppForge demo URL.",
    )
    search: Optional[str] = Field(
        default=None,
        description="Free-text search across biz_name, city, and owner_name.",
    )


@mcp.tool(
    name="de_board_data",
    annotations={
        "title": "Query Lead Board",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def de_board_data(params: BoardDataInput) -> str:
    """Query leads from the Data Engine database with optional filters.

    Supports pagination and filtering by email, phone, business type, state,
    outreach status, and AppForge demo status. Use de_stats first to understand
    what's in the pipeline before querying.

    Args:
        params (BoardDataInput): Filter/pagination options.

    Returns:
        str: JSON with schema:
        {
            "total_matching": int,
            "count": int,
            "offset": int,
            "has_more": bool,
            "leads": [
                {
                    "id": int,
                    "biz_name": str,
                    "biz_type": str,
                    "city": str,
                    "state": str,
                    "phone": str | null,
                    "email": str | null,
                    "website": str | null,
                    "appforge_url": str | null,
                    "outreach_sent": bool,
                    "enriched": bool
                },
                ...
            ]
        }
    """
    try:
        conn = _get_conn()
        cur = conn.cursor()

        conditions: list[str] = []
        values: list = []

        if params.has_email is True:
            conditions.append("email IS NOT NULL AND email != ''")
        elif params.has_email is False:
            conditions.append("(email IS NULL OR email = '')")

        if params.has_phone is True:
            conditions.append("phone IS NOT NULL AND phone != ''")
        elif params.has_phone is False:
            conditions.append("(phone IS NULL OR phone = '')")

        if params.biz_type:
            conditions.append("LOWER(biz_type) = LOWER(?)")
            values.append(params.biz_type)

        if params.state:
            conditions.append("UPPER(state) = UPPER(?)")
            values.append(params.state)

        if params.outreach_sent is True:
            conditions.append("outreach_sent = 1")
        elif params.outreach_sent is False:
            conditions.append("(outreach_sent = 0 OR outreach_sent IS NULL)")

        if params.has_appforge_url is True:
            conditions.append("appforge_url IS NOT NULL AND appforge_url != ''")
        elif params.has_appforge_url is False:
            conditions.append("(appforge_url IS NULL OR appforge_url = '')")

        if params.search:
            conditions.append(
                "(LOWER(biz_name) LIKE LOWER(?) OR LOWER(city) LIKE LOWER(?) OR LOWER(owner_name) LIKE LOWER(?))"
            )
            q = f"%{params.search}%"
            values.extend([q, q, q])

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        total = cur.execute(f"SELECT COUNT(*) FROM leads {where}", values).fetchone()[0]

        rows = cur.execute(
            f"""SELECT id, biz_name, biz_type, city, state, phone, email,
                       website, appforge_url, outreach_sent, enriched
                FROM leads {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?""",
            values + [params.limit, params.offset],
        ).fetchall()

        conn.close()

        leads = [
            {
                "id": r["id"],
                "biz_name": r["biz_name"],
                "biz_type": r["biz_type"],
                "city": r["city"],
                "state": r["state"],
                "phone": r["phone"] or None,
                "email": r["email"] or None,
                "website": r["website"] or None,
                "appforge_url": r["appforge_url"] or None,
                "outreach_sent": bool(r["outreach_sent"]),
                "enriched": bool(r["enriched"]),
            }
            for r in rows
        ]

        return json.dumps(
            {
                "total_matching": total,
                "count": len(leads),
                "offset": params.offset,
                "has_more": total > params.offset + len(leads),
                "next_offset": params.offset + len(leads)
                if total > params.offset + len(leads)
                else None,
                "leads": leads,
            },
            indent=2,
        )
    except Exception as e:
        return f"Error: {e}"


# ── Tool 3: de_enrich ─────────────────────────────────────────────────────────


class EnrichInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: int = Field(
        ...,
        description="The integer ID of the lead to enrich. Get IDs from de_board_data.",
        ge=1,
    )


@mcp.tool(
    name="de_enrich",
    annotations={
        "title": "Enrich a Lead",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def de_enrich(params: EnrichInput, ctx: Context) -> str:
    """Attempt to find and verify an email address for a specific lead.

    Runs the Data Engine enrichment pipeline for a single lead: scrapes website,
    checks WHOIS, guesses common email patterns, and verifies via DNS/SMTP.
    Updates the lead's email field in the database if found.

    Args:
        params (EnrichInput): lead_id (int) — the lead to enrich.

    Returns:
        str: JSON with schema:
        {
            "lead_id": int,
            "biz_name": str,
            "email_found": bool,
            "email": str | null,
            "email_source": str | null,
            "output": str   # raw CLI output for debugging
        }

    Note: Enrichment calls external APIs (Hunter.io, Apollo.io free tiers).
    May take 10–30 seconds per lead.
    """
    try:
        await ctx.report_progress(0.1, f"Looking up lead {params.lead_id}...")

        conn = _get_conn()
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, biz_name, email FROM leads WHERE id = ?", [params.lead_id]
        ).fetchone()

        if not row:
            conn.close()
            return f"Error: Lead {params.lead_id} not found. Use de_board_data to find valid IDs."

        biz_name = row["biz_name"]
        existing_email = row["email"]
        conn.close()

        if existing_email:
            return json.dumps(
                {
                    "lead_id": params.lead_id,
                    "biz_name": biz_name,
                    "email_found": True,
                    "email": existing_email,
                    "email_source": "already_enriched",
                    "output": f"Lead already has email: {existing_email}",
                },
                indent=2,
            )

        await ctx.report_progress(0.3, f"Enriching {biz_name}...")

        output = _run_de("enrich", "--lead-id", str(params.lead_id), timeout=90)

        await ctx.report_progress(0.9, "Reading result...")

        conn2 = _get_conn()
        updated = conn2.execute(
            "SELECT email, email_source FROM leads WHERE id = ?", [params.lead_id]
        ).fetchone()
        conn2.close()

        email = updated["email"] if updated else None
        source = updated["email_source"] if updated else None

        return json.dumps(
            {
                "lead_id": params.lead_id,
                "biz_name": biz_name,
                "email_found": bool(email),
                "email": email or None,
                "email_source": source or None,
                "output": output,
            },
            indent=2,
        )

    except subprocess.TimeoutExpired:
        return f"Error: Enrichment timed out for lead {params.lead_id}. The lead may require manual lookup."
    except Exception as e:
        return f"Error: {e}"


# ── Tool 4: de_appforge ───────────────────────────────────────────────────────


class AppForgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: int = Field(
        ...,
        description="The integer ID of the lead to generate a personalized AppForge demo for. Must have a biz_name and biz_type. Get IDs from de_board_data.",
        ge=1,
    )


@mcp.tool(
    name="de_appforge",
    annotations={
        "title": "Generate AppForge Demo for Lead",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def de_appforge(params: AppForgeInput, ctx: Context) -> str:
    """Generate a personalized AppForge demo web app for a specific lead.

    Builds a custom demo app using the lead's business name, city, and type.
    The generated app URL is saved back to the lead's appforge_url field
    and can be included in cold outreach emails.

    Args:
        params (AppForgeInput): lead_id (int) — the lead to generate a demo for.

    Returns:
        str: JSON with schema:
        {
            "lead_id": int,
            "biz_name": str,
            "biz_type": str,
            "city": str,
            "appforge_url": str | null,
            "output": str   # raw CLI output
        }

    Typical use: query de_board_data with has_email=True, has_appforge_url=False
    to find leads ready for personalized demos, then call de_appforge for each.
    """
    try:
        await ctx.report_progress(0.1, f"Looking up lead {params.lead_id}...")

        conn = _get_conn()
        cur = conn.cursor()
        row = cur.execute(
            "SELECT id, biz_name, biz_type, city, state, appforge_url FROM leads WHERE id = ?",
            [params.lead_id],
        ).fetchone()
        conn.close()

        if not row:
            return f"Error: Lead {params.lead_id} not found. Use de_board_data to find valid IDs."

        biz_name = row["biz_name"]
        biz_type = row["biz_type"]
        city = row["city"]
        existing_url = row["appforge_url"]

        if existing_url:
            return json.dumps(
                {
                    "lead_id": params.lead_id,
                    "biz_name": biz_name,
                    "biz_type": biz_type,
                    "city": city,
                    "appforge_url": existing_url,
                    "output": f"Demo already generated: {existing_url}",
                },
                indent=2,
            )

        await ctx.report_progress(
            0.3, f"Generating demo for {biz_name} ({biz_type}, {city})..."
        )

        output = _run_de("appforge", str(params.lead_id), timeout=120)

        await ctx.report_progress(0.9, "Reading result...")

        conn2 = _get_conn()
        updated = conn2.execute(
            "SELECT appforge_url FROM leads WHERE id = ?", [params.lead_id]
        ).fetchone()
        conn2.close()

        url = updated["appforge_url"] if updated else None

        return json.dumps(
            {
                "lead_id": params.lead_id,
                "biz_name": biz_name,
                "biz_type": biz_type,
                "city": city,
                "appforge_url": url or None,
                "output": output,
            },
            indent=2,
        )

    except subprocess.TimeoutExpired:
        return f"Error: AppForge generation timed out for lead {params.lead_id}."
    except Exception as e:
        return f"Error: {e}"


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()  # stdio transport — Claude Code connects via subprocess
