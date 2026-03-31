"""
Yellow Pages scraper — no API key needed.
Pulls business listings for NE cities + target categories.
Returns leads in the same format as fetcher.py sources.
"""
import time
import re
import httpx
from bs4 import BeautifulSoup

# Target categories matching our ICP
YP_CATEGORIES = [
    'restaurants',
    'real-estate-agents',
    'property-management',
    'bars',
    'coffee-shops',
    'caterers',
    'pizza',
    'contractors',
    'plumbers',
    'electricians',
    'landscaping',
    'cleaning-service',
]

# NE cities to scrape (highest density of target businesses)
YP_CITIES = [
    'Philadelphia, PA',
    'Pittsburgh, PA',
    'Allentown, PA',
    'Newark, NJ',
    'Jersey City, NJ',
    'Hoboken, NJ',
    'New York, NY',
    'Brooklyn, NY',
    'Buffalo, NY',
    'Boston, MA',
    'Worcester, MA',
    'Hartford, CT',
    'New Haven, CT',
    'Baltimore, MD',
    'Providence, RI',
    'Wilmington, DE',
    'Manchester, NH',
    'Portland, ME',
]

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}


def _state_from_city(city_str: str) -> str:
    parts = city_str.split(', ')
    return parts[-1].strip() if len(parts) > 1 else ''


def _parse_results(html: str, state: str) -> list[dict]:
    """Parse Yellow Pages search results HTML into lead dicts."""
    soup = BeautifulSoup(html, 'html.parser')
    leads = []

    for result in soup.select('div.result, div.v-card'):
        try:
            # Business name
            name_el = (
                result.select_one('a.business-name') or
                result.select_one('h2.n a') or
                result.select_one('.business-name')
            )
            if not name_el:
                continue
            biz_name = name_el.get_text(strip=True)
            if not biz_name:
                continue

            # Phone
            phone_el = (
                result.select_one('.phones.phone.primary') or
                result.select_one('div.phones') or
                result.select_one('.phone')
            )
            phone = phone_el.get_text(strip=True) if phone_el else ''

            # Address
            street_el = result.select_one('.street-address')
            locality_el = result.select_one('.locality')
            address = street_el.get_text(strip=True) if street_el else ''
            locality_text = locality_el.get_text(strip=True) if locality_el else ''

            # Parse city/state/zip from locality (e.g. "Philadelphia, PA 19103")
            city, zip_code = '', ''
            if locality_text:
                m = re.match(r'^(.+?),\s*[A-Z]{2}\s*(\d{5})?', locality_text)
                if m:
                    city = m.group(1).strip()
                    zip_code = (m.group(2) or '').strip()
                else:
                    city = locality_text

            # Website
            website_el = (
                result.select_one('a.track-visit-website') or
                result.select_one('a[href*="http"]:not([href*="yellowpages"])')
            )
            website = ''
            if website_el:
                href = website_el.get('href', '')
                # YP wraps outbound links — extract real URL if present
                if 'yellowpages.com' not in href:
                    website = href
                else:
                    # Try to pull from data attributes
                    website = website_el.get('data-url', '') or website_el.get('data-href', '')

            # Category
            cat_els = result.select('.categories a')
            category = ', '.join(el.get_text(strip=True) for el in cat_els) if cat_els else ''

            leads.append({
                'source': 'yellowpages',
                'biz_name': biz_name,
                'biz_type': category,
                'address': address,
                'city': city or '',
                'state': state,
                'zip': zip_code,
                'phone': phone,
                'website': website,
            })
        except Exception:
            continue

    return leads


def fetch_yellowpages(
    categories: list[str] | None = None,
    cities: list[str] | None = None,
    pages_per_combo: int = 2,
    delay: float = 1.5,
) -> list[dict]:
    """
    Scrape Yellow Pages for target categories + NE cities.
    pages_per_combo: how many result pages to fetch per city+category combo (default 2 = ~60 results).
    delay: seconds between requests (be polite).
    """
    categories = categories or YP_CATEGORIES
    cities = cities or YP_CITIES
    leads = []
    seen = set()

    for city in cities:
        state = _state_from_city(city)
        for cat in categories:
            for page in range(1, pages_per_combo + 1):
                url = 'https://www.yellowpages.com/search'
                params = {
                    'search_terms': cat.replace('-', ' '),
                    'geo_location_terms': city,
                    'page': page,
                }
                try:
                    r = httpx.get(url, params=params, headers=HEADERS, timeout=12, follow_redirects=True)
                    if r.status_code == 200:
                        page_leads = _parse_results(r.text, state)
                        for lead in page_leads:
                            key = (lead['biz_name'].lower(), state)
                            if key not in seen:
                                seen.add(key)
                                leads.append(lead)
                        # Stop paging if fewer than 10 results (last page)
                        if len(page_leads) < 10:
                            break
                    elif r.status_code == 429:
                        print(f'  YP rate limit hit — sleeping 30s...')
                        time.sleep(30)
                    else:
                        break
                except Exception as e:
                    print(f'  YP fetch failed {city}/{cat}: {e}')
                    break
                time.sleep(delay)

    return leads
