"""
Foursquare Places API fetcher — replaces Yelp/Google Places.
Free tier: 1,000 calls/day, no card required.

Uses Places Search endpoint:
  GET https://api.foursquare.com/v3/places/search
  → returns name, address, phone, website, category, geocode
"""

import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

FSQ_KEY = os.getenv("FOURSQUARE_API_KEY", "")
SEARCH_URL = "https://api.foursquare.com/v3/places/search"

# Foursquare category IDs for our ICP
# Full list: https://docs.foursquare.com/data-products/docs/categories
FSQ_CATEGORIES = {
    "restaurant": "13065",  # Restaurant (parent)
    "bar": "13003",  # Bar
    "cafe": "13035",  # Coffee Shop
    "real_estate": "11100",  # Real Estate
    "property_mgmt": "11121",  # Property Management
    "contractor": "11115",  # General Contractor
    "home_services": "11108",  # Home Services
}

NE_CITIES = [
    ("Philadelphia", "PA", "Philadelphia,PA,US"),
    ("Pittsburgh", "PA", "Pittsburgh,PA,US"),
    ("Newark", "NJ", "Newark,NJ,US"),
    ("Jersey City", "NJ", "Jersey City,NJ,US"),
    ("New York City", "NY", "New York,NY,US"),
    ("Boston", "MA", "Boston,MA,US"),
    ("Hartford", "CT", "Hartford,CT,US"),
    ("Baltimore", "MD", "Baltimore,MD,US"),
    ("Providence", "RI", "Providence,RI,US"),
    ("Wilmington", "DE", "Wilmington,DE,US"),
    ("Manchester", "NH", "Manchester,NH,US"),
    ("Portland", "ME", "Portland,ME,US"),
    ("Burlington", "VT", "Burlington,VT,US"),
    ("Albany", "NY", "Albany,NY,US"),
    ("Trenton", "NJ", "Trenton,NJ,US"),
]

STATE_ABBR = {
    "PA": "PA",
    "NJ": "NJ",
    "NY": "NY",
    "MA": "MA",
    "CT": "CT",
    "MD": "MD",
    "RI": "RI",
    "VT": "VT",
    "NH": "NH",
    "ME": "ME",
    "DE": "DE",
}


def _search(near: str, category_id: str, limit: int = 50) -> list[dict]:
    try:
        r = httpx.get(
            SEARCH_URL,
            headers={
                "Authorization": FSQ_KEY,
                "Accept": "application/json",
            },
            params={
                "near": near,
                "categories": category_id,
                "limit": limit,
                "fields": "name,location,tel,website,categories",
            },
            timeout=12,
        )
        return r.json().get("results", [])
    except Exception as e:
        print(f"    Foursquare error: {e}")
        return []


def _parse_lead(place: dict, state: str, cat_label: str) -> dict | None:
    name = place.get("name", "").strip()
    if not name:
        return None

    loc = place.get("location", {})
    cats = place.get("categories", [])
    biz_type = cats[0]["name"] if cats else cat_label.replace("_", " ").title()

    return {
        "source": "foursquare",
        "biz_name": name,
        "biz_type": biz_type,
        "address": loc.get("address", ""),
        "city": loc.get("city", ""),
        "state": loc.get("region", state),
        "zip": loc.get("postcode", ""),
        "phone": place.get("tel", ""),
        "website": place.get("website", ""),
    }


def fetch_foursquare(
    categories: list[str] | None = None,
    cities: list[tuple] | None = None,
    delay: float = 0.5,
) -> list[dict]:
    """
    Fetch NE business leads from Foursquare Places API.
    Stays within 1,000 calls/day free limit automatically at default settings
    (7 categories × 15 cities = 105 calls).
    """
    if not FSQ_KEY:
        print("  Foursquare: no API key — skipping")
        return []

    categories = categories or list(FSQ_CATEGORIES.keys())
    cities = cities or NE_CITIES
    leads = []
    seen = set()

    for city_name, state, near in cities:
        for cat_key in categories:
            cat_id = FSQ_CATEGORIES[cat_key]
            print(f"  Foursquare: {cat_key} in {city_name}, {state}...")

            results = _search(near, cat_id)
            for place in results:
                lead = _parse_lead(place, state, cat_key)
                if not lead:
                    continue
                key = (lead["biz_name"].lower(), lead["state"])
                if key in seen:
                    continue
                seen.add(key)
                leads.append(lead)

            time.sleep(delay)

    return leads
