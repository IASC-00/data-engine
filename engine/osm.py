"""
OpenStreetMap Overpass API fetcher — completely free, no key needed.
Pulls businesses by type + city from OSM data for NE USA.
Returns leads in the standard Data Engine format.
"""

import time
import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# OSM amenity/office tags mapped to our ICP categories
OSM_QUERIES = {
    "restaurant": '["amenity"~"restaurant|bar|cafe|fast_food|pub"]',
    "real_estate": '["office"~"estate_agent|property_management|realtor"]',
    "contractor": '["craft"~"plumber|electrician|carpenter|painter|builder"]',
    "professional": '["office"~"lawyer|accountant|consulting|insurance|financial"]',
}

# City name → Nominatim place for Overpass area lookup
NE_CITIES = {
    "Philadelphia, PA": ("Philadelphia", "Pennsylvania"),
    "Pittsburgh, PA": ("Pittsburgh", "Pennsylvania"),
    "Newark, NJ": ("Newark", "New Jersey"),
    "Jersey City, NJ": ("Jersey City", "New Jersey"),
    "New York, NY": ("New York City", "New York"),
    "Boston, MA": ("Boston", "Massachusetts"),
    "Hartford, CT": ("Hartford", "Connecticut"),
    "Baltimore, MD": ("Baltimore", "Maryland"),
    "Providence, RI": ("Providence", "Rhode Island"),
    "Wilmington, DE": ("Wilmington", "Delaware"),
    "Manchester, NH": ("Manchester", "New Hampshire"),
    "Portland, ME": ("Portland", "Maine"),
    "Burlington, VT": ("Burlington", "Vermont"),
    "Albany, NY": ("Albany", "New York"),
    "Trenton, NJ": ("Trenton", "New Jersey"),
}

# State abbreviation lookup
STATE_ABBR = {
    "Pennsylvania": "PA",
    "New Jersey": "NJ",
    "New York": "NY",
    "Massachusetts": "MA",
    "Connecticut": "CT",
    "Maryland": "MD",
    "Rhode Island": "RI",
    "Vermont": "VT",
    "New Hampshire": "NH",
    "Maine": "ME",
    "Delaware": "DE",
}


def _get_nominatim_id(city: str, state: str) -> int | None:
    """Use Nominatim to get the OSM relation ID for a city."""
    try:
        r = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={
                "q": f"{city}, {state}",
                "format": "json",
                "limit": 1,
                "featuretype": "city",
            },
            headers={"User-Agent": "DataEngine/1.0 (contact@iswain.dev)"},
            timeout=10,
        )
        results = r.json()
        if results:
            return int(results[0]["osm_id"])
    except Exception:
        pass
    return None


def _overpass_query(
    bbox: tuple, tag_filter: str, timeout: int = 60, retries: int = 3
) -> list[dict]:
    """
    Run an Overpass query within a bounding box.
    bbox: (south, west, north, east) in decimal degrees.
    """
    south, west, north, east = bbox
    query = f"""
[out:json][timeout:{timeout}];
(
  node{tag_filter}({south},{west},{north},{east});
  way{tag_filter}({south},{west},{north},{east});
);
out body;
"""
    for attempt in range(retries):
        try:
            r = httpx.post(OVERPASS_URL, data={"data": query}, timeout=timeout + 15)
            r.raise_for_status()
            return r.json().get("elements", [])
        except Exception as e:
            err = str(e)
            if attempt < retries - 1 and (
                "504" in err or "429" in err or "timeout" in err.lower()
            ):
                wait = 15 * (attempt + 1)
                print(f"  Overpass retry {attempt + 1}/{retries} (waiting {wait}s)...")
                time.sleep(wait)
            else:
                print(f"  Overpass error: {e}")
                return []
    return []


def _get_city_bbox(city: str, state: str) -> tuple | None:
    """Get approximate bounding box for a city via Nominatim."""
    try:
        r = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": f"{city}, {state}, USA", "format": "json", "limit": 1},
            headers={"User-Agent": "DataEngine/1.0 (contact@iswain.dev)"},
            timeout=10,
        )
        results = r.json()
        if results and "boundingbox" in results[0]:
            bb = results[0]["boundingbox"]
            # bb = [south, north, west, east]
            return (float(bb[0]), float(bb[2]), float(bb[1]), float(bb[3]))
    except Exception:
        pass
    return None


def _element_to_lead(el: dict, state: str, category_label: str) -> dict | None:
    """Convert an OSM element to a lead dict."""
    tags = el.get("tags", {})
    name = tags.get("name", "").strip()
    if not name:
        return None

    phone = tags.get("phone", "") or tags.get("contact:phone", "")
    website = (
        tags.get("website", "")
        or tags.get("contact:website", "")
        or tags.get("url", "")
    )
    email = tags.get("email", "") or tags.get("contact:email", "")
    address = " ".join(
        filter(
            None,
            [
                tags.get("addr:housenumber", ""),
                tags.get("addr:street", ""),
            ],
        )
    )
    city = tags.get("addr:city", "")
    zip_code = tags.get("addr:postcode", "")

    # Determine biz_type from OSM tags
    biz_type = (
        (
            tags.get("amenity")
            or tags.get("office")
            or tags.get("craft")
            or category_label
        )
        .replace("_", " ")
        .title()
    )

    return {
        "source": "osm",
        "biz_name": name,
        "biz_type": biz_type,
        "address": address,
        "city": city,
        "state": state,
        "zip": zip_code,
        "phone": phone,
        "website": website,
        "email": email if email else None,
    }


def fetch_osm(
    categories: list[str] | None = None,
    cities: dict | None = None,
    delay: float = 2.0,
) -> list[dict]:
    """
    Fetch NE business leads from OpenStreetMap via Overpass API.
    categories: subset of OSM_QUERIES keys (default: all)
    cities: subset of NE_CITIES dict (default: all)
    delay: seconds between requests (Overpass rate limit is ~1 req/2s)
    """
    categories = categories or list(OSM_QUERIES.keys())
    cities = cities or NE_CITIES
    leads = []
    seen = set()

    for city_label, (city_name, state_name) in cities.items():
        state_abbr = STATE_ABBR.get(state_name, state_name[:2].upper())

        print(f"  OSM: {city_label}...")
        bbox = _get_city_bbox(city_name, state_name)
        if not bbox:
            print(f"    (could not get bbox for {city_label})")
            continue
        time.sleep(1)

        for cat_key in categories:
            tag_filter = OSM_QUERIES[cat_key]
            elements = _overpass_query(bbox, tag_filter)

            for el in elements:
                lead = _element_to_lead(el, state_abbr, cat_key)
                if lead:
                    key = (lead["biz_name"].lower(), state_abbr)
                    if key not in seen:
                        seen.add(key)
                        leads.append(lead)

            time.sleep(delay)

    return leads
