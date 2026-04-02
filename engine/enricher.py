"""
Email enrichment chain for Data Engine leads.

Chain (in order, stops when email found):
  1. Firecrawl — scrape business website (handles JS, anti-bot, redirects)
  2. BeautifulSoup fallback — basic scrape if Firecrawl unavailable
  3. WHOIS registrant email lookup
  4. Guess common patterns (info@, contact@, firstname@) + DNS MX verify
  5. Hunter.io API (25/month free)
  6. Apollo.io API (50/month free)

Cross-reference: uses Google Places API to find official website
when only a Yelp URL is available.
"""

import ipaddress
import os
import re
import time
import subprocess
import socket
import urllib.parse
import httpx
import dns.resolver
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

HUNTER_KEY = os.getenv("HUNTER_API_KEY", "")
APOLLO_KEY = os.getenv("APOLLO_API_KEY", "")
GOOGLE_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")


# ── Step 0: Resolve real website via Google Places ────────────────────────────


def resolve_website(biz_name: str, city: str, state: str) -> str:
    """Use Google Places text search to find the official website."""
    if not GOOGLE_KEY:
        return ""
    try:
        r = httpx.get(
            "https://maps.googleapis.com/maps/api/place/findplacefromtext/json",
            params={
                "input": f"{biz_name} {city} {state}",
                "inputtype": "textquery",
                "fields": "website,name",
                "key": GOOGLE_KEY,
            },
            timeout=8,
        )
        candidates = r.json().get("candidates", [])
        if candidates:
            return candidates[0].get("website", "")
    except Exception:
        pass
    return ""


# ── Step 1a: Firecrawl scrape (primary — handles JS, anti-bot, redirects) ────

FIRECRAWL_BIN = os.getenv("FIRECRAWL_BIN", "firecrawl")
FIRECRAWL_KEY = os.getenv("FIRECRAWL_API_KEY", "")


def _safe_url(url: str) -> bool:
    """Reject anything that isn't a plain http/https URL to a public hostname.
    Blocks: IPv4 private/loopback, IPv6 loopback, decimal/hex IP tricks, AWS metadata.
    """
    if not url or not url.startswith(("http://", "https://")):
        return False
    lower = url.lower()
    # Block private IPv4 ranges using proper ipaddress module
    # 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 127.0.0.0/8, 169.254.0.0/16
    private_ranges = [
        ipaddress.ip_network("10.0.0.0/8", strict=False),
        ipaddress.ip_network("172.16.0.0/12", strict=False),
        ipaddress.ip_network("192.168.0.0/16", strict=False),
        ipaddress.ip_network("127.0.0.0/8", strict=False),
        ipaddress.ip_network("169.254.0.0/16", strict=False),
    ]
    # Extract host from URL and check if it's a private IP
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname:
            try:
                host_ip = ipaddress.ip_address(parsed.hostname)
                for network in private_ranges:
                    if host_ip in network:
                        return False
            except ValueError:
                # Not an IP address - could be domain, continue with DNS check
                pass
    except Exception:
        pass
    # IPv6 loopback and link-local
    blocked_ipv6 = ("::1", "[::1]", "::ffff:", "fe80:", "[fe80:")
    if any(b in lower for b in blocked_ipv6):
        return False
    # Block decimal/octal/hex IP notation (e.g. http://0x7f000001, http://2130706433)
    if re.search(r"https?://0x[0-9a-f]+", lower):
        return False
    if re.search(r"https?://\d{7,10}[/:$]", lower):  # decimal IP like 2130706433
        return False

    # DNS rebinding protection: resolve hostname now and validate the real IP.
    # A malicious domain can pass all string checks above, then resolve to 127.0.0.1
    # at request time. Resolving here and rejecting private/loopback IPs closes that gap.
    try:
        hostname = urllib.parse.urlparse(url).hostname
        if not hostname:
            return False
        for info in socket.getaddrinfo(hostname, None):
            addr = ipaddress.ip_address(info[4][0])
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_reserved
            ):
                return False
    except (socket.gaierror, OSError, ValueError):
        # Unresolvable hostname — fail safe
        return False

    return True


def firecrawl_email(url: str) -> str:
    """Use Firecrawl CLI to scrape website — handles JS-rendered sites and anti-bot."""
    if not url or "yelp.com" in url or not FIRECRAWL_KEY or not _safe_url(url):
        return ""
    try:
        env = os.environ.copy()
        env["FIRECRAWL_API_KEY"] = FIRECRAWL_KEY
        result = subprocess.run(
            [FIRECRAWL_BIN, "scrape", url],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
        text = result.stdout
        # Find mailto: links in markdown output
        for match in re.findall(r"\[.*?\]\(mailto:([^)]+)\)", text):
            email = match.split("?")[0].strip()
            if _valid_email(email) and not _is_noise_email(email):
                return email
        # Find email patterns in text
        emails = re.findall(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
        for email in emails:
            if _valid_email(email) and not _is_noise_email(email):
                return email
    except Exception:
        pass
    return ""


# ── Step 1b: BeautifulSoup fallback scrape ────────────────────────────────────


def scrape_website_email(url: str) -> str:
    """Fallback scraper using httpx + BeautifulSoup (basic sites only)."""
    if not url or "yelp.com" in url or not _safe_url(url):
        return ""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; DataEngine/1.0)"}
        pages = [url, url.rstrip("/") + "/contact", url.rstrip("/") + "/contact-us"]
        for page in pages:
            try:
                r = httpx.get(page, headers=headers, timeout=8, follow_redirects=True)
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if href.startswith("mailto:"):
                        email = href[7:].split("?")[0].strip()
                        if _valid_email(email):
                            return email
                emails = re.findall(
                    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", r.text
                )
                for email in emails:
                    if _valid_email(email) and not _is_noise_email(email):
                        return email
            except Exception:
                continue
    except Exception:
        pass
    return ""


# ── Step 2: WHOIS registrant email ───────────────────────────────────────────


def whois_email(domain: str) -> str:
    """Look up WHOIS registrant email. Many small biz skip privacy protection."""
    if not domain:
        return ""
    try:
        import whois

        w = whois.whois(domain)
        emails = (
            w.emails if isinstance(w.emails, list) else ([w.emails] if w.emails else [])
        )
        for email in emails:
            if email and _valid_email(email) and not _is_noise_email(email):
                return email
    except Exception:
        pass
    return ""


# ── Step 3: Guess + DNS MX verify ────────────────────────────────────────────


def guess_and_verify(domain: str, owner_name: str = "") -> tuple[str, bool]:
    """
    Guess common email patterns and verify via DNS MX lookup.
    Returns (email, verified) — verified=True means MX records exist for domain.
    """
    if not domain:
        return "", False

    # Check domain has MX records at all (if not, skip guessing)
    mx_exists = _has_mx(domain)
    if not mx_exists:
        return "", False

    guesses = ["info", "contact", "hello", "admin"]
    if owner_name:
        first = owner_name.split()[0].lower() if owner_name.split() else ""
        if first:
            guesses.insert(0, first)

    # Return first guess — MX verified means domain accepts mail
    for prefix in guesses:
        email = f"{prefix}@{domain}"
        if _valid_email(email):
            return email, True

    return "", False


def _has_mx(domain: str) -> bool:
    try:
        dns.resolver.resolve(domain, "MX")
        return True
    except Exception:
        return False


# ── Step 4: Hunter.io ─────────────────────────────────────────────────────────


def hunter_email(domain: str) -> str:
    if not HUNTER_KEY or not domain:
        return ""
    try:
        r = httpx.get(
            "https://api.hunter.io/v2/domain-search",
            params={"domain": domain, "api_key": HUNTER_KEY, "limit": 3},
            timeout=8,
        )
        emails = r.json().get("data", {}).get("emails", [])
        if emails:
            return emails[0].get("value", "")
    except Exception:
        pass
    return ""


# ── Step 5: Apollo.io ─────────────────────────────────────────────────────────


def apollo_email(biz_name: str, domain: str) -> str:
    """Two-step: Search (free, no credits) → Enrich (1 credit) to reveal email."""
    if not APOLLO_KEY or not domain:
        return ""
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "x-api-key": APOLLO_KEY,
    }
    try:
        # Step 1: Search by domain — free, no credits consumed
        r = httpx.post(
            "https://api.apollo.io/api/v1/mixed_people/api_search",
            headers=headers,
            json={
                "q_organization_domains_list": [domain],
                "person_titles": [
                    "owner",
                    "founder",
                    "president",
                    "manager",
                    "director",
                ],
                "person_seniorities": ["owner", "founder", "c_suite", "partner"],
                "per_page": 1,
            },
            timeout=10,
        )
        people = r.json().get("people", [])
        if not people:
            return ""
        person_id = people[0].get("id", "")
        if not person_id:
            return ""

        # Step 2: Enrich to get actual email — costs 1 credit
        r2 = httpx.post(
            "https://api.apollo.io/api/v1/people/bulk_match",
            headers=headers,
            json={"details": [{"id": person_id}]},
            timeout=10,
        )
        matches = r2.json().get("matches", [])
        if matches:
            return matches[0].get("email", "")
    except Exception:
        pass
    return ""


# ── Main enrichment entry point ───────────────────────────────────────────────


def enrich_lead(lead: dict) -> dict:
    """
    Run the full enrichment chain on a lead.
    Returns updated lead dict with email, email_source, email_verified fields.
    """
    result = dict(lead)
    result["enriched"] = 1

    # Already has email — skip
    if lead.get("email"):
        return result

    website = lead.get("website", "") or ""
    biz_name = lead.get("biz_name", "")
    city = lead.get("city", "")
    state = lead.get("state", "")
    owner = lead.get("owner_name", "")

    # Step 0: resolve real website if we only have a Yelp URL or nothing
    if not website or "yelp.com" in website:
        website = resolve_website(biz_name, city, state)
        if website:
            result["website"] = website

    domain = _extract_domain(website)

    # Step 1a: Firecrawl (handles JS, anti-bot)
    email = firecrawl_email(website)
    if email:
        result["email"] = email
        result["email_source"] = "firecrawl"
        result["email_verified"] = 1
        return result

    # Step 1b: basic scrape fallback
    email = scrape_website_email(website)
    if email:
        result["email"] = email
        result["email_source"] = "scrape"
        result["email_verified"] = 1
        return result

    # Step 2: WHOIS
    email = whois_email(domain)
    if email:
        result["email"] = email
        result["email_source"] = "whois"
        result["email_verified"] = 1
        return result

    # Step 3: guess + MX verify
    email, verified = guess_and_verify(domain, owner)
    if email:
        result["email"] = email
        result["email_source"] = "guess"
        result["email_verified"] = int(verified)
        return result

    # Step 4: Hunter.io (rate-limited — use sparingly)
    email = hunter_email(domain)
    if email:
        result["email"] = email
        result["email_source"] = "hunter"
        result["email_verified"] = 1
        return result

    # Step 5: Apollo.io
    email = apollo_email(biz_name, domain)
    if email:
        result["email"] = email
        result["email_source"] = "apollo"
        result["email_verified"] = 1
        return result

    return result


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_domain(url: str) -> str:
    if not url:
        return ""
    url = re.sub(r"^https?://", "", url).split("/")[0].split("?")[0]
    return url.replace("www.", "").strip()


def _valid_email(email: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", email))


def _is_noise_email(email: str) -> bool:
    """Filter out placeholder / privacy emails."""
    noise = [
        "example.com",
        "domain.com",
        "email.com",
        "whoisprivacy",
        "privacy",
        "protect",
        "proxy",
        "noreply",
        "no-reply",
        "donotreply",
        "sav.com",
        "godaddy",
        "namecheap",
        "cloudflare",
    ]
    email_lower = email.lower()
    return any(n in email_lower for n in noise)
