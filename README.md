# Data Engine

NE USA lead generation pipeline for self-employed business owners. Pulls business data from multiple free sources, cross-references, and enriches with email addresses using a zero-cost chain.

**Target:** 100 verified emails/week at $0 ongoing cost.

---

## What it does

1. **Fetches** business leads from OpenStreetMap (free, no key) across 15 NE cities
2. **Enriches** emails via a 5-step chain (website scrape → WHOIS → DNS guess+verify → Hunter.io → Apollo.io)
3. **Exports** to CSV for outreach
4. **Generates** personalized demos via AppForge integration

**Coverage:** PA, NJ, NY, MA, CT, MD, RI, VT, NH, ME, DE
**Categories:** Restaurants, real estate, contractors, professional services

---

## Stack

- Python 3.12, Click, Rich, httpx
- SQLite (`~/.data-engine/leads.db`)
- Dashboard: HTML rendered to `~/Desktop/data-engine-dashboard.html`

---

## Quick start

```bash
# Install
pip install -e .

# Add API keys
cp .env.example .env
# Edit .env with your keys (all free tiers — see .env.example for links)

# Fetch leads from OpenStreetMap (free, no key needed)
python3 cli.py fetch

# Run email enrichment chain
python3 cli.py enrich --limit 20

# View stats
python3 cli.py stats

# Export to CSV
python3 cli.py export

# Open HTML dashboard
python3 cli.py board

# Full pipeline
python3 cli.py run
```

---

## Email enrichment chain

Runs in order, stops at the first hit:

| Step | Method | Cost |
|------|--------|------|
| 1 | Scrape business website for `mailto:` links | Free |
| 2 | WHOIS registrant email | Free |
| 3 | Guess `info@` / `contact@` / `firstname@` + DNS MX verify | Free |
| 4 | Hunter.io API | 25/month free |
| 5 | Apollo.io people search | 50 credits/month free |

Hit rate: ~40% on leads with websites.

---

## CLI reference

```
python3 cli.py fetch        # Pull leads from OSM (15 NE cities × 4 categories)
python3 cli.py enrich       # Run email enrichment on unenriched leads
python3 cli.py enrich --limit 50  # Limit batch size
python3 cli.py stats        # Show pipeline counts
python3 cli.py board        # Generate + open HTML dashboard
python3 cli.py export       # Export CSV to Desktop
python3 cli.py serve        # Start web UI (Tailscale private)
python3 cli.py appforge ID  # Generate AppForge demo for lead by ID
python3 cli.py run          # Full pipeline: fetch → enrich → export → board
```

---

## API keys (all free)

| Service | Free tier | Purpose |
|---------|-----------|---------|
| OpenStreetMap | No key needed | Business listings |
| Foursquare | 1,000 calls/day | Additional listings |
| Hunter.io | 25/month | Email lookup |
| Apollo.io | 50 credits/month | Email lookup |
| Firecrawl | 500 credits/month | Website scraping |

---

## Project structure

```
data-engine/
├── cli.py              # All CLI commands
├── engine/
│   ├── db.py           # SQLite schema + queries
│   ├── fetcher.py      # OpenCorporates + Yelp + cross-reference
│   ├── osm.py          # OpenStreetMap / Overpass API fetcher
│   ├── enricher.py     # Email enrichment chain
│   └── exporter.py     # CSV export
├── dashboard/
│   └── renderer.py     # HTML dashboard generator
├── .env.example        # Environment variable template
└── requirements.txt
```
