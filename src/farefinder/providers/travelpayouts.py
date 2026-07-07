"""Travelpayouts (Aviasales) cross-check provider — free, no per-call quota.

Uses the Flight Data v3 `prices_for_dates` endpoint. This is a *cached* fare
source (cheapest tickets other users recently found) and has **no cabin
parameter**, so it cross-checks the ECONOMY cabin only. Google Flights remains
the per-cabin source. Booking links are real Aviasales links (with your marker).

Env vars:
  TRAVELPAYOUTS_TOKEN   (required for live calls)
  TRAVELPAYOUTS_MARKER  (optional affiliate id appended to booking links)
"""
from __future__ import annotations

import os
from datetime import date, datetime

import requests

from ..config import SearchConfig
from ..models import FareOffer, utcnow

_HOST = "https://api.travelpayouts.com"
_AVIASALES = "https://www.aviasales.com"


class TravelpayoutsError(RuntimeError):
    pass


def booking_link(raw_link: str | None, marker: str | None) -> str:
    """Build a full Aviasales booking URL from the API's (often relative) link."""
    link = raw_link or "/"
    if not link.startswith("http"):
        link = _AVIASALES + link
    if marker:
        sep = "&" if "?" in link else "?"
        link = f"{link}{sep}marker={marker}"
    return link


def parse_prices_for_dates(
    data: dict,
    *,
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date,
    cabin: str = "ECONOMY",
    preferred_airlines=(),
    max_stops: int | None = None,
    marker: str | None = None,
    fetched_at: datetime | None = None,
) -> list[FareOffer]:
    """Turn a `prices_for_dates` response into FareOffers (pure, testable)."""
    fetched_at = fetched_at or utcnow()
    preferred = {a.upper() for a in preferred_airlines}
    offers: list[FareOffer] = []

    for row in data.get("data", []) or []:
        try:
            airline = str(row.get("airline") or "").upper()
            if not airline:
                continue
            if preferred and airline not in preferred:
                continue

            stops_out = int(row.get("transfers", 0) or 0)
            stops_ret = int(row.get("return_transfers", row.get("transfers", 0)) or 0)
            if max_stops is not None and max(stops_out, stops_ret) > max_stops:
                continue

            raw_price = row.get("price")
            if raw_price is None:
                continue
            price = float(raw_price)
            if price <= 0:
                continue
            currency = str(data.get("currency") or "USD").upper()

            offers.append(
                FareOffer(
                    origin=origin,
                    destination=destination,
                    depart_date=depart_date,
                    return_date=return_date,
                    cabin=cabin,
                    airline=airline,
                    price=price,
                    currency=currency,
                    stops_out=stops_out,
                    stops_ret=stops_ret,
                    source="travelpayouts",
                    booking_url=booking_link(row.get("link"), marker),
                    fetched_at=fetched_at,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue

    return offers


class TravelpayoutsProvider:
    """ECONOMY cross-check via Travelpayouts prices_for_dates."""

    name = "travelpayouts"
    supported_cabins = ("ECONOMY",)

    def __init__(
        self,
        token: str | None = None,
        marker: str | None = None,
        session: requests.Session | None = None,
        timeout: float = 20.0,
    ):
        self.token = token or os.environ.get("TRAVELPAYOUTS_TOKEN", "")
        self.marker = marker or os.environ.get("TRAVELPAYOUTS_MARKER", "")
        self.session = session or requests.Session()
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.token)

    def _search_raw(self, cfg: SearchConfig, depart: date, ret: date, limit: int = 30) -> dict:
        transfers = ",".join(str(n) for n in range(0, cfg.max_stops + 1))
        params = {
            "origin": cfg.origin,
            "destination": cfg.destination,
            "departure_at": depart.isoformat(),
            "return_at": ret.isoformat(),
            "currency": cfg.currency.lower(),
            "transfers": transfers,
            "one_way": "false",
            "limit": limit,
            "sorting": "price",
            "token": self.token,
        }
        resp = self.session.get(
            f"{_HOST}/aviasales/v3/prices_for_dates",
            params=params,
            headers={"X-Access-Token": self.token},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise TravelpayoutsError(f"prices_for_dates failed: {resp.status_code} {resp.text[:300]}")
        body = resp.json()
        if not body.get("success", True):
            raise TravelpayoutsError(f"prices_for_dates error: {body.get('error') or body}")
        return body

    def search_pair(self, cfg: SearchConfig, depart: date, ret: date, cabin: str = "ECONOMY") -> list[FareOffer]:
        # Travelpayouts is economy-only; ignore other cabins.
        if cabin != "ECONOMY":
            return []
        data = self._search_raw(cfg, depart, ret)
        return parse_prices_for_dates(
            data,
            origin=cfg.origin,
            destination=cfg.destination,
            depart_date=depart,
            return_date=ret,
            cabin="ECONOMY",
            preferred_airlines=cfg.preferred_airlines,
            max_stops=cfg.max_stops,
            marker=self.marker,
        )
