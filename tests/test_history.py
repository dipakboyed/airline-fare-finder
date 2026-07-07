from datetime import date, datetime, timezone

from farefinder.history import (
    compute_changes,
    has_deals,
    has_drops,
    load_latest,
    save_run,
)
from farefinder.models import FareOffer, utcnow
from farefinder.search import RunResult


def offer(cabin, airline, price, source="amadeus"):
    return FareOffer(
        origin="SEA", destination="CCU", depart_date=date(2026, 7, 21),
        return_date=date(2026, 8, 4), cabin=cabin, airline=airline, price=price,
        currency="USD", stops_out=1, stops_ret=1, source=source,
        booking_url="https://example.com/x", fetched_at=utcnow(),
    )


def make_result(best, when=None):
    return RunResult(
        config_name="sea-ccu", origin="SEA", destination="CCU",
        generated_at=when or datetime(2026, 7, 7, 12, 0, tzinfo=timezone.utc),
        best_by_cabin=best, all_offers=list(best.values()), amadeus_calls=2,
        google_offer_count=3, date_pairs=50,
    )


def test_save_and_load_roundtrip(tmp_path):
    result = make_result({"ECONOMY": offer("ECONOMY", "QR", 1783)})
    snapshot, latest = save_run(result, tmp_path)
    assert snapshot.exists() and latest.exists()
    loaded = load_latest(tmp_path, "sea-ccu")
    assert loaded["best_by_cabin"]["ECONOMY"]["price"] == 1783


def test_load_latest_missing_returns_none(tmp_path):
    assert load_latest(tmp_path, "nope") is None


def test_first_run_all_new_no_drops(tmp_path):
    result = make_result({"ECONOMY": offer("ECONOMY", "QR", 1783)})
    changes = compute_changes(None, result, target_price=1500)
    assert changes[0].is_new is True
    assert changes[0].is_drop is False
    assert has_drops(changes) is False


def test_drop_detected_against_previous(tmp_path):
    prev = make_result({"ECONOMY": offer("ECONOMY", "QR", 1783)})
    save_run(prev, tmp_path)
    previous = load_latest(tmp_path, "sea-ccu")

    curr = make_result({"ECONOMY": offer("ECONOMY", "QR", 1450)})
    changes = compute_changes(previous, curr, target_price=1500)
    c = changes[0]
    assert c.is_drop is True
    assert c.delta == -333.0
    assert c.prev_price == 1783.0
    assert c.is_deal is True  # 1450 <= 1500
    assert has_drops(changes) is True
    assert has_deals(changes) is True


def test_price_increase_is_not_a_drop():
    previous = {"best_by_cabin": {"ECONOMY": offer("ECONOMY", "QR", 1400).to_dict()}}
    curr = make_result({"ECONOMY": offer("ECONOMY", "QR", 1600)})
    changes = compute_changes(previous, curr, target_price=1500)
    assert changes[0].is_drop is False
    assert changes[0].delta == 200.0
    assert changes[0].is_deal is False  # 1600 > 1500
    assert has_drops(changes) is False


def test_pct_change_computed():
    previous = {"best_by_cabin": {"ECONOMY": offer("ECONOMY", "QR", 2000).to_dict()}}
    curr = make_result({"ECONOMY": offer("ECONOMY", "QR", 1500)})
    changes = compute_changes(previous, curr, target_price=None)
    assert changes[0].pct_change == -25.0


def test_new_cabin_added_since_last_run_is_new():
    previous = {"best_by_cabin": {"ECONOMY": offer("ECONOMY", "QR", 1783).to_dict()}}
    curr = make_result({
        "ECONOMY": offer("ECONOMY", "QR", 1783),
        "BUSINESS": offer("BUSINESS", "EK", 5200),
    })
    changes = {c.cabin: c for c in compute_changes(previous, curr, target_price=1500)}
    assert changes["BUSINESS"].is_new is True
    assert changes["ECONOMY"].is_new is False
