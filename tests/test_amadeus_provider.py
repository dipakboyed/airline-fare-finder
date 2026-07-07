import json
from datetime import date
from pathlib import Path

import responses

from farefinder.config import SearchConfig, Sampling
from farefinder.providers.amadeus import AmadeusClient, parse_amadeus_offers

FIXTURE = Path(__file__).parent / "fixtures" / "amadeus_sea_ccu.json"

COMMON = dict(
    origin="SEA",
    destination="CCU",
    depart_date=date(2026, 7, 21),
    return_date=date(2026, 8, 4),
    cabin="ECONOMY",
    preferred_airlines=("SQ", "EK", "QR"),
    max_stops=1,
)


def load_raw():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_cfg():
    return SearchConfig(
        name="t", origin="SEA", destination="CCU", max_stops=1,
        depart_from=date(2026, 7, 21), depart_to=date(2026, 7, 21),
        trip_min_days=10, trip_max_days=20, cabins=("ECONOMY",),
        preferred_airlines=("SQ", "EK", "QR"), passengers=1, currency="USD",
        target_price_usd=1500.0, sampling=Sampling(1, 2), amadeus_max_calls_per_run=15,
        alert_policy="only_drops",
    )


def test_contract_offers_well_formed():
    offers = parse_amadeus_offers(load_raw(), **COMMON)
    assert offers
    for o in offers:
        assert o.is_well_formed()
        assert o.source == "amadeus"
        assert o.max_stops <= 1


def test_ground_truth_parsed_matches_raw():
    # Parsed values must equal the source-of-truth fields in the raw payload.
    raw = load_raw()
    by_airline = {o.airline: o for o in parse_amadeus_offers(raw, **COMMON)}
    raw_by_airline = {r["validatingAirlineCodes"][0]: r for r in raw["data"]}

    for code in ("QR", "EK"):
        o = by_airline[code]
        r = raw_by_airline[code]
        assert o.price == float(r["price"]["grandTotal"])
        assert o.currency == r["price"]["currency"]
        assert o.stops_out == len(r["itineraries"][0]["segments"]) - 1
        assert o.stops_ret == len(r["itineraries"][1]["segments"]) - 1


def test_max_stops_filters_two_stop_offer():
    # UA offer has 2 stops each way -> excluded at max_stops=1.
    offers = parse_amadeus_offers(load_raw(), **COMMON)
    assert "UA" not in {o.airline for o in offers}


def test_preferred_airline_filter_excludes_ua_even_when_stops_ok():
    offers = parse_amadeus_offers(load_raw(), **{**COMMON, "max_stops": 3})
    assert {o.airline for o in offers} == {"QR", "EK"}  # UA not preferred


def test_missing_price_and_empty_data_do_not_raise():
    assert parse_amadeus_offers({"data": []}, **COMMON) == []
    assert parse_amadeus_offers({}, **COMMON) == []
    broken = {"data": [{"validatingAirlineCodes": ["QR"], "itineraries": [{"segments": [{}]}]}]}
    assert parse_amadeus_offers(broken, **COMMON) == []  # no price -> skipped


@responses.activate
def test_client_search_pair_mocks_token_and_offers():
    host = "https://api.amadeus.com"
    responses.add(
        responses.POST, f"{host}/v1/security/oauth2/token",
        json={"access_token": "tok123", "expires_in": 1799}, status=200,
    )
    responses.add(
        responses.GET, f"{host}/v2/shopping/flight-offers",
        json=load_raw(), status=200,
    )
    client = AmadeusClient(client_id="id", client_secret="secret", env="production")
    offers = client.search_pair(make_cfg(), date(2026, 7, 21), date(2026, 8, 4), "ECONOMY")
    assert {o.airline for o in offers} == {"QR", "EK"}
    # token endpoint hit once, offers once
    assert len(responses.calls) == 2
