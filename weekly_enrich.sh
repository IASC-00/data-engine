#!/bin/bash
# Weekly enrichment cron task
# Path to your data-engine directory
DE_DIR="$HOME/data-engine"
LOG_DIR="$DE_DIR/logs"
mkdir -p "$LOG_DIR"

cd "$DE_DIR"
python3 cli.py enrich --limit 100 >> "$LOG_DIR/enrich_$(date +\%F).log" 2>&1
python3 cli.py curate --limit 100 >> "$LOG_DIR/curate_$(date +\%F).log" 2>&1
