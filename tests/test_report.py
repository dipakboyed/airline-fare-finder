from datetime import date, datetime, timezone

from farefinder.config import SearchConfig, Sampling
from farefinder.history import CabinChange
from farefinder.models import FareOffer, utcnow
from farefinder.report import build_html, build_subject, build_text


def _offer(cabin, airline, price):
    return FareOffer(
        origin="SEA", destination="CCU", depart_date=date(2026, 7, 21),
        return_date=date(2026, 8, 4), cabin=cabin, airline=airline, price=price,
        currency="USD", stops_out=1, stops_ret=1, source="amadeus",
        booking_url="https://www.google.com/travel/flights?q=x", fetched_at=utcnow(),
    )


def _change(cabin, airline, price, prev=None, target=1500):
    o = _offer(cabin, airline, price)
    delta = (price - prev) if prev is not None else None
    return CabinChange(
        cabin=cabin, airline=airline, price=price, currency="USD", source="amadeus",
        prev_price=prev, delta=delta, is_drop=delta is not None and delta < 0,
        is_new=prev is None, is_deal=target is not None and price <= target, offer=o,
    )


def _cfg():
    return SearchConfig(
        name="sea-ccu", origin="SEA", destination="CCU", max_stops=1,
        depart_from=date(2026, 7, 21), depart_to=date(2026, 7, 25),
        trip_min_days=10, trip_max_days=20, cabins=("ECONOMY", "BUSINESS"),
        preferred_airlines=("SQ", "EK", "QR"), passengers=1, currency="USD",
        target_price_usd=1500.0, alert_policy="only_drops", sampling=Sampling(1, 2),
        amadeus_max_calls_per_run=15,
    )


def test_subject_flags_drop():
    changes = [_change("ECONOMY", "QR", 1450, prev=1783)]
    subj = build_subject(_cfg(), changes)
    assert "SEA" in subj and "CCU" in subj
    assert "drop" in subj.lower()
    assert "1,450" in subj


def test_html_contains_prices_links_and_badges():
    changes = [_change("ECONOMY", "QR", 1450, prev=1783), _change("BUSINESS", "EK", 5200, prev=None)]
    html = build_html(_cfg(), changes, notes=["amadeus ok"])
    assert "USD 1,450" in html
    assert "DROP" in html            # economy dropped
    assert "DEAL" in html            # economy 1450 <= 1500
    assert "google.com/travel/flights" in html
    assert "Economy" in html and "Business" in html


def test_text_report_lists_all_cabins_cheapest_first():
    changes = [_change("BUSINESS", "EK", 5200), _change("ECONOMY", "QR", 1450, prev=1783)]
    text = build_text(_cfg(), changes, notes=[])
    econ_idx = text.index("Economy")
    biz_idx = text.index("Business")
    assert econ_idx < biz_idx  # cheapest listed first


def test_html_escapes_untrusted_notes():
    changes = [_change("ECONOMY", "QR", 1450, prev=1783)]
    html = build_html(_cfg(), changes, notes=["<script>alert(1)</script>"])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
