"""Domain models shared across providers and the orchestrator."""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone

VALID_CABINS = {"ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"}
_IATA_CODE_RE = re.compile(r"^[A-Z0-9]{2}$")   # airline codes: 2 alphanumeric
_AIRPORT_RE = re.compile(r"^[A-Z]{3}$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class FareOffer:
    """A single priced round-trip itinerary for one cabin."""

    origin: str
    destination: str
    depart_date: date
    return_date: date
    cabin: str
    airline: str            # validating / primary marketing carrier (IATA)
    price: float
    currency: str
    stops_out: int
    stops_ret: int
    source: str             # "google" | "travelpayouts"
    booking_url: str
    fetched_at: datetime

    @property
    def max_stops(self) -> int:
        return max(self.stops_out, self.stops_ret)

    @property
    def trip_length_days(self) -> int:
        return (self.return_date - self.depart_date).days

    def is_well_formed(self) -> bool:
        """Ground-truth structural checks used by contract tests."""
        return (
            bool(_AIRPORT_RE.match(self.origin))
            and bool(_AIRPORT_RE.match(self.destination))
            and isinstance(self.depart_date, date)
            and isinstance(self.return_date, date)
            and self.return_date > self.depart_date
            and self.cabin in VALID_CABINS
            and bool(_IATA_CODE_RE.match(self.airline))
            and isinstance(self.price, (int, float))
            and self.price > 0
            and bool(self.currency)
            and self.stops_out >= 0
            and self.stops_ret >= 0
            and self.source in {"google", "travelpayouts"}
            and self.booking_url.startswith("http")
        )

    def to_dict(self) -> dict:
        d = asdict(self)
        d["depart_date"] = self.depart_date.isoformat()
        d["return_date"] = self.return_date.isoformat()
        d["fetched_at"] = self.fetched_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FareOffer":
        return cls(
            origin=d["origin"],
            destination=d["destination"],
            depart_date=date.fromisoformat(d["depart_date"]),
            return_date=date.fromisoformat(d["return_date"]),
            cabin=d["cabin"],
            airline=d["airline"],
            price=float(d["price"]),
            currency=d["currency"],
            stops_out=int(d["stops_out"]),
            stops_ret=int(d["stops_ret"]),
            source=d["source"],
            booking_url=d["booking_url"],
            fetched_at=datetime.fromisoformat(d["fetched_at"]),
        )
