"""Persist run snapshots and detect fare drops / deals vs the previous run."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import FareOffer
from .search import RunResult


def _history_dir(data_dir: Path, name: str) -> Path:
    return data_dir / "history" / name


def _latest_path(data_dir: Path, name: str) -> Path:
    return data_dir / "latest" / f"{name}.json"


def load_latest(data_dir: str | Path, name: str) -> dict | None:
    """Return the previous run's serialized RunResult dict, or None."""
    path = _latest_path(Path(data_dir), name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def save_run(result: RunResult, data_dir: str | Path) -> tuple[Path, Path]:
    """Write a dated snapshot and update latest.json. Returns (snapshot, latest)."""
    data_dir = Path(data_dir)
    hist = _history_dir(data_dir, result.config_name)
    hist.mkdir(parents=True, exist_ok=True)
    latest = _latest_path(data_dir, result.config_name)
    latest.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(result.to_dict(), indent=2)
    stamp = result.generated_at.strftime("%Y-%m-%dT%H%M%SZ")
    snapshot = hist / f"{stamp}.json"
    snapshot.write_text(payload, encoding="utf-8")
    latest.write_text(payload, encoding="utf-8")
    return snapshot, latest


@dataclass
class CabinChange:
    cabin: str
    airline: str
    price: float
    currency: str
    source: str
    prev_price: float | None
    delta: float | None          # price - prev_price (negative == cheaper)
    is_drop: bool
    is_new: bool                 # no prior price for this cabin
    is_deal: bool                # price <= target_price
    offer: FareOffer

    @property
    def pct_change(self) -> float | None:
        if self.prev_price in (None, 0):
            return None
        return round((self.delta / self.prev_price) * 100, 1)


def compute_changes(
    previous: dict | None,
    result: RunResult,
    target_price: float | None,
) -> list[CabinChange]:
    """Compare current best-per-cabin against the previous run."""
    prev_best = (previous or {}).get("best_by_cabin", {}) if previous else {}
    changes: list[CabinChange] = []

    for cabin, offer in sorted(result.best_by_cabin.items()):
        prev_entry = prev_best.get(cabin)
        prev_price = float(prev_entry["price"]) if prev_entry else None
        delta = (offer.price - prev_price) if prev_price is not None else None
        changes.append(
            CabinChange(
                cabin=cabin,
                airline=offer.airline,
                price=offer.price,
                currency=offer.currency,
                source=offer.source,
                prev_price=prev_price,
                delta=delta,
                is_drop=delta is not None and delta < 0,
                is_new=prev_price is None,
                is_deal=target_price is not None and offer.price <= target_price,
                offer=offer,
            )
        )
    return changes


def has_drops(changes: list[CabinChange]) -> bool:
    return any(c.is_drop for c in changes)


def has_deals(changes: list[CabinChange]) -> bool:
    return any(c.is_deal for c in changes)
