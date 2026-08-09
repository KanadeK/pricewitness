"""Generate a self-contained, privacy-preserving HTML report."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from pricewitness.analysis import analyze


def write_report(
    database: str | Path,
    output: str | Path,
    *,
    spike_threshold: float = 10.0,
    shrink_threshold: float = 5.0,
) -> dict[str, Any]:
    document = analyze(
        database,
        spike_threshold=spike_threshold,
        shrink_threshold=shrink_threshold,
    )
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_report(document), encoding="utf-8", newline="\n")
    return document


def render_report(document: dict[str, Any]) -> str:
    summary = document["summary"]
    currency = _escape(summary["currency"])
    basket = summary["basket_change_percent"]
    basket_text = "Not enough history" if basket is None else f"{basket:+.2f}%"
    alerts_html = "".join(_alert_card(alert) for alert in document["alerts"])
    if not alerts_html:
        alerts_html = '<p class="empty">No threshold alerts in the mapped evidence.</p>'
    product_rows = "".join(_product_row(product, currency) for product in document["products"])
    if not product_rows:
        product_rows = '<tr><td colspan="7" class="empty">No mapped products yet.</td></tr>'
    review_rows = "".join(_review_row(item) for item in document["review_queue"])
    if not review_rows:
        review_rows = '<tr><td colspan="5" class="empty">Nothing needs alias review.</td></tr>'
    evidence_rows = "".join(_evidence_row(item) for item in document["evidence"])
    embedded = json.dumps(document, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>PriceWitness evidence report</title>
  <style>
    :root {{ color-scheme: light; --ink:#18201d; --muted:#63716a; --paper:#f5f1e8;
      --card:#fffdf8; --line:#d9d1c3; --green:#176b4d; --amber:#a95f05; --red:#a33b2b;
      --shadow:0 16px 45px rgba(56,45,29,.10); font-family:Inter,ui-sans-serif,system-ui,sans-serif; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; color:var(--ink); background:
      radial-gradient(circle at 8% 2%,#d9eddf 0,transparent 28rem),var(--paper); }}
    main {{ width:min(1180px,calc(100% - 32px)); margin:32px auto 72px; }}
    header {{ background:var(--ink); color:#f8f3e8; border-radius:22px; padding:34px;
      box-shadow:var(--shadow); position:relative; overflow:hidden; }}
    header::after {{ content:"PW"; position:absolute; right:20px; bottom:-38px; font:800 128px/1 monospace;
      opacity:.06; }} .eyebrow {{ color:#8fe0b7; font:700 12px/1.4 monospace; letter-spacing:.14em; }}
    h1 {{ margin:.35rem 0 .5rem; font-size:clamp(2.1rem,6vw,4.8rem); letter-spacing:-.06em; }}
    header p {{ max-width:760px; color:#cdd7d1; margin:0; }}
    .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:18px 0 32px; }}
    .metric,.panel {{ background:var(--card); border:1px solid var(--line); border-radius:16px; box-shadow:var(--shadow); }}
    .metric {{ padding:18px; }} .metric b {{ display:block; font-size:1.65rem; letter-spacing:-.04em; }}
    .metric span,.note,.empty {{ color:var(--muted); font-size:.9rem; }}
    section {{ margin-top:30px; }} h2 {{ font-size:1.35rem; margin:0 0 12px; }}
    .panel {{ overflow:auto; }} table {{ width:100%; border-collapse:collapse; font-size:.9rem; }}
    th,td {{ padding:13px 15px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }}
    th {{ font:700 11px/1.2 monospace; letter-spacing:.08em; color:var(--muted); text-transform:uppercase; }}
    tr:last-child td {{ border-bottom:0; }} code {{ font-size:.82em; background:#eee8dd; padding:2px 5px; border-radius:5px; }}
    .alerts {{ display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }}
    .alert {{ background:var(--card); border:1px solid var(--line); border-left:5px solid var(--amber);
      border-radius:12px; padding:15px 16px; }} .alert strong {{ display:block; margin-bottom:5px; }}
    .pill {{ display:inline-block; border-radius:999px; padding:3px 8px; font:700 10px/1.2 monospace;
      letter-spacing:.06em; background:#e6efe9; color:var(--green); }} .up {{ color:var(--red); }} .down {{ color:var(--green); }}
    footer {{ margin-top:30px; color:var(--muted); font-size:.82rem; }}
    @media (max-width:800px) {{ .grid {{ grid-template-columns:repeat(2,1fr); }} .alerts {{ grid-template-columns:1fr; }} }}
    @media (max-width:480px) {{ main {{ width:min(100% - 18px,1180px); margin-top:9px; }} header {{ padding:24px 20px; }} }}
    @media (prefers-reduced-motion:no-preference) {{ .metric,.panel,.alert {{ transition:transform .15s ease; }}
      .metric:hover,.alert:hover {{ transform:translateY(-2px); }} }}
    @media print {{ body {{ background:white; }} main {{ width:100%; margin:0; }} .metric,.panel,header,.alert {{ box-shadow:none; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div class="eyebrow">LOCAL RECEIPT EVIDENCE / PRICEWITNESS</div>
    <h1>Your basket remembers.</h1>
    <p>Mapped unit prices, package changes, and unresolved shorthand. This report contains no remote scripts, trackers, or source receipt bodies.</p>
  </header>
  <div class="grid" aria-label="Report summary">
    <div class="metric"><b>{summary["receipt_count"]}</b><span>receipts witnessed</span></div>
    <div class="metric"><b>{summary["mapped_percent"]:.1f}%</b><span>line items mapped</span></div>
    <div class="metric"><b>{basket_text}</b><span>weighted basket change</span></div>
    <div class="metric"><b>{summary["alert_count"]}</b><span>threshold alerts</span></div>
  </div>
  <section><h2>What changed</h2><div class="alerts">{alerts_html}</div></section>
  <section><h2>Product ledger</h2><div class="panel"><table>
    <thead><tr><th>Product</th><th>History</th><th>First</th><th>Latest</th><th>Change</th><th>Best current store</th><th>Unit</th></tr></thead>
    <tbody>{product_rows}</tbody></table></div></section>
  <section><h2>Review queue</h2><p class="note">Unmapped or ambiguous shorthand stays visible; PriceWitness never silently invents a product identity.</p>
    <div class="panel"><table><thead><tr><th>Date</th><th>Merchant</th><th>Raw descriptor</th><th>Suggested key</th><th>Status</th></tr></thead><tbody>{review_rows}</tbody></table></div></section>
  <section><h2>Evidence manifest</h2><div class="panel"><table><thead><tr><th>Date</th><th>Merchant</th><th>Source</th><th>Total</th><th>SHA-256</th></tr></thead><tbody>{evidence_rows}</tbody></table></div></section>
  <footer>Generated by PriceWitness. Prices are observations from supplied receipts, not market claims. Re-run <code>pricewitness verify</code> with the source files before relying on the hashes.</footer>
  <script type="application/json" id="pricewitness-analysis">{embedded}</script>
</main>
</body>
</html>
"""


def _product_row(product: dict[str, Any], currency: str) -> str:
    change = product["change_percent"]
    change_text = "—" if change is None else f"{change:+.2f}%"
    change_class = "up" if change is not None and change > 0 else "down"
    first = _price(product["first_unit_price"], currency)
    latest = _price(product["latest_unit_price"], currency)
    return (
        "<tr>"
        f"<td><strong>{_escape(product['name'])}</strong><br><code>{_escape(product['key'])}</code></td>"
        f'<td>{product["observation_count"]} observations<br><span class="note">{_escape(product["first_date"])} → {_escape(product["latest_date"])}</span></td>'
        f'<td>{first}</td><td>{latest}</td><td class="{change_class}">{change_text}</td>'
        f"<td>{_escape(product['best_current_merchant'] or '—')}</td>"
        f"<td>{_escape(product['comparison_unit'] or 'needs review')}</td></tr>"
    )


def _review_row(item: dict[str, Any]) -> str:
    return (
        f"<tr><td>{_escape(item['date'])}</td><td>{_escape(item['merchant'])}</td>"
        f"<td>{_escape(item['raw_name'])}</td><td><code>{_escape(item['suggested_key'])}</code></td>"
        f'<td><span class="pill">{_escape(item["status"])}</span></td></tr>'
    )


def _evidence_row(item: dict[str, Any]) -> str:
    total = (
        "—" if item["total"] is None else f"{_escape(item['currency'])} {_escape(item['total'])}"
    )
    return (
        f"<tr><td>{_escape(item['date'])}</td><td>{_escape(item['merchant'])}</td>"
        f"<td>{_escape(item['source'])}</td><td>{total}</td>"
        f'<td><code title="{_escape(item["sha256"])}">{_escape(item["sha256"][:16])}…</code></td></tr>'
    )


def _alert_card(alert: dict[str, Any]) -> str:
    return (
        '<article class="alert">'
        f'<span class="pill">{_escape(alert["type"])}</span>'
        f"<strong>{_escape(alert['product'])}</strong>"
        f"<div>{_escape(alert['message'])}</div>"
        f'<div class="note">{_escape(alert["date"])} · {_escape(alert.get("merchant", "mapping review"))}</div>'
        "</article>"
    )


def _price(value: str | None, currency: str) -> str:
    return "—" if value is None else f"{currency} {_escape(value)}"


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)
