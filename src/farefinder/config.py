"""Load and validate a trip search configuration from YAML."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import yaml

from .models import VALID_CABINS

_REL_RE = re.compile(r"^\+(\d+)d$")
_AIRPORT_RE = re.compile(r"^[A-Z]{3}$")
_AIRLINE_RE = re.compile(r"^[A-Z0-9]{2}$")

ALERT_POLICIES = {"every_run", "only_target", "only_drops", "every_run_plus_drops"}


class ConfigError(ValueError):
    """Raised when a search config is missing or invalid."""


def _resolve_date(token, today: date) -> date:
    """Resolve 'today', '+Nd', or an ISO date string/date to a concrete date."""
    if isinstance(token, date):
        return token
    if not isinstance(token, str):
        raise ConfigError(f"date token must be a string or date, got {token!r}")
    token = token.strip()
    if token == "today":
        return today
    m = _REL_RE.match(token)
    if m:
        return today + timedelta(days=int(m.group(1)))
    try:
        return date.fromisoformat(token)
    except ValueError as exc:
        raise ConfigError(f"invalid date token {token!r}") from exc


@dataclass(frozen=True)
class Sampling:
    depart_step_days: int = 1
    trip_length_step_days: int = 1


@dataclass(frozen=True)
class SearchConfig:
    name: str
    origin: str
    destination: str
    max_stops: int
    depart_from: date
    depart_to: date
    trip_min_days: int
    trip_max_days: int
    cabins: tuple[str, ...]
    preferred_airlines: tuple[str, ...]
    passengers: int
    currency: str
    target_price_usd: float | None
    alert_policy: str
    sampling: Sampling
    crosscheck_max_calls_per_run: int
    source_path: Path | None = None

    def validate(self) -> None:
        errs = []
        if not _AIRPORT_RE.match(self.origin):
            errs.append(f"origin must be a 3-letter IATA code, got {self.origin!r}")
        if not _AIRPORT_RE.match(self.destination):
            errs.append(f"destination must be a 3-letter IATA code, got {self.destination!r}")
        if self.origin == self.destination:
            errs.append("origin and destination must differ")
        if self.max_stops < 0:
            errs.append("max_stops must be >= 0")
        if self.depart_to < self.depart_from:
            errs.append("depart_window.to must be on/after depart_window.from")
        if self.trip_min_days <= 0 or self.trip_max_days <= 0:
            errs.append("trip_length_days must be positive")
        if self.trip_max_days < self.trip_min_days:
            errs.append("trip_length_days max must be >= min")
        if not self.cabins:
            errs.append("at least one cabin required")
        bad_cabins = [c for c in self.cabins if c not in VALID_CABINS]
        if bad_cabins:
            errs.append(f"invalid cabins {bad_cabins}; allowed: {sorted(VALID_CABINS)}")
        bad_airlines = [a for a in self.preferred_airlines if not _AIRLINE_RE.match(a)]
        if bad_airlines:
            errs.append(f"invalid airline codes {bad_airlines}")
        if self.passengers < 1:
            errs.append("passengers must be >= 1")
        if not self.currency:
            errs.append("currency required")
        if self.sampling.depart_step_days < 1 or self.sampling.trip_length_step_days < 1:
            errs.append("sampling steps must be >= 1")
        if self.crosscheck_max_calls_per_run < 0:
            errs.append("crosscheck_max_calls_per_run must be >= 0")
        if self.alert_policy not in ALERT_POLICIES:
            errs.append(f"alert_policy must be one of {sorted(ALERT_POLICIES)}")
        if self.target_price_usd is not None and self.currency != "USD":
            errs.append(
                "target_price_usd is USD-denominated; set currency: USD or remove target_price_usd"
            )
        if errs:
            raise ConfigError("; ".join(errs))


def load_search_config(path: str | Path, today: date | None = None) -> SearchConfig:
    """Parse a YAML search file into a validated SearchConfig."""
    today = today or date.today()
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    try:
        window = raw.get("depart_window", {}) or {}
        trip = raw.get("trip_length_days", [10, 20])
        samp = raw.get("sampling", {}) or {}
        cfg = SearchConfig(
            name=str(raw.get("name") or path.stem),
            origin=str(raw["origin"]).upper(),
            destination=str(raw["destination"]).upper(),
            max_stops=int(raw.get("max_stops", 1)),
            depart_from=_resolve_date(window.get("from", "today"), today),
            depart_to=_resolve_date(window.get("to", "+21d"), today),
            trip_min_days=int(trip[0]),
            trip_max_days=int(trip[1]),
            cabins=tuple(str(c).upper() for c in raw.get("cabins", ["ECONOMY"])),
            preferred_airlines=tuple(str(a).upper() for a in raw.get("preferred_airlines", [])),
            passengers=int(raw.get("passengers", 1)),
            currency=str(raw.get("currency", "USD")).upper(),
            target_price_usd=(float(raw["target_price_usd"]) if raw.get("target_price_usd") is not None else None),
            alert_policy=str(raw.get("alert_policy", "only_drops")).lower(),
            sampling=Sampling(
                depart_step_days=int(samp.get("depart_step_days", 1)),
                trip_length_step_days=int(samp.get("trip_length_step_days", 1)),
            ),
            crosscheck_max_calls_per_run=int(raw.get("crosscheck_max_calls_per_run", 15)),
            source_path=path,
        )
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise ConfigError(f"malformed config {path}: {exc}") from exc

    cfg.validate()
    return cfg


def load_all_search_configs(directory: str | Path, today: date | None = None) -> list[SearchConfig]:
    """Load every *.yaml/*.yml search under a directory (future trips = new files)."""
    directory = Path(directory)
    files = sorted([*directory.glob("*.yaml"), *directory.glob("*.yml")])
    return [load_search_config(f, today=today) for f in files]
