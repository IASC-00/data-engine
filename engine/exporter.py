"""
Export leads from SQLite to CSV.
"""
import csv
import os
from datetime import datetime
from .db import get_all_leads

EXPORT_DIR = os.path.expanduser('~/Desktop')


def export_csv(state=None, with_email_only=False, output_path=None) -> str:
    leads = get_all_leads(state=state, with_email_only=with_email_only)
    if not leads:
        return ''

    if not output_path:
        tag = f'_{state.lower()}' if state else ''
        tag += '_email' if with_email_only else ''
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_path = os.path.join(EXPORT_DIR, f'leads{tag}_{ts}.csv')

    fields = [
        'id', 'biz_name', 'owner_name', 'biz_type', 'address', 'city',
        'state', 'zip', 'phone', 'email', 'email_source', 'email_verified',
        'website', 'yelp_rating', 'yelp_category', 'filing_date',
        'outreach_sent', 'appforge_url', 'created_at',
    ]

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(leads)

    return output_path
