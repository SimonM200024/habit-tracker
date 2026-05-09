"""Scrape regulated petroleum-derivative prices from energetika-portal.si.

Source page lists effective dates and EUR/liter prices for NMB-95 petrol,
diesel, and extra-light heating oil (ELKO) from 2007 onward.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date, datetime
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", type=_iso, help="Exact effective date (YYYY-MM-DD)")
    ap.add_argument("--from", dest="start", type=_iso, help="Range start (inclusive)")
    ap.add_argument("--to", dest="end", type=_iso, help="Range end (inclusive)")
    ap.add_argument("--json", action="store_true", help="Output JSON instead of a table")
    ap.add_argument("--limit", type=int, help="Show at most N rows (after filtering)")
    args = ap.parse_args(argv)

    rows = fetch_prices()
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
