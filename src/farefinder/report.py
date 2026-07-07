"""Build the email report (subject + HTML + plaintext) from a run's changes."""
from __future__ import annotations

import html
from datetime import date

from .config import SearchConfig
from .history import CabinChange

_CABIN_LABELS = {
    "ECONOMY": "Economy",
    "PREMIUM_ECONOMY": "Premium Economy",
    "BUSINESS": "Business",
    "FIRST": "First",
}


def _fmt_money(price: float, currency: str) -> str:
    return f"{currency} {price:,.0f}"


def _delta_str(c: CabinChange) -> str:
    if c.is_new or c.delta is None:
        return "new"
    if c.delta == 0:
        return "no change"
    arrow = "\u2193" if c.delta < 0 else "\u2191"
    pct = f" ({c.pct_change:+.1f}%)" if c.pct_change is not None else ""
    return f"{arrow} {c.currency} {abs(c.delta):,.0f}{pct}"


def build_subject(cfg: SearchConfig, changes: list[CabinChange]) -> str:
    route = f"{cfg.origin}\u2192{cfg.destination}"
    cheapest = min(changes, key=lambda c: c.price) if changes else None
    drops = [c for c in changes if c.is_drop]
    deals = [c for c in changes if c.is_deal]
    tag = "\U0001f4c9 drop" if drops else ("\U0001f525 deal" if deals else "update")
    if cheapest is None:
        return f"[fare-finder] {route}: no fares found"
    label = _CABIN_LABELS.get(cheapest.cabin, cheapest.cabin)
    return (
        f"[fare-finder] {route} {tag}: {label} {_fmt_money(cheapest.price, cheapest.currency)} "
        f"({cheapest.airline})"
    )


def build_text(cfg: SearchConfig, changes: list[CabinChange], notes: list[str]) -> str:
    route = f"{cfg.origin} -> {cfg.destination}"
    lines = [f"Fare report for {route}", ""]
    for c in sorted(changes, key=lambda c: c.price):
        label = _CABIN_LABELS.get(c.cabin, c.cabin)
        flags = []
        if c.is_deal:
            flags.append("DEAL")
        if c.is_drop:
            flags.append("DROP")
        flag = f"  [{', '.join(flags)}]" if flags else ""
        lines.append(
            f"- {label}: {_fmt_money(c.price, c.currency)} on {c.airline} "
            f"[{c.source}]  {_delta_str(c)}{flag}"
        )
        lines.append(
            f"    {c.offer.depart_date.isoformat()} -> {c.offer.return_date.isoformat()} "
            f"({c.offer.trip_length_days}d, {c.offer.max_stops} stop)  {c.offer.booking_url}"
        )
    if notes:
        lines += ["", "Notes:"] + [f"- {n}" for n in notes]
    return "\n".join(lines)


def build_html(cfg: SearchConfig, changes: list[CabinChange], notes: list[str]) -> str:
    route = f"{cfg.origin}&rarr;{cfg.destination}"
    target = (
        f'<p style="color:#555">Deal threshold: {_fmt_money(cfg.target_price_usd, cfg.currency)}</p>'
        if cfg.target_price_usd is not None
        else ""
    )
    rows = []
    for c in sorted(changes, key=lambda c: c.price):
        label = html.escape(_CABIN_LABELS.get(c.cabin, c.cabin))
        badge = ""
        if c.is_drop:
            badge += ' <span style="background:#0a7d33;color:#fff;padding:1px 6px;border-radius:4px;font-size:11px">DROP</span>'
        if c.is_deal:
            badge += ' <span style="background:#b8860b;color:#fff;padding:1px 6px;border-radius:4px;font-size:11px">DEAL</span>'
        delta_color = "#0a7d33" if c.is_drop else ("#b00" if (c.delta or 0) > 0 else "#555")
        rows.append(
            "<tr>"
            f'<td style="padding:8px;border-bottom:1px solid #eee"><b>{label}</b>{badge}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;font-size:18px"><b>{_fmt_money(c.price, c.currency)}</b></td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;color:{delta_color}">{html.escape(_delta_str(c))}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee">{html.escape(c.airline)} '
            f'<span style="color:#999;font-size:11px">({html.escape(c.source)})</span></td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;color:#555">'
            f"{c.offer.depart_date.isoformat()} &rarr; {c.offer.return_date.isoformat()}<br>"
            f'{c.offer.trip_length_days}d, {c.offer.max_stops} stop</td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee">'
            f'<a href="{html.escape(c.offer.booking_url)}">view</a></td>'
            "</tr>"
        )
    notes_html = ""
    if notes:
        items = "".join(f"<li>{html.escape(n)}</li>" for n in notes)
        notes_html = f'<p style="color:#888;font-size:12px">Notes:<ul>{items}</ul></p>'

    return f"""<html><body style="font-family:-apple-system,Segoe UI,Arial,sans-serif;color:#222">
<h2>Fare report: {route}</h2>
{target}
<table style="border-collapse:collapse;min-width:640px">
<thead><tr style="text-align:left;background:#f4f4f4">
<th style="padding:8px">Cabin</th><th style="padding:8px">Best fare</th>
<th style="padding:8px">vs last run</th><th style="padding:8px">Airline</th>
<th style="padding:8px">Dates</th><th style="padding:8px">Link</th>
</tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
{notes_html}
<p style="color:#aaa;font-size:11px">airline-fare-finder &middot; best fare per cabin (Google Flights + Travelpayouts economy cross-check)</p>
</body></html>"""
