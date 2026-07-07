import json
from datetime import date
from pathlib import Path

from farefinder.models import FareOffer
from farefinder.providers.google_flights import (
    google_flights_url,
    parse_itineraries,
)

FIXTURE = Path(__file__).parent / "fixtures" / "google_sea_ccu_items.json"

COMMON = dict(
    origin="SEA",
    destination="CCU",
    depart_date=date(2026, 7, 21),
    return_date=date(2026, 8, 4),
    cabin="ECONOMY",
    currency="USD",
    preferred_airlines=("SQ", "EK", "QR"),
    max_stops=1,
)


def load_items():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_parses_to_well_formed_offers():
    offers = parse_itineraries(load_items(), **COMMON)
    assert offers, "expected at least one offer from fixture"
    for o in offers:
        assert isinstance(o, FareOffer)
        assert o.is_well_formed(), f"malformed: {o}"
        assert o.airline in {"SQ", "EK", "QR"}
        assert o.max_stops <= 1
        assert o.currency == "USD"
        assert o.source == "google"
        assert o.booking_url.startswith("https://www.google.com/travel/flights")


def test_fixture_expected_carriers_and_prices():
    # Fixture holds QR ($1783) and EK ($2661); SQ has a hidden price -> skipped.
    offers = {o.airline: o for o in parse_itineraries(load_items(), **COMMON)}
    assert "QR" in offers and offers["QR"].price == 1783.0
    assert "EK" in offers and offers["EK"].price == 2661.0
    assert "SQ" not in offers  # price hidden by Google -> must be dropped, not crash


def test_preferred_airline_filter():
    offers = parse_itineraries(load_items(), **{**COMMON, "preferred_airlines": ("QR",)})
    assert {o.airline for o in offers} == {"QR"}


def test_max_stops_filter_excludes_too_many():
    offers = parse_itineraries(load_items(), **{**COMMON, "max_stops": 0})
    assert offers == []  # all fixture itineraries have 1 stop


def test_empty_and_garbage_items_do_not_raise():
    assert parse_itineraries(None, **COMMON) == []
    assert parse_itineraries([], **COMMON) == []
    assert parse_itineraries([[["QR"]], [123], "junk"], **COMMON) == []


def test_google_url_is_well_formed():
    url = google_flights_url("SEA", "CCU", date(2026, 7, 21), date(2026, 8, 4), "BUSINESS")
    assert url.startswith("https://www.google.com/travel/flights?q=")
    assert "SEA" in url and "CCU" in url
