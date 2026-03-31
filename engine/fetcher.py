"""
Lead fetcher — pulls from Google Places API + OpenStreetMap.
Cross-references both sources by business name + state for richer records.
"""

import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


def cross_reference(primary: list[dict], secondary: list[dict]) -> list[dict]:
    """
    Merge two lead lists. When names match (name + state), merge secondary
    fields into primary (fills in missing phone/website/biz_type).
    Non-matching secondary leads are appended as-is.
    """
    sec_index = {}
    for lead in secondary:
        key = (_normalize(lead["biz_name"]), lead.get("state", ""))
        sec_index[key] = lead

    merged = []
    for lead in primary:
        key = (_normalize(lead["biz_name"]), lead.get("state", ""))
        match = sec_index.get(key)
        if match:
            combined = {**lead}
            combined["phone"] = combined.get("phone") or match.get("phone", "")
            combined["website"] = combined.get("website") or match.get("website", "")
            combined["biz_type"] = combined.get("biz_type") or match.get("biz_type", "")
            merged.append(combined)
        else:
            merged.append(lead)

    # Append secondary-only leads
    primary_keys = {(_normalize(l["biz_name"]), l.get("state", "")) for l in primary}
    for lead in secondary:
        key = (_normalize(lead["biz_name"]), lead.get("state", ""))
        if key not in primary_keys:
            merged.append(lead)

    return merged


def _normalize(name: str) -> str:
    import re

    name = name.lower().strip()
    name = re.sub(r"\b(llc|inc|corp|ltd|co|company|the)\b", "", name)
    name = re.sub(r"[^a-z0-9]", "", name)
    return name


def fetch_all(days_back=7) -> list[dict]:
    """Main entry point — fetch from OpenStreetMap (free, no key required)."""
    from engine.osm import fetch_osm

    print("Fetching OpenStreetMap businesses...")
    leads = fetch_osm()
    print(f"  → {len(leads)} leads")

    return leads
