"""Scrape regulated petroleum-derivative prices from energetika-portal.si.

Source page lists effective dates and EUR/liter prices for NMB-95 petrol,
diesel, and extra-light heating oil (ELKO) from 2007 onward.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Iterable

URL = (
    "https://www.energetika-portal.si/podrocja/energetika/"
    "cene-naftnih-derivatov/regulirane-cene-naftnih-derivatov/"
)
PRODUCTS = ("nmb95", "diesel", "elko")


@dataclass
class PriceRow:
    date: str  # ISO YYYY-MM-DD
    nmb95: float | None
    diesel: float | None
    elko: float | None


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_target_table = False
        self._table_depth = 0
        self._in_row = False
        self._in_cell = False
        self._current_row: list[str] = []
        self._current_cell: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            classes = dict(attrs).get("class", "") or ""
            if "contenttable" in classes or self._in_target_table:
                self._in_target_table = True
                self._table_depth += 1
        elif self._in_target_table:
            if tag == "tr":
                self._in_row = True
                self._current_row = []
            elif tag == "td" and self._in_row:
                self._in_cell = True
                self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_target_table:
            self._table_depth -= 1
            if self._table_depth == 0:
                self._in_target_table = False
        elif self._in_target_table:
            if tag == "td" and self._in_cell:
                self._current_row.append("".join(self._current_cell).strip())
                self._in_cell = False
            elif tag == "tr" and self._in_row:
                if self._current_row:
                    self.rows.append(self._current_row)
                self._in_row = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)


def _parse_price(cell: str) -> float | None:
    cell = cell.strip().replace("\xa0", " ")
    if not cell:
        return None
    cleaned = cell.replace(" ", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_date(cell: str) -> str | None:
    try:
        return datetime.strptime(cell.strip(), "%d.%m.%Y").date().isoformat()
    except ValueError:
        return None


def fetch_html(url: str = URL, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "energetika-scraper/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_prices(html: str) -> list[PriceRow]:
    parser = _TableParser()
    parser.feed(html)
    out: list[PriceRow] = []
    for row in parser.rows:
        if len(row) < 4:
            continue
        iso = _parse_date(row[0])
        if iso is None:
            continue
        out.append(
            PriceRow(
                date=iso,
                nmb95=_parse_price(row[1]),
                diesel=_parse_price(row[2]),
                elko=_parse_price(row[3]),
            )
        )
    out.sort(key=lambda r: r.date, reverse=True)
    return out


def fetch_prices(url: str = URL) -> list[PriceRow]:
    return parse_prices(fetch_html(url))


def filter_by_date(
    rows: Iterable[PriceRow],
    on: date | None = None,
    start: date | None = None,
    end: date | None = None,
) -> list[PriceRow]:
    result = []
    for r in rows:
        d = date.fromisoformat(r.date)
        if on is not None and d != on:
            continue
        if start is not None and d < start:
            continue
        if end is not None and d > end:
            continue
        result.append(r)
    return result


def _iso(s: str) -> date:
    return date.fromisoformat(s)


_HTML_TEMPLATE = """<!doctype html>
<html lang="sl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Regulirane cene naftnih derivatov</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
          margin: 0; padding: 1.5rem; max-width: 960px; margin-inline: auto;
          background: #fafafa; color: #111; }}
  h1 {{ margin: 0 0 .25rem; font-size: 1.4rem; }}
  p.meta {{ color: #666; margin: 0 0 1.25rem; font-size: .9rem; }}
  p.meta a {{ color: inherit; }}
  .controls {{ display: flex; flex-wrap: wrap; gap: .75rem; align-items: end;
               background: #fff; padding: .9rem 1rem; border-radius: 8px;
               box-shadow: 0 1px 3px rgba(0,0,0,.06); margin-bottom: 1rem; }}
  .controls label {{ display: flex; flex-direction: column; font-size: .8rem;
                     color: #444; gap: .25rem; }}
  .controls input, .controls button {{ font: inherit; padding: .4rem .6rem;
                                       border: 1px solid #ccc; border-radius: 6px;
                                       background: #fff; }}
  .controls button {{ cursor: pointer; }}
  .controls button:hover {{ background: #f0f0f0; }}
  #count {{ margin-left: auto; color: #666; font-size: .85rem; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           box-shadow: 0 1px 3px rgba(0,0,0,.06); border-radius: 8px; overflow: hidden; }}
  th, td {{ padding: .55rem .75rem; text-align: right; border-bottom: 1px solid #eee;
            font-variant-numeric: tabular-nums; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{ background: #f4f4f4; font-weight: 600; font-size: .85rem; }}
  tr:last-child td {{ border-bottom: 0; }}
  tr:hover td {{ background: #fafafa; }}
  td.na {{ color: #999; }}
  td.up {{ color: #c62828; }}
  td.down {{ color: #2e7d32; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #111; color: #eee; }}
    .controls, table {{ background: #1c1c1c; box-shadow: none; }}
    .controls input, .controls button {{ background: #222; color: #eee; border-color: #333; }}
    th {{ background: #222; }}
    th, td {{ border-color: #2a2a2a; }}
    tr:hover td {{ background: #1f1f1f; }}
    p.meta, #count {{ color: #999; }}
    td.up {{ color: #ef5350; }}
    td.down {{ color: #66bb6a; }}
  }}
</style>
</head>
<body>
<h1>Regulirane cene naftnih derivatov</h1>
<p class="meta">Vir: <a href="{source_url}" target="_blank" rel="noopener">energetika-portal.si</a>
&middot; osveženo {generated_at}</p>

<div class="controls">
  <label>Od <input type="date" id="from" min="{min_date}" max="{max_date}"></label>
  <label>Do <input type="date" id="to" min="{min_date}" max="{max_date}"></label>
  <button id="reset" type="button">Ponastavi</button>
  <span id="count"></span>
</div>

<table>
  <thead>
    <tr>
      <th>Datum</th>
      <th>NMB-95 (EUR/L)</th>
      <th>NMB-95 &Delta;%</th>
      <th>Dizel (EUR/L)</th>
      <th>ELKO (EUR/L)</th>
    </tr>
  </thead>
  <tbody id="rows"></tbody>
</table>

<script id="data" type="application/json">{data_json}</script>
<script>
  const data = JSON.parse(document.getElementById('data').textContent);
  for (let i = 0; i < data.length; i++) {{
    const cur = data[i].nmb95, prev = i + 1 < data.length ? data[i + 1].nmb95 : null;
    data[i].nmb95Change = (cur != null && prev != null && prev !== 0)
      ? (cur - prev) / prev * 100 : null;
  }}
  const tbody = document.getElementById('rows');
  const fromInput = document.getElementById('from');
  const toInput = document.getElementById('to');
  const countEl = document.getElementById('count');
  const fmt = v => v == null ? '<td class="na">&mdash;</td>' : `<td>${{v.toFixed(3)}}</td>`;
  const fmtChange = v => {{
    if (v == null) return '<td class="na">&mdash;</td>';
    const cls = v > 0 ? 'up' : v < 0 ? 'down' : '';
    const sign = v > 0 ? '+' : '';
    return `<td class="${{cls}}">${{sign}}${{v.toFixed(2)}}%</td>`;
  }};
  function render() {{
    const f = fromInput.value, t = toInput.value;
    const rows = data.filter(r => (!f || r.date >= f) && (!t || r.date <= t));
    tbody.innerHTML = rows.map(r =>
      `<tr><td>${{r.date}}</td>${{fmt(r.nmb95)}}${{fmtChange(r.nmb95Change)}}${{fmt(r.diesel)}}${{fmt(r.elko)}}</tr>`
    ).join('');
    countEl.textContent = `${{rows.length}} / ${{data.length}} zapisov`;
  }}
  fromInput.addEventListener('input', render);
  toInput.addEventListener('input', render);
  document.getElementById('reset').addEventListener('click', () => {{
    fromInput.value = ''; toInput.value = ''; render();
  }});
  render();
</script>
</body>
</html>
"""


def render_html(rows: list[PriceRow], source_url: str = URL) -> str:
    payload = [asdict(r) for r in rows]
    dates = [r.date for r in rows]
    return _HTML_TEMPLATE.format(
        source_url=html.escape(source_url),
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        min_date=min(dates) if dates else "",
        max_date=max(dates) if dates else "",
        data_json=json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", type=_iso, help="Exact effective date (YYYY-MM-DD)")
    ap.add_argument("--from", dest="start", type=_iso, help="Range start (inclusive)")
    ap.add_argument("--to", dest="end", type=_iso, help="Range end (inclusive)")
    ap.add_argument("--json", action="store_true", help="Output JSON instead of a table")
    ap.add_argument("--limit", type=int, help="Show at most N rows (after filtering)")
    ap.add_argument(
        "--build-html",
        metavar="PATH",
        help="Write a self-contained HTML report to PATH (uses unfiltered dataset)",
    )
    args = ap.parse_args(argv)

    rows = fetch_prices()

    if args.build_html:
        with open(args.build_html, "w", encoding="utf-8") as f:
            f.write(render_html(rows))
        print(f"Wrote {args.build_html} ({len(rows)} rows)")
        return 0

    rows = filter_by_date(rows, on=args.date, start=args.start, end=args.end)
    if args.limit is not None:
        rows = rows[: args.limit]

    if args.json:
        json.dump([asdict(r) for r in rows], sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"{'date':<12} {'NMB-95':>8} {'diesel':>8} {'ELKO':>8}")
    for r in rows:
        def fmt(v: float | None) -> str:
            return "—" if v is None else f"{v:.3f}"
        print(f"{r.date:<12} {fmt(r.nmb95):>8} {fmt(r.diesel):>8} {fmt(r.elko):>8}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
