"""Orchestrate a fare search: Google breadth sweep + Amadeus confirmation.

Strategy (quota-aware):
  1. Google Flights sweeps the full (date-pair x cabin) matrix cheaply.
  2. The cheapest Google candidates per cabin are re-checked against Amadeus,
     up to `amadeus_max_calls_per_run` (free-tier quota guard).
  3. Best fare per cabin prefers Amadeus (authoritative) when available,
     else falls back to the cheapest Google offer.
If Google returns nothing (e.g. blocked in CI), we fall back to sampling the
matrix directly against Amadeus within the same call budget.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from .config import SearchConfig
from .dates import generate_date_matrix
from .models import FareOffer, utcnow
from .providers.amadeus import AmadeusClient
from .providers.google_flights import GoogleFlightsProvider


def best_per_cabin(offers: list[FareOffer], prefer_source: str = "amadeus") -> dict[str, FareOffer]:
    """Cheapest offer per cabin, preferring `prefer_source` when present."""
    by_cabin: dict[str, list[FareOffer]] = {}
    for o in offers:
        by_cabin.setdefault(o.cabin, []).append(o)
    best: dict[str, FareOffer] = {}
    for cabin, group in by_cabin.items():
        preferred = [o for o in group if o.source == prefer_source]
        pool = preferred or group
        best[cabin] = min(pool, key=lambda o: o.price)
    return best


def _top_candidates(offers: list[FareOffer], cabins, top_n: int) -> list[tuple[date, date, str]]:
    """Cheapest (depart, return, cabin) combos per cabin from Google results."""
    seen: set[tuple[date, date, str]] = set()
    ordered: list[tuple[date, date, str]] = []
    for cabin in cabins:
        cabin_offers = sorted((o for o in offers if o.cabin == cabin), key=lambda o: o.price)
        for o in cabin_offers[:top_n]:
            key = (o.depart_date, o.return_date, cabin)
            if key not in seen:
                seen.add(key)
                ordered.append(key)
    return ordered


def _fallback_candidates(matrix: list[tuple[date, date]], cabins, budget: int) -> list[tuple[date, date, str]]:
    """Evenly sample the matrix across cabins when Google yields nothing."""
    cabins = list(cabins)
    if not matrix or not cabins or budget <= 0:
        return []
    per_cabin = max(budget // len(cabins), 1)
    step = max(len(matrix) // per_cabin, 1)
    sampled = matrix[::step][:per_cabin]
    out: list[tuple[date, date, str]] = []
    for cabin in cabins:
        for dep, ret in sampled:
            out.append((dep, ret, cabin))
    return out[:budget]


@dataclass
class RunResult:
    config_name: str
    origin: str
    destination: str
    generated_at: datetime
    best_by_cabin: dict[str, FareOffer]
    all_offers: list[FareOffer]
    amadeus_calls: int
    google_offer_count: int
    date_pairs: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "config_name": self.config_name,
            "origin": self.origin,
            "destination": self.destination,
            "generated_at": self.generated_at.isoformat(),
            "best_by_cabin": {c: o.to_dict() for c, o in self.best_by_cabin.items()},
            "all_offers": [o.to_dict() for o in self.all_offers],
            "amadeus_calls": self.amadeus_calls,
            "google_offer_count": self.google_offer_count,
            "date_pairs": self.date_pairs,
            "notes": self.notes,
        }


def run_search(
    cfg: SearchConfig,
    google: GoogleFlightsProvider | None = None,
    amadeus: AmadeusClient | None = None,
    top_n: int = 3,
) -> RunResult:
    google = google or GoogleFlightsProvider()
    amadeus = amadeus or AmadeusClient()

    matrix = generate_date_matrix(cfg)
    notes: list[str] = []

    google_offers = google.search(cfg, matrix, cfg.cabins)
    all_offers: list[FareOffer] = list(google_offers)
    if not google_offers:
        notes.append("google returned no offers (possibly blocked); relying on Amadeus")

    amadeus_calls = 0
    budget = cfg.amadeus_max_calls_per_run
    if amadeus.configured and budget > 0:
        if google_offers:
            candidates = _top_candidates(google_offers, cfg.cabins, top_n)
        else:
            candidates = _fallback_candidates(matrix, cfg.cabins, budget)
        for dep, ret, cabin in candidates:
            if amadeus_calls >= budget:
                break
            amadeus_calls += 1
            try:
                all_offers.extend(amadeus.search_pair(cfg, dep, ret, cabin))
            except Exception as exc:  # noqa: BLE001 - provider failures shouldn't kill the run
                notes.append(f"amadeus error for {dep}->{ret} {cabin}: {exc}")
    elif not amadeus.configured:
        notes.append("amadeus not configured; results are Google-only (unverified)")

    return RunResult(
        config_name=cfg.name,
        origin=cfg.origin,
        destination=cfg.destination,
        generated_at=utcnow(),
        best_by_cabin=best_per_cabin(all_offers),
        all_offers=all_offers,
        amadeus_calls=amadeus_calls,
        google_offer_count=len(google_offers),
        date_pairs=len(matrix),
        notes=notes,
    )
