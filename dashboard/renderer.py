"""
Generate HTML dashboard for Data Engine leads.
"""

import os
import json
from datetime import datetime
from string import Template
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from engine.db import get_all_leads, get_stats

DASHBOARD_PATH = os.path.expanduser("~/Desktop/data-engine-dashboard.html")


def _row_data(l: dict) -> dict:
    return {
        "id": l.get("id", ""),
        "biz_name": l.get("biz_name", ""),
        "city": l.get("city", "") or "",
        "state": l.get("state", "") or "",
        "biz_type": (l.get("biz_type", "") or "")[:40],
        "email": l.get("email", "") or "",
        "email_source": l.get("email_source", "") or "",
        "email_verified": int(l.get("email_verified", 0) or 0),
        "phone": l.get("phone", "") or "",
        "filing_date": l.get("filing_date", "") or "",
        "appforge_url": l.get("appforge_url", "") or "",
        "outreach_sent": int(l.get("outreach_sent", 0) or 0),
        "campaign_week": l.get("campaign_week", "") or "",
        "outreach_status": l.get("outreach_status", "pending"),
        "enriched": int(l.get("enriched", 0) or 0),
        "website": l.get("website", "") or "",
    }


# Template uses $VAR placeholders — no conflict with JS {} syntax
TEMPLATE = Template(r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Data Engine — Lead Dashboard</title>
<script src="https://cdn.tailwindcss.com"></script>
<style>
  .funnel-stage { transition: background 0.2s; cursor: pointer; }
  .funnel-stage:hover { filter: brightness(1.15); }
  .src-seg { position: relative; display: inline-block; height: 28px; min-width: 4px; vertical-align: top; }
  .src-seg .src-tip {
    display: none; position: absolute; bottom: 34px; left: 50%;
    transform: translateX(-50%); background: #1e293b; color: #cbd5e1;
    font-size: 11px; padding: 4px 8px; border-radius: 4px; white-space: nowrap;
    border: 1px solid #334155; z-index: 10; pointer-events: none;
  }
  .src-seg:hover .src-tip { display: block; }
  .tl-bar { display: inline-block; width: 100%; background: #38bdf8; border-radius: 4px 4px 0 0; min-height: 4px; }
  .tl-col { display: flex; flex-direction: column; align-items: center; gap: 4px; flex: 1 1 0; min-width: 40px; }
  .tl-col:hover .tl-bar { background: #7dd3fc; }
  .outreach-btn { font-size: 10px; padding: 2px 6px; border-radius: 4px; cursor: pointer; border: none; }
  .outreach-btn.unsent { background: #475569; color: #cbd5e1; }
  .outreach-btn.sent    { background: #166534; color: #86efac; }
</style>
</head>
<body class="bg-slate-900 text-slate-100 min-h-screen p-6 font-mono">
<div class="max-w-7xl mx-auto">

  <!-- Header -->
  <div class="flex items-center justify-between mb-6">
    <h1 class="text-2xl font-bold text-white">Data Engine <span class="text-sky-400">Lead Pipeline</span></h1>
    <span class="text-xs text-slate-500">Generated $generated_at</span>
  </div>

  <!-- Stats cards (clickable filters) -->
  <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
    <div class="bg-slate-800 rounded-lg p-4 cursor-pointer hover:bg-slate-700 transition" onclick="setFilter('all')">
      <div class="text-3xl font-bold text-white">$total</div>
      <div class="text-xs text-slate-400 mt-1">Total Leads</div>
    </div>
    <div class="bg-slate-800 rounded-lg p-4 cursor-pointer hover:bg-slate-700 transition" onclick="setFilter('email')">
      <div class="text-3xl font-bold text-emerald-400">$with_email</div>
      <div class="text-xs text-slate-400 mt-1">With Email</div>
    </div>
    <div class="bg-slate-800 rounded-lg p-4 cursor-pointer hover:bg-slate-700 transition" onclick="setFilter('enriched')">
      <div class="text-3xl font-bold text-sky-400">$enriched</div>
      <div class="text-xs text-slate-400 mt-1">Enriched</div>
    </div>
    <div class="bg-slate-800 rounded-lg p-4 cursor-pointer hover:bg-slate-700 transition" onclick="setFilter('outreach')">
      <div class="text-3xl font-bold text-violet-400">$outreach_sent</div>
      <div class="text-xs text-slate-400 mt-1">Outreach Sent</div>
    </div>
  </div>

  <!-- Feature 1: Funnel View -->
  <div class="bg-slate-800 rounded-lg p-5 mb-8">
    <h3 class="text-sm font-semibold text-slate-300 mb-4">Pipeline Funnel</h3>
    <div id="funnel-container" class="flex flex-col gap-2 items-center w-full"></div>
  </div>

  <!-- Feature 3: Timeline Chart -->
  <div class="bg-slate-800 rounded-lg p-5 mb-8">
    <h3 class="text-sm font-semibold text-slate-300 mb-4">Filings by Month</h3>
    <div id="timeline-container"></div>
  </div>

  <!-- Charts row -->
  <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
    <div class="bg-slate-800 rounded-lg p-4">
      <h3 class="text-sm font-semibold text-slate-300 mb-3">By State</h3>
      <div class="flex flex-col gap-1.5 text-sm" id="chart-state">$state_rows</div>
    </div>

    <!-- Feature 4: Email Source Visual Breakdown -->
    <div class="bg-slate-800 rounded-lg p-4">
      <h3 class="text-sm font-semibold text-slate-300 mb-3">Email Source</h3>
      <div id="source-visual"></div>
    </div>

    <div class="bg-slate-800 rounded-lg p-4">
      <h3 class="text-sm font-semibold text-slate-300 mb-3">Coverage</h3>
      <div class="flex flex-col gap-3 text-sm">
        <div>
          <div class="flex justify-between text-xs mb-1">
            <span class="text-slate-400">Email coverage</span>
            <span class="text-slate-300" id="pct-email">-</span>
          </div>
          <div class="bg-slate-700 rounded-full h-2"><div id="bar-email" class="bg-emerald-500 h-2 rounded-full" style="width:0%"></div></div>
        </div>
        <div>
          <div class="flex justify-between text-xs mb-1">
            <span class="text-slate-400">Phone coverage</span>
            <span class="text-slate-300" id="pct-phone">-</span>
          </div>
          <div class="bg-slate-700 rounded-full h-2"><div id="bar-phone" class="bg-sky-500 h-2 rounded-full" style="width:0%"></div></div>
        </div>
        <div>
          <div class="flex justify-between text-xs mb-1">
            <span class="text-slate-400">Enriched</span>
            <span class="text-slate-300" id="pct-enriched">-</span>
          </div>
          <div class="bg-slate-700 rounded-full h-2"><div id="bar-enriched" class="bg-violet-500 h-2 rounded-full" style="width:0%"></div></div>
        </div>
        <div>
          <div class="flex justify-between text-xs mb-1">
            <span class="text-slate-400">Has demo</span>
            <span class="text-slate-300" id="pct-demo">-</span>
          </div>
          <div class="bg-slate-700 rounded-full h-2"><div id="bar-demo" class="bg-amber-500 h-2 rounded-full" style="width:0%"></div></div>
        </div>
        <div>
          <div class="flex justify-between text-xs mb-1">
            <span class="text-slate-400">Outreach sent</span>
            <span class="text-slate-300" id="pct-outreach">-</span>
          </div>
          <div class="bg-slate-700 rounded-full h-2"><div id="bar-outreach" class="bg-rose-500 h-2 rounded-full" style="width:0%"></div></div>
        </div>
      </div>
    </div>
  </div>

  <!-- Feature 2: Top Business Types Table (full-width card below charts row) -->
  <div class="bg-slate-800 rounded-lg p-4 mb-8">
    <h3 class="text-sm font-semibold text-slate-300 mb-3">Top Business Types</h3>
    <div class="overflow-x-auto">
      <table class="w-full text-xs" id="biz-type-table">
        <thead>
          <tr class="text-slate-500 uppercase border-b border-slate-700">
            <th class="px-2 py-1.5 text-left">#</th>
            <th class="px-2 py-1.5 text-left">Type</th>
            <th class="px-2 py-1.5 text-right">Leads</th>
            <th class="px-2 py-1.5 text-left" style="width:200px">Email Hit Rate</th>
          </tr>
        </thead>
        <tbody id="biz-type-tbody"></tbody>
      </table>
    </div>
  </div>

  <!-- Filter bar -->
  <div class="bg-slate-800 rounded-lg p-4 mb-4">
    <div class="flex flex-wrap gap-2 items-center">
      <div class="flex flex-wrap gap-1.5" id="filter-pills">
        <button onclick="setFilter('all')"          class="pill active px-3 py-1 rounded-full text-xs font-medium bg-slate-600 text-white">All</button>
        <button onclick="setFilter('email')"        class="pill px-3 py-1 rounded-full text-xs font-medium bg-slate-700 text-slate-300 hover:bg-slate-600">Has Email</button>
        <button onclick="setFilter('phone')"        class="pill px-3 py-1 rounded-full text-xs font-medium bg-slate-700 text-slate-300 hover:bg-slate-600">Has Phone</button>
        <button onclick="setFilter('both')"         class="pill px-3 py-1 rounded-full text-xs font-medium bg-slate-700 text-slate-300 hover:bg-slate-600">Email + Phone</button>
        <button onclick="setFilter('demo')"         class="pill px-3 py-1 rounded-full text-xs font-medium bg-slate-700 text-slate-300 hover:bg-slate-600">Has Demo</button>
        <button onclick="setFilter('enriched')"     class="pill px-3 py-1 rounded-full text-xs font-medium bg-slate-700 text-slate-300 hover:bg-slate-600">Enriched</button>
        <button onclick="setFilter('outreach')"     class="pill px-3 py-1 rounded-full text-xs font-medium bg-slate-700 text-slate-300 hover:bg-slate-600">Outreach Sent</button>
        <button onclick="setFilter('empty')"        class="pill px-3 py-1 rounded-full text-xs font-medium bg-slate-700 text-slate-300 hover:bg-slate-600">No Contact</button>
        <button onclick="setFilter('ready')"         class="pill px-3 py-1 rounded-full text-xs font-medium bg-emerald-800 text-emerald-200 hover:bg-emerald-700">&#9889; Ready to Send</button>
        <button onclick="setFilter('weekly')"        class="pill px-3 py-1 rounded-full text-xs font-medium bg-sky-800 text-sky-100 hover:bg-sky-700">🎯 This Week's 100</button>
        <button onclick="setFilter('marked_sent')"  class="pill px-3 py-1 rounded-full text-xs font-medium bg-slate-700 text-slate-300 hover:bg-slate-600">Marked Sent (local)</button>
        <span id="marked-count-badge" class="px-2 py-1 rounded-full text-xs font-medium bg-violet-900 text-violet-300 hidden"></span>
      </div>
      <div class="flex-1"></div>
      <select id="state-filter" onchange="applyFilters()"
        class="bg-slate-700 text-slate-300 text-xs rounded px-2 py-1.5 border border-slate-600 focus:outline-none focus:border-sky-500">
        <option value="">All States</option>
        $state_options
      </select>
      <select id="type-filter" onchange="applyFilters()"
        class="bg-slate-700 text-slate-300 text-xs rounded px-2 py-1.5 border border-slate-600 focus:outline-none focus:border-sky-500">
        <option value="">All Types</option>
        $type_options
      </select>
      <input id="search-input" type="text" placeholder="Search business…" oninput="applyFilters()"
        class="bg-slate-700 text-slate-300 text-xs rounded px-2 py-1.5 border border-slate-600 focus:outline-none focus:border-sky-500 w-44">
      <button onclick="exportCSV()"
        class="px-3 py-1.5 rounded text-xs font-medium bg-emerald-700 text-emerald-100 hover:bg-emerald-600 transition">
        Export CSV
      </button>
    </div>
    <div class="mt-2 text-xs text-slate-500" id="result-count"></div>
  </div>

  <!-- Leads table -->
  <div class="bg-slate-800 rounded-lg overflow-hidden">
    <div class="overflow-x-auto">
      <table class="w-full text-sm" id="leads-table">
        <thead>
          <tr class="border-b border-slate-700 text-xs text-slate-500 uppercase select-none">
            <th class="px-3 py-2 text-left cursor-pointer hover:text-slate-300" onclick="sortBy('biz_name')">Business<span id="sort-biz_name"></span></th>
            <th class="px-3 py-2 text-left cursor-pointer hover:text-slate-300" onclick="sortBy('state')">Location<span id="sort-state"></span></th>
            <th class="px-3 py-2 text-left cursor-pointer hover:text-slate-300" onclick="sortBy('biz_type')">Type<span id="sort-biz_type"></span></th>
            <th class="px-3 py-2 text-left cursor-pointer hover:text-slate-300" onclick="sortBy('email')">Email<span id="sort-email"></span></th>
            <th class="px-3 py-2 text-left cursor-pointer hover:text-slate-300" onclick="sortBy('phone')">Phone<span id="sort-phone"></span></th>
            <th class="px-3 py-2 text-left cursor-pointer hover:text-slate-300" onclick="sortBy('filing_date')">Filed<span id="sort-filing_date"></span></th>
            <th class="px-3 py-2 text-left">Demo</th>
            <th class="px-3 py-2 text-left">Status</th>
          </tr>
        </thead>
        <tbody id="leads-tbody"></tbody>
      </table>
    </div>
  </div>

  <div class="mt-4 text-xs text-slate-600">
    Import CSV: <code class="text-slate-500">python3 cli.py import path/to/file.csv</code>
  </div>

</div>

<script>
const LEADS = $leads_json;

let activeFilter = 'all';
let sortCol = '';
let sortDir = 1;
let filtered = [];

// ─── Coverage bars ────────────────────────────────────────────────────────────
(function() {
  const total = LEADS.length;
  if (!total) return;
  const pct = (n) => Math.round(n / total * 100);
  const withEmail    = LEADS.filter(l => l.email).length;
  const withPhone    = LEADS.filter(l => l.phone).length;
  const enriched     = LEADS.filter(l => l.enriched).length;
  const withDemo     = LEADS.filter(l => l.appforge_url).length;
  const withOutreach = LEADS.filter(l => l.outreach_sent).length;
  const set = (id, bar, n) => {
    const p = pct(n);
    document.getElementById(id).textContent = p + '%';
    document.getElementById(bar).style.width = p + '%';
  };
  set('pct-email',    'bar-email',    withEmail);
  set('pct-phone',    'bar-phone',    withPhone);
  set('pct-enriched', 'bar-enriched', enriched);
  set('pct-demo',     'bar-demo',     withDemo);
  set('pct-outreach', 'bar-outreach', withOutreach);
})();

// ─── Feature 1: Funnel View ───────────────────────────────────────────────────
(function() {
  const total = LEADS.length;
  if (!total) return;

  const stages = [
    { label: 'Total',         count: total,                                                        color: 'bg-slate-600',   filter: 'all',      pct: 100 },
    { label: 'Has Website',   count: LEADS.filter(l => l.website).length,                         color: 'bg-blue-700',    filter: null },
    { label: 'Has Email',     count: LEADS.filter(l => l.email).length,                           color: 'bg-emerald-700', filter: 'email' },
    { label: 'Enriched',      count: LEADS.filter(l => l.enriched).length,                        color: 'bg-sky-700',     filter: 'enriched' },
    { label: 'Has Demo',      count: LEADS.filter(l => l.appforge_url).length,                    color: 'bg-amber-700',   filter: 'demo' },
    { label: 'Outreach Sent', count: LEADS.filter(l => l.outreach_sent).length,                   color: 'bg-violet-700',  filter: 'outreach' },
  ];

  const maxW = 100;
  const minW = 30;
  const step = stages.length > 1 ? (maxW - minW) / (stages.length - 1) : 0;

  const container = document.getElementById('funnel-container');
  stages.forEach(function(s, i) {
    const w = maxW - i * step;
    const pct = total > 0 ? Math.round(s.count / total * 100) : 0;
    const onclick = s.filter ? 'setFilter(\'' + s.filter + '\')' : 'setFilter(\'all\')';
    const div = document.createElement('div');
    div.className = 'funnel-stage ' + s.color + ' rounded text-center py-2 text-xs font-medium text-white';
    div.style.width = w + '%';
    div.setAttribute('onclick', onclick);
    div.title = 'Click to filter';
    div.innerHTML = s.label + ': <span class="font-bold">' + s.count.toLocaleString() + '</span> <span class="opacity-70">(' + pct + '%)</span>';
    container.appendChild(div);
  });
})();

// ─── Feature 3: Timeline Chart ────────────────────────────────────────────────
(function() {
  const container = document.getElementById('timeline-container');
  const monthMap = {};
  LEADS.forEach(function(l) {
    if (!l.filing_date) return;
    const m = l.filing_date.toString().slice(0, 7);
    if (!m || m.length < 7) return;
    monthMap[m] = (monthMap[m] || 0) + 1;
  });
  const months = Object.keys(monthMap).sort();
  if (months.length < 3) {
    container.innerHTML = '<p class="text-slate-500 text-xs">Not enough filing date data</p>';
    return;
  }
  const maxCount = Math.max.apply(null, months.map(function(m) { return monthMap[m]; }));
  const barH = 120;
  const wrapper = document.createElement('div');
  wrapper.style.cssText = 'display:flex;align-items:flex-end;gap:4px;width:100%;overflow-x:auto;padding-bottom:8px;';
  months.forEach(function(m) {
    const count = monthMap[m];
    const h = maxCount > 0 ? Math.max(4, Math.round(count / maxCount * barH)) : 4;
    const col = document.createElement('div');
    col.className = 'tl-col';
    const dateObj = new Date(m + '-01');
    const label = dateObj.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
    col.innerHTML =
      '<span style="font-size:9px;color:#94a3b8;">' + count + '</span>' +
      '<div class="tl-bar" style="height:' + h + 'px;"></div>' +
      '<span style="font-size:9px;color:#64748b;white-space:nowrap;">' + label + '</span>';
    wrapper.appendChild(col);
  });
  container.appendChild(wrapper);
})();

// ─── Feature 4: Email Source Visual Breakdown ─────────────────────────────────
(function() {
  const container = document.getElementById('source-visual');
  const srcColors = {
    whois:  { bg: '#065f46', fg: '#6ee7b7' },
    scrape: { bg: '#0c4a6e', fg: '#7dd3fc' },
    guess:  { bg: '#78350f', fg: '#fcd34d' },
    hunter: { bg: '#4c1d95', fg: '#c4b5fd' },
    apollo: { bg: '#881337', fg: '#fda4af' },
    none:   { bg: '#1e293b', fg: '#94a3b8' },
  };
  const srcOrder = ['whois', 'scrape', 'guess', 'hunter', 'apollo', 'none'];

  // count from LEADS
  const counts = {};
  LEADS.forEach(function(l) {
    const src = l.email_source || 'none';
    counts[src] = (counts[src] || 0) + 1;
  });
  const grandTotal = LEADS.length;

  // Build stacked bar
  const bar = document.createElement('div');
  bar.style.cssText = 'display:flex;width:100%;height:28px;border-radius:4px;overflow:hidden;margin-bottom:12px;';

  const legend = document.createElement('div');
  legend.style.cssText = 'display:flex;flex-direction:column;gap:6px;';

  srcOrder.forEach(function(src) {
    const n = counts[src] || 0;
    if (!n) return;
    const pct = grandTotal > 0 ? (n / grandTotal * 100) : 0;
    const col = srcColors[src] || srcColors['none'];

    // bar segment
    const seg = document.createElement('div');
    seg.className = 'src-seg';
    seg.style.cssText = 'width:' + pct + '%;background:' + col.bg + ';';
    seg.innerHTML = '<span class="src-tip">' + src + ': ' + n + ' (' + pct.toFixed(1) + '%)</span>';
    bar.appendChild(seg);

    // legend row
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;align-items:center;gap:6px;font-size:11px;';
    row.innerHTML =
      '<span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:' + col.bg + ';flex-shrink:0;"></span>' +
      '<span style="color:#94a3b8;flex:1;">' + src + '</span>' +
      '<span style="color:#e2e8f0;font-weight:600;">' + n + '</span>' +
      '<span style="color:#64748b;margin-left:4px;">' + pct.toFixed(1) + '%</span>';
    legend.appendChild(row);
  });

  if (!Object.keys(counts).length) {
    container.innerHTML = '<span class="text-slate-500 text-xs">No data</span>';
    return;
  }
  container.appendChild(bar);
  container.appendChild(legend);
})();

// ─── Feature 2: Top Business Types Table ──────────────────────────────────────
(function() {
  const typeMap = {};
  LEADS.forEach(function(l) {
    const t = (l.biz_type || '').trim();
    if (!t) return;
    if (!typeMap[t]) typeMap[t] = { total: 0, withEmail: 0 };
    typeMap[t].total++;
    if (l.email) typeMap[t].withEmail++;
  });

  const sorted = Object.keys(typeMap).map(function(t) {
    return { type: t, total: typeMap[t].total, withEmail: typeMap[t].withEmail };
  }).sort(function(a, b) { return b.total - a.total; }).slice(0, 15);

  const tbody = document.getElementById('biz-type-tbody');
  sorted.forEach(function(row, i) {
    const rate = row.total > 0 ? Math.round(row.withEmail / row.total * 100) : 0;
    const barColor = rate > 30 ? '#16a34a' : rate >= 10 ? '#d97706' : '#dc2626';
    const tr = document.createElement('tr');
    tr.className = 'border-b border-slate-700 hover:bg-slate-750 cursor-pointer';
    tr.style.background = 'transparent';
    tr.onmouseover = function() { this.style.background = '#1e293b'; };
    tr.onmouseout  = function() { this.style.background = 'transparent'; };
    tr.onclick = function() {
      const sel = document.getElementById('type-filter');
      sel.value = row.type;
      applyFilters();
      document.getElementById('leads-table').scrollIntoView({ behavior: 'smooth' });
    };
    tr.innerHTML =
      '<td class="px-2 py-1.5 text-slate-500">' + (i + 1) + '</td>' +
      '<td class="px-2 py-1.5 text-slate-300">' + row.type + '</td>' +
      '<td class="px-2 py-1.5 text-slate-200 font-bold text-right">' + row.total + '</td>' +
      '<td class="px-2 py-1.5">' +
        '<div style="display:flex;align-items:center;gap:6px;">' +
          '<div style="flex:1;background:#334155;border-radius:3px;height:8px;">' +
            '<div style="width:' + rate + '%;background:' + barColor + ';height:8px;border-radius:3px;"></div>' +
          '</div>' +
          '<span style="color:#94a3b8;font-size:10px;min-width:30px;">' + rate + '%</span>' +
        '</div>' +
      '</td>';
    tbody.appendChild(tr);
  });

  if (!sorted.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="px-2 py-4 text-center text-slate-500">No data</td></tr>';
  }
})();

// ─── Feature 5: Outreach Status Tracker — localStorage helpers ────────────────
function getOutreachStatus(id) {
  return localStorage.getItem('outreach_' + id) === '1';
}

function setOutreachStatus(id, val) {
  localStorage.setItem('outreach_' + id, val ? '1' : '0');
}

function countMarkedLocally() {
  return LEADS.filter(function(l) { return getOutreachStatus(l.id); }).length;
}

function updateMarkedBadge() {
  const n = countMarkedLocally();
  const badge = document.getElementById('marked-count-badge');
  if (n > 0) {
    badge.textContent = n + ' marked locally';
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }
}

function toggleOutreach(id) {
  const cur = getOutreachStatus(id);
  setOutreachStatus(id, !cur);
  updateMarkedBadge();
  // re-render current view to update button state
  renderRows();
}

// ─── Filter logic ─────────────────────────────────────────────────────────────
function setFilter(f) {
  activeFilter = f;
  document.querySelectorAll('.pill').forEach(function(b) {
    b.classList.remove('active','bg-slate-600','text-white');
    b.classList.add('bg-slate-700','text-slate-300');
  });
  const active = document.querySelector('.pill[onclick="setFilter(\'' + f + '\')"]');
  if (active) {
    active.classList.add('active','bg-slate-600','text-white');
    active.classList.remove('bg-slate-700','text-slate-300');
  }
  applyFilters();
}

function matchesFilter(l) {
  if (activeFilter === 'email')       return !!l.email;
  if (activeFilter === 'phone')       return !!l.phone;
  if (activeFilter === 'both')        return !!l.email && !!l.phone;
  if (activeFilter === 'demo')        return !!l.appforge_url;
  if (activeFilter === 'enriched')    return l.enriched === 1;
  if (activeFilter === 'outreach')    return l.outreach_sent === 1;
  if (activeFilter === 'empty')       return !l.email && !l.phone;
  if (activeFilter === 'ready')       return !!l.email && !!l.appforge_url && !l.outreach_sent && !getOutreachStatus(l.id);
  if (activeFilter === 'weekly')      return !!l.campaign_week;
  if (activeFilter === 'marked_sent') return getOutreachStatus(l.id);
  return true;
}

function applyFilters() {
  const state  = document.getElementById('state-filter').value;
  const type   = document.getElementById('type-filter').value.toLowerCase();
  const search = document.getElementById('search-input').value.toLowerCase().trim();

  filtered = LEADS.filter(function(l) {
    if (!matchesFilter(l)) return false;
    if (state  && l.state !== state) return false;
    if (type   && !l.biz_type.toLowerCase().includes(type)) return false;
    if (search && !l.biz_name.toLowerCase().includes(search)) return false;
    return true;
  });

  if (sortCol) {
    filtered.sort(function(a, b) {
      const av = (a[sortCol] || '').toString().toLowerCase();
      const bv = (b[sortCol] || '').toString().toLowerCase();
      return av < bv ? -sortDir : av > bv ? sortDir : 0;
    });
  }

  renderRows();
}

function sortBy(col) {
  if (sortCol === col) sortDir = -sortDir;
  else { sortCol = col; sortDir = 1; }
  document.querySelectorAll('[id^="sort-"]').forEach(function(el) { el.textContent = ''; });
  const ind = document.getElementById('sort-' + col);
  if (ind) ind.textContent = sortDir === 1 ? ' ▲' : ' ▼';
  applyFilters();
}

function emailBadge(l) {
  if (!l.email) return '';
  const color = l.email_verified
    ? 'bg-emerald-900 text-emerald-300'
    : 'bg-amber-900 text-amber-300';
  return '<span class="text-xs px-1.5 py-0.5 rounded ' + color + '">' + l.email_source + '</span>';
}

function renderRows() {
  const tbody = document.getElementById('leads-tbody');
  if (!filtered.length) {
    tbody.innerHTML = "<tr><td colspan='8' class='px-3 py-8 text-center text-slate-500'>No leads match</td></tr>";
    document.getElementById('result-count').textContent = '0 leads';
    return;
  }

  const PAGE = 500;
  const rows = filtered.slice(0, PAGE).map(function(l) {
    const dimmed = (!l.email && !l.phone) ? 'opacity-40' : '';
    const demo   = l.appforge_url
      ? '<a href="' + l.appforge_url + '" target="_blank" class="text-sky-400 hover:underline text-xs">Demo</a>'
      : '';
    const isSent = getOutreachStatus(l.id);
    const btnClass = isSent ? 'outreach-btn sent' : 'outreach-btn unsent';
    const btnLabel = isSent ? 'Sent ✓' : 'Mark Sent';
    const outreachBtn = '<button class="' + btnClass + '" onclick="toggleOutreach(' + l.id + ');event.stopPropagation();">' + btnLabel + '</button>';
    return '<tr class="border-b border-slate-800 hover:bg-slate-800/50 ' + dimmed + '">'
      + '<td class="px-3 py-2 text-slate-300 font-medium">' + l.biz_name + '</td>'
      + '<td class="px-3 py-2 text-slate-400">' + l.city + ', ' + l.state + '</td>'
      + '<td class="px-3 py-2 text-slate-400 text-xs">' + l.biz_type + '</td>'
      + '<td class="px-3 py-2 text-slate-300">' + (l.email || '—') + ' ' + emailBadge(l) + '</td>'
      + '<td class="px-3 py-2 text-slate-500 text-xs">' + (l.phone || '—') + '</td>'
      + '<td class="px-3 py-2 text-slate-500 text-xs">' + (l.filing_date || '—') + '</td>'
      + '<td class="px-3 py-2">' + demo + '</td>'
      + '<td class="px-3 py-2">' + outreachBtn + '</td>'
      + '</tr>';
  }).join('');

  const extra = filtered.length > PAGE
    ? '<tr><td colspan="8" class="px-3 py-4 text-center text-slate-600 text-xs">... ' + (filtered.length - PAGE) + ' more — export CSV or narrow filters</td></tr>'
    : '';

  tbody.innerHTML = rows + extra;
  document.getElementById('result-count').textContent =
    filtered.length.toLocaleString() + ' lead' + (filtered.length !== 1 ? 's' : '');
}

function exportCSV() {
  const cols = ['id','biz_name','city','state','biz_type','email','email_source','email_verified','phone','website','filing_date','appforge_url','outreach_sent','enriched','local_status'];
  const header = cols.join(',');
  const rows = filtered.map(function(l) {
    return cols.map(function(c) {
      let v;
      if (c === 'local_status') {
        v = getOutreachStatus(l.id) ? '1' : '0';
      } else {
        v = (l[c] !== undefined ? l[c] : '').toString().replace(/"/g, '""');
      }
      return (v.includes(',') || v.includes('"') || v.includes('\n')) ? '"' + v + '"' : v;
    }).join(',');
  });
  const csv = [header, ...rows].join('\n');
  const blob = new Blob([csv], {type: 'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  const label = activeFilter !== 'all' ? '_' + activeFilter : '';
  a.download = 'leads' + label + '_' + new Date().toISOString().slice(0,10) + '.csv';
  a.click();
}

// ─── Init ─────────────────────────────────────────────────────────────────────
updateMarkedBadge();
applyFilters();
</script>
</body>
</html>""")


def render_dashboard() -> str:
    stats = get_stats()
    leads = get_all_leads(limit=5000)

    states = sorted({l.get("state", "") for l in leads if l.get("state")})
    types = sorted(
        {(l.get("biz_type", "") or "").strip() for l in leads if l.get("biz_type")}
    )

    leads_json = json.dumps([_row_data(l) for l in leads], separators=(",", ":"))

    total = stats["total"]
    state_rows = (
        "".join(
            f"<div class=\"flex justify-between cursor-pointer hover:text-white\" onclick=\"document.getElementById('state-filter').value='{r['state']}';applyFilters()\">"
            f'<span class="text-slate-400">{r["state"]}</span>'
            f'<span class="text-slate-200 font-medium">{r["n"]}</span></div>'
            for r in stats["by_state"]
        )
        or "<span class='text-slate-500'>No data</span>"
    )

    state_options = "\n".join(f'<option value="{s}">{s}</option>' for s in states)
    type_options = "\n".join(f'<option value="{t}">{t}</option>' for t in types[:30])

    html = TEMPLATE.substitute(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        total=total,
        with_email=stats["with_email"],
        enriched=stats["enriched"],
        outreach_sent=stats["outreach_sent"],
        state_rows=state_rows,
        state_options=state_options,
        type_options=type_options,
        leads_json=leads_json,
    )

    with open(DASHBOARD_PATH, "w") as f:
        f.write(html)
    return DASHBOARD_PATH
