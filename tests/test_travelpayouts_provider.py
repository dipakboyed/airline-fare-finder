import json
from datetime import date
from pathlib import Path

import responses

from farefinder.config import SearchConfig, Sampling
from farefinder.providers.travelpayouts import (
    TravelpayoutsProvider,
    booking_link,
    parse_prices_for_dates,
)

FIXTURE = Path(__file__).parent / "fixtures" / "travelpayouts_sea_ccu.json"

COMMON = dict(
    origin="SEA",
    destination="CCU",
    depart_date=date(2026, 7, 21),
    return_date=date(2026, 8, 4),
    preferred_airlines=("SQ", "EK", "QR"),
    max_stops=1,
    marker="12345",
)


def load_raw():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_cfg():
    return SearchConfig(
        name="t", origin="SEA", destination="CCU", max_stops=1,
        depart_from=date(2026, 7, 21), depart_to=date(2026, 7, 21),
        trip_min_days=10, trip_max_days=20, cabins=("ECONOMY",),
        preferred_airlines=("SQ", "EK", "QR"), passengers=1, currency="USD",
        target_price_usd=1500.0, alert_policy="only_drops", sampling=Sampling(1, 2),
        crosscheck_max_calls_per_run=15,
    )


def test_contract_offers_well_formed():
    offers = parse_prices_for_dates(load_raw(), **COMMON)
    assert offers
    for o in offers:
        assert o.is_well_formed()
        assert o.source == "travelpayouts"
        assert o.cabin == "ECONOMY"
        assert o.max_stops <= 1


def test_ground_truth_parsed_matches_raw():
    raw = load_raw()
    by_airline = {o.airline: o for o in parse_prices_for_dates(raw, **COMMON)}
    raw_by_airline = {r["airline"]: r for r in raw["data"]}
    for code in ("QR", "EK"):
        o = by_airline[code]
        r = raw_by_airline[code]
        assert o.price == float(r["price"])
        assert o.currency == raw["currency"]
        assert o.stops_out == r["transfers"]
        assert o.stops_ret == r["return_transfers"]


def test_max_stops_excludes_two_transfer_offer():
    offers = parse_prices_for_dates(load_raw(), **COMMON)
    assert "UA" not in {o.airline for o in offers}


def test_preferred_airline_filter_excludes_ai():
    # AI has 1 transfer (stops ok) but is not in the preferred set -> excluded.
    offers = parse_prices_for_dates(load_raw(), **COMMON)
    assert {o.airline for o in offers} == {"QR", "EK"}


def test_booking_link_relative_and_absolute_with_marker():
    assert booking_link("/search/X", "99").startswith("https://www.aviasales.com/search/X")
    assert booking_link("/search/X", "99").endswith("marker=99")
    abs_link = booking_link("https://www.aviasales.com/search/Y?a=1", "99")
    assert abs_link == "https://www.aviasales.com/search/Y?a=1&marker=99"
    assert "marker" not in booking_link("/search/Z", None)


def test_missing_price_and_empty_do_not_raise():
    assert parse_prices_for_dates({"data": []}, **COMMON) == []
    assert parse_prices_for_dates({}, **COMMON) == []
    broken = {"data": [{"airline": "QR", "transfers": 1}], "currency": "USD"}  # no price
    assert parse_prices_for_dates(broken, **COMMON) == []


@responses.activate
def test_provider_search_pair_mocks_endpoint():
    responses.add(
        responses.GET,
        "https://api.travelpayouts.com/aviasales/v3/prices_for_dates",
        json=load_raw(), status=200,
    )
    provider = TravelpayoutsProvider(token="tok", marker="55")
    offers = provider.search_pair(make_cfg(), date(2026, 7, 21), date(2026, 8, 4), "ECONOMY")
    assert {o.airline for o in offers} == {"QR", "EK"}
    # token sent as query param and header
    req = responses.calls[0].request
    assert "token=tok" in req.url
    assert req.headers["X-Access-Token"] == "tok"


def test_provider_ignores_non_economy_cabin():
    provider = TravelpayoutsProvider(token="tok")
    assert provider.search_pair(make_cfg(), date(2026, 7, 21), date(2026, 8, 4), "BUSINESS") == []


def test_unconfigured_provider():
    assert TravelpayoutsProvider(token="").configured is False
