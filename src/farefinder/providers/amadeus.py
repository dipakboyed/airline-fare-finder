"""Amadeus Self-Service provider — authoritative fares.

Uses the Flight Offers Search API. Amadeus has no "max stops" filter (only a
`nonStop` boolean), so we request offers and filter to `<= max_stops`
client-side. Token is cached and refreshed on expiry.

Env vars:
  AMADEUS_CLIENT_ID, AMADEUS_CLIENT_SECRET  (required for live calls)
  AMADEUS_ENV = "production" (default) | "test"
"""
from __future__ import annotations

import os
import time
from datetime import date, datetime
from typing import Iterable

import requests

from ..config import SearchConfig
from ..models import FareOffer, utcnow
from .google_flights import google_flights_url

_HOSTS = {
    "production": "https://api.amadeus.com",
    "test": "https://test.api.amadeus.com",
}


class AmadeusError(RuntimeError):
    pass


def _to_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _itinerary_stops(itinerary: dict) -> int:
    segments = itinerary.get("segments") or []
    return max(len(segments) - 1, 0)


def parse_amadeus_offers(
    data: dict,
    *,
    origin: str,
    destination: str,
    depart_date: date,
    return_date: date,
    cabin: str,
    preferred_airlines: Iterable[str] = (),
    max_stops: int | None = None,
    fetched_at: datetime | None = None,
) -> list[FareOffer]:
    """Turn a raw Flight Offers Search response into FareOffers.

    Pure function (no I/O) so it can be tested against a recorded fixture and
    ground-truth-checked against the raw payload.
    """
    fetched_at = fetched_at or utcnow()
    preferred = {a.upper() for a in preferred_airlines}
    offers: list[FareOffer] = []

    for offer in data.get("data", []) or []:
        try:
            itineraries = offer.get("itineraries") or []
            if not itineraries:
                continue
            stops_out = _itinerary_stops(itineraries[0])
            stops_ret = _itinerary_stops(itineraries[1]) if len(itineraries) > 1 else 0
            if max_stops is not None and max(stops_out, stops_ret) > max_stops:
                continue

            validating = offer.get("validatingAirlineCodes") or []
            if validating:
                airline = str(validating[0]).upper()
            else:
                airline = str(itineraries[0]["segments"][0]["carrierCode"]).upper()
            if preferred and airline not in preferred:
                continue

            price_block = offer.get("price") or {}
            raw_price = price_block.get("grandTotal") or price_block.get("total")
            if raw_price is None:
                continue
            price = float(raw_price)
            if price <= 0:
                continue
            currency = str(price_block.get("currency") or "USD").upper()

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
                    source="amadeus",
                    booking_url=google_flights_url(origin, destination, depart_date, return_date, cabin),
                    fetched_at=fetched_at,
                )
            )
        except (KeyError, IndexError, TypeError, ValueError):
            continue

    return offers


class AmadeusClient:
    """Thin Flight Offers Search client with token caching."""

    name = "amadeus"

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        env: str | None = None,
        session: requests.Session | None = None,
        timeout: float = 20.0,
    ):
        self.client_id = client_id or os.environ.get("AMADEUS_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("AMADEUS_CLIENT_SECRET", "")
        self.env = (env or os.environ.get("AMADEUS_ENV") or "production").lower()
        self.host = _HOSTS.get(self.env, _HOSTS["production"])
        self.session = session or requests.Session()
        self.timeout = timeout
        self._token: str | None = None
        self._token_expiry: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - 30:
            return self._token
        resp = self.session.post(
            f"{self.host}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise AmadeusError(f"token request failed: {resp.status_code} {resp.text[:200]}")
        body = resp.json()
        self._token = body["access_token"]
        self._token_expiry = time.time() + _to_int(body.get("expires_in"), 1799)
        return self._token

    def _search_raw(self, cfg: SearchConfig, depart: date, ret: date, cabin: str, max_offers: int = 5) -> dict:
        token = self._get_token()
        params = {
            "originLocationCode": cfg.origin,
            "destinationLocationCode": cfg.destination,
            "departureDate": depart.isoformat(),
            "returnDate": ret.isoformat(),
            "adults": cfg.passengers,
            "travelClass": cabin,
            "currencyCode": cfg.currency,
            "max": max_offers,
        }
        if cfg.preferred_airlines:
            params["includedAirlineCodes"] = ",".join(cfg.preferred_airlines)
        resp = self.session.get(
            f"{self.host}/v2/shopping/flight-offers",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise AmadeusError(f"flight-offers failed: {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def search_pair(self, cfg: SearchConfig, depart: date, ret: date, cabin: str, max_offers: int = 5) -> list[FareOffer]:
        data = self._search_raw(cfg, depart, ret, cabin, max_offers=max_offers)
        return parse_amadeus_offers(
            data,
            origin=cfg.origin,
            destination=cfg.destination,
            depart_date=depart,
            return_date=ret,
            cabin=cabin,
            preferred_airlines=cfg.preferred_airlines,
            max_stops=cfg.max_stops,
        )
