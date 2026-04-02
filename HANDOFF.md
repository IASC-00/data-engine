# Data Engine — Handoff

## Goal
Build a free lead pipeline targeting NE USA self-employed business owners
(restaurants, RE agents, property managers). Target: 100 verified emails/week at $0 cost.

---

## Current State (2026-03-17)

### DB
- **13,116+ leads** in `~/.data-engine/leads.db` (fetch still running as of handoff)
- Coverage: NY 8,898 | PA 3,254 | NJ 964 (more states loading)
- 682 leads already have emails (5% coverage, unenriched — came from OSM tags)
- 0 enriched runs completed yet

### Source Stack (final — both Yelp and OpenCorporates dropped)
| Source | Status | Notes |
|--------|--------|-------|
| OpenStreetMap (OSM) | ✅ Working | Primary source, free, no key, ~2k+ leads/city |
| Foursquare | ❌ Dead | v3 endpoint 410 Gone; service API key doesn't work |
| Yelp Fusion | ❌ Dead | Free tier no longer exists |
| OpenCorporates | ❌ Dead | £225/mo minimum |
| Google Places | ❌ Skipped | Requires $10 prepayment to activate billing |

### API Keys in `~/data-engine/.env`
| Key | Value | Status |
|-----|-------|--------|
| `HUNTER_API_KEY` | `cf166ee73e743f5b00939467f5eb62b1b5c8a853` | ✅ Active, 25 lookups/mo |
| `APOLLO_API_KEY` | `vlzRIbfGPAAVCan6rGoctQ` | ✅ Active, 50 credits/mo |
| `FIRECRAWL_API_KEY` | `fc-151089be7617447ba372882f9a154ff3` | ✅ Active, 500 credits/mo |
| `FOURSQUARE_API_KEY` | (two tested, both dead) | ❌ Remove from .env |

### Apollo Integration (enricher.py)
Updated to correct two-step flow:
1. Search via `POST /api/v1/mixed_people/api_search` — **free, no credits**
2. Enrich via `POST /api/v1/people/bulk_match` — **costs 1 credit** to reveal email
Auth: `x-api-key` header (not `api_key` in body — that was the old v1 format)

---

## What Worked
- OSM Overpass API — 2,073 Philly restaurants alone from one query; scales well
- Apollo Search API — correctly identified as free (no credits for search, credits only for enrichment)
- Hunter.io domain-search — straightforward, works fine
- Firecrawl CLI scraping — installed and key set

## What Didn't Work
- **Foursquare v3 API** — endpoint `/v3/places/search` returns 410 Gone. Both keys tested (Z2VEOJSTPBFU3J22AEJHU05ZAOUPPA5ZMZ1ZQ5FR4HXKS1H3 and KR2UAZSIP2GY0RZPQSG4YBHGYBB4B1LULUWLDPINXAJVJD4H). Bearer prefix gives 410, no-Bearer gives 401. Dead end — do not retry.
- **Google Places** — requires $10 prepayment to activate GCP billing. Skipped.
- **Yelp Fusion** — no longer has the free tier we built for.
- **OpenCorporates** — paid only (£225/mo min).

---

## Next Steps (in order)

### 1. Wait for fetch to finish, check final count
```bash
# Check if still running
ps aux | grep "cli.py fetch" | grep -v grep

# Final stats
python3 cli.py stats
```

### 2. Run enrichment on first batch
```bash
cd ~/data-engine
python3 cli.py enrich --limit 100
```
This runs the chain: Firecrawl → scrape → WHOIS → DNS guess → Hunter → Apollo.
Check coverage improvement after:
```bash
python3 cli.py stats
```

### 3. Export leads with emails to CSV
```bash
python3 cli.py export --email-only
# → ~/Desktop/data-engine-export.csv
```

### 4. Open dashboard
```bash
python3 cli.py board
```

### 5. Set up weekly cron
Add to crontab — runs every Monday 8am:
```
0 8 * * 1 cd /home/iswai/data-engine && python3 cli.py run >> /tmp/de-weekly.log 2>&1
```

### 6. Add HERE Places API (optional — if more leads needed)
- Sign up free at developer.here.com — 250k calls/mo, no card required
- Add `HERE_API_KEY` to `.env`
- Build `engine/here.py` fetcher (same pattern as `engine/osm.py`)

### 7. Add NY Open Data (optional — SoS filings free replacement)
- API: `data.ny.gov` — active corporations dataset, free REST API
- Gives "new business" leads (recently filed LLCs) — high intent
- Build `engine/ny_opendata.py` fetcher

---

## File Map
```
~/data-engine/
├── cli.py                  — main CLI (de fetch / enrich / export / stats / board / run)
├── engine/
│   ├── fetcher.py          — fetch_all() → OSM only now
│   ├── osm.py              — Overpass API fetcher (15 NE cities × 4 categories)
│   ├── enricher.py         — email chain (Firecrawl → scrape → WHOIS → DNS → Hunter → Apollo)
│   ├── foursquare.py       — DEAD — can delete
│   ├── db.py               — SQLite schema + queries
│   └── exporter.py         — CSV export
├── dashboard/renderer.py   — HTML dashboard generator
└── .env                    — API keys
```

## Commands Quick Ref
```bash
python3 cli.py fetch              # pull OSM leads (all NE cities)
python3 cli.py fetch --cities "Philadelphia, PA"  # single city
python3 cli.py enrich --limit 50  # enrich 50 leads
python3 cli.py enrich --all       # enrich everything
python3 cli.py stats              # pipeline counts
python3 cli.py board              # open dashboard
python3 cli.py export --email-only
python3 cli.py run                # full pipeline
```
