# Data Engine — Project A

NE USA lead generation pipeline. Pulls SoS filings + Yelp → cross-references → enriches emails → feeds AppForge demos.

## Run
```bash
python3 cli.py fetch        # pull NE filings + Yelp (add API keys first)
python3 cli.py enrich       # run email enrichment chain on unenriched leads
python3 cli.py stats        # show pipeline counts
python3 cli.py board        # generate + open HTML dashboard
python3 cli.py export       # export CSV to Desktop
python3 cli.py appforge 42  # generate AppForge demo for lead #42
python3 cli.py run          # full pipeline: fetch → enrich → export → board
```

## Stack
- Python 3.12, Click, Rich, httpx, SQLite
- DB: ~/.data-engine/leads.db
- Dashboard: ~/Desktop/data-engine-dashboard.html

## Key files
- `cli.py` — all CLI commands
- `engine/fetcher.py` — OpenCorporates (11 NE states) + Yelp Fusion + cross-reference
- `engine/enricher.py` — email chain: scrape → WHOIS → DNS guess+verify → Hunter → Apollo
- `engine/db.py` — SQLite schema + queries
- `engine/exporter.py` — CSV export
- `dashboard/renderer.py` — HTML dashboard generator
- `.env` — API keys

## API keys needed (all free tiers)
- `YELP_API_KEY` — yelp.com/developers (500 calls/day) ← highest priority
- `OPENCORPORATES_API_KEY` — opencorporates.com (higher rate limits)
- `HUNTER_API_KEY` — hunter.io (25 lookups/month)
- `APOLLO_API_KEY` — apollo.io (50 email credits/month)
- `GOOGLE_PLACES_API_KEY` — console.cloud.google.com ($200/mo free credit)

## Target
100 verified emails/week, $0 cost, NE USA self-employed business owners

## Email enrichment chain (in order)
1. Scrape business website contact page (mailto: links + regex)
2. WHOIS registrant email lookup
3. Guess info@/contact@/firstname@ + DNS MX verify
4. Hunter.io API
5. Apollo.io people search

## NE states covered
PA, NJ, NY, MA, CT, MD, RI, VT, NH, ME, DE

## AppForge integration
`python3 cli.py appforge LEAD_ID` — detects biz type → generates matching demo → returns shareable URL
Requires AppForge running on localhost:5001
