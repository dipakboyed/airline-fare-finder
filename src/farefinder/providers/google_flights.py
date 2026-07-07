"""Google Flights provider via `fast-flights`.

We fetch the HTML with fast-flights but parse the embedded JSON ourselves,
defensively — the library's own parser crashes on itineraries whose price is
hidden by Google. Google is our per-cabin source; Travelpayouts cross-checks
economy.

Round-trip note: Google returns outbound itineraries with a *total round-trip*
price. The return leg's segments aren't exposed until you pick an outbound, so
`stops_ret` mirrors `stops_out` (both legs are constrained to <= max_stops by
the query anyway). Travelpayouts supplies per-leg transfer counts.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from datetime import date, datetime
from typing import Iterable

from ..config import SearchConfig
from ..models import FareOffer, utcnow

# Lazy import so unit tests that only exercise the pure parser don't need the
# network stack (primp/selectolax) to be importable.
SEAT_MAP = {
    "ECONOMY": "economy",
    "PREMIUM_ECONOMY": "premium-economy",
    "BUSINESS": "business",
    "FIRST": "first",
}


def google_flights_url(origin: str, destination: str, depart: date, ret: date, cabin: str) -> str:
    """A stable, well-formed Google Flights search URL for the itinerary."""
    seat = SEAT_MAP.get(cabin, "economy").replace("-", " ")
    q = (
        f"Flights from {origin} to {destination} on {depart.isoformat()} "
        f"through {ret.isoformat()} {seat}"
    )
    return "https://www.google.com/travel/flights?q=" + urllib.parse.quote(q)


def _safe_price(k) -> float | None:
    try:
        price = k[1][0][1]
    except (IndexError, TypeError, KeyError):
        return None
    if not isinstance(price, (int, float)) or price <= 0:
        return None
    return float(price)


def parse_itineraries(
    items,
    *,
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date,
    cabin: str,
    currency: str,
    preferred_airlines: Iterable[str] = (),
    max_stops: int | None = None,
    fetched_at: datetime | None = None,
) -> list[FareOffer]:
    """Turn Google's `payload[3][0]` itinerary list into FareOffers.

    Pure function (no I/O) so it can be tested against a recorded fixture.
    Malformed itineraries are skipped, never raised.
    """
    fetched_at = fetched_at or utcnow()
    preferred = {a.upper() for a in preferred_airlines}
    offers: list[FareOffer] = []

    for k in items or []:
        try:
            flight = k[0]
            code = flight[0]
            if isinstance(code, list):
                code = code[0] if code else None
            if not isinstance(code, str) or not code:
                continue
            code = code.upper()

            price = _safe_price(k)
            if price is None:
                continue

            segments = flight[2] or []
            stops = max(len(segments) - 1, 0)
            if max_stops is not None and stops > max_stops:
                continue
            if preferred and code not in preferred:
                continue

            offers.append(
                FareOffer(
                    origin=origin,
                    destination=destination,
                    depart_date=depart_date,
                    return_date=return_date,
                    cabin=cabin,
                    airline=code,
                    price=price,
                    currency=currency,
                    stops_out=stops,
                    stops_ret=stops,
                    source="google",
                    booking_url=google_flights_url(origin, destination, depart_date, return_date, cabin),
                    fetched_at=fetched_at,
                )
            )
        except (IndexError, TypeError, KeyError, ValueError):
            continue

    return offers


def extract_items_from_html(html: str) -> list:
    """Pull `payload[3][0]` (the itinerary list) out of the Google response HTML."""
    from selectolax.lexbor import LexborHTMLParser

    parser = LexborHTMLParser(html)
    script = parser.css_first(r"script.ds\:1")
    if script is None:
        return []
    js = script.text()
    try:
        data = js.split("data:", 1)[1].rsplit(",", 1)[0]
        payload = json.loads(data)
        items = payload[3][0]
    except (IndexError, TypeError, ValueError):
        return []
    return items or []


class GoogleFlightsProvider:
    """Breadth scanner: fetch fares for each (date-pair, cabin) via Google Flights."""

    name = "google"

    def __init__(self, request_delay_s: float = 1.0):
        self.request_delay_s = request_delay_s

    def _fetch_html(self, cfg: SearchConfig, depart: date, ret: date, cabin: str) -> str:
        from fast_flights import FlightQuery, Passengers, create_filter, fetch_flights_html

        flights = [
            FlightQuery(date=depart.isoformat(), from_airport=cfg.origin, to_airport=cfg.destination, max_stops=cfg.max_stops),
            FlightQuery(date=ret.isoformat(), from_airport=cfg.destination, to_airport=cfg.origin, max_stops=cfg.max_stops),
        ]
        query = create_filter(
            flights=flights,
            seat=SEAT_MAP.get(cabin, "economy"),
            trip="round-trip",
            passengers=Passengers(adults=cfg.passengers),
            currency=cfg.currency,
            max_stops=cfg.max_stops,
        )
        return fetch_flights_html(query)

    def search_pair(self, cfg: SearchConfig, depart: date, ret: date, cabin: str) -> list[FareOffer]:
        try:
            html = self._fetch_html(cfg, depart, ret, cabin)
        except Exception:
            return []
        items = extract_items_from_html(html)
        return parse_itineraries(
            items,
            origin=cfg.origin,
            destination=cfg.destination,
            depart_date=depart,
            return_date=ret,
            cabin=cabin,
            currency=cfg.currency,
            preferred_airlines=cfg.preferred_airlines,
            max_stops=cfg.max_stops,
        )

    def search(self, cfg: SearchConfig, date_pairs: list[tuple[date, date]], cabins: Iterable[str]) -> list[FareOffer]:
        offers: list[FareOffer] = []
        for cabin in cabins:
            for depart, ret in date_pairs:
                offers.extend(self.search_pair(cfg, depart, ret, cabin))
                if self.request_delay_s:
                    time.sleep(self.request_delay_s)
        return offers
