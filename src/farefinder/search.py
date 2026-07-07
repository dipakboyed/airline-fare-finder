"""Orchestrate a fare search: Google breadth sweep + Travelpayouts cross-check.

Strategy:
  1. Google Flights sweeps the full (date-pair x cabin) matrix — the per-cabin
     source (Economy / Premium Economy / Business), real-time-ish, free.
  2. The cheapest Google ECONOMY candidates are cross-checked against
     Travelpayouts (free, no quota; economy-only cached fares), up to
     `crosscheck_max_calls_per_run`.
  3. Best fare per cabin = cheapest across all sources (min price), tagged with
     its source. Travelpayouts adds an independent economy signal + real
     Aviasales booking links.
If Google returns nothing (e.g. blocked in CI), we fall back to sampling the
matrix directly against Travelpayouts (economy) within the same budget.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from .config import SearchConfig
from .dates import generate_date_matrix
from .models import FareOffer, utcnow
from .providers.google_flights import GoogleFlightsProvider
from .providers.travelpayouts import TravelpayoutsProvider


def best_per_cabin(offers: list[FareOffer], prefer_source: str | None = None) -> dict[str, FareOffer]:
    """Cheapest offer per cabin. If `prefer_source` is set and present for a
    cabin, restrict that cabin to it; otherwise pick the cheapest across sources.
    """
    by_cabin: dict[str, list[FareOffer]] = {}
    for o in offers:
        by_cabin.setdefault(o.cabin, []).append(o)
    best: dict[str, FareOffer] = {}
    for cabin, group in by_cabin.items():
        pool = group
        if prefer_source:
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
    crosscheck_calls: int
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
            "crosscheck_calls": self.crosscheck_calls,
            "google_offer_count": self.google_offer_count,
            "date_pairs": self.date_pairs,
            "notes": self.notes,
        }


def run_search(
    cfg: SearchConfig,
    google: GoogleFlightsProvider | None = None,
    crosscheck: TravelpayoutsProvider | None = None,
    top_n: int = 3,
) -> RunResult:
    google = google or GoogleFlightsProvider()
    crosscheck = crosscheck or TravelpayoutsProvider()

    matrix = generate_date_matrix(cfg)
    notes: list[str] = []

    google_offers = google.search(cfg, matrix, cfg.cabins)
    all_offers: list[FareOffer] = list(google_offers)
    if not google_offers:
        notes.append("google returned no offers (possibly blocked); relying on cross-check")

    # Travelpayouts is economy-only, so cross-check only the ECONOMY cabin.
    econ_cabins = ["ECONOMY"] if "ECONOMY" in cfg.cabins else []
    crosscheck_calls = 0
    budget = cfg.crosscheck_max_calls_per_run
    if crosscheck.configured and budget > 0 and econ_cabins:
        if google_offers:
            candidates = _top_candidates(google_offers, econ_cabins, top_n)
        else:
            candidates = _fallback_candidates(matrix, econ_cabins, budget)
        for dep, ret, cabin in candidates:
            if crosscheck_calls >= budget:
                break
            crosscheck_calls += 1
            try:
                all_offers.extend(crosscheck.search_pair(cfg, dep, ret, cabin))
            except Exception as exc:  # noqa: BLE001 - provider failures shouldn't kill the run
                notes.append(f"crosscheck error for {dep}->{ret} {cabin}: {exc}")
    elif not crosscheck.configured:
        notes.append("cross-check (Travelpayouts) not configured; results are Google-only")

    return RunResult(
        config_name=cfg.name,
        origin=cfg.origin,
        destination=cfg.destination,
        generated_at=utcnow(),
        best_by_cabin=best_per_cabin(all_offers),
        all_offers=all_offers,
        crosscheck_calls=crosscheck_calls,
        google_offer_count=len(google_offers),
        date_pairs=len(matrix),
        notes=notes,
    )
