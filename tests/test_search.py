from datetime import date

from farefinder.config import SearchConfig, Sampling
from farefinder.models import FareOffer, utcnow
from farefinder.search import best_per_cabin, run_search


def offer(cabin, airline, price, source="google", dep=date(2026, 7, 21), ret=date(2026, 8, 4)):
    return FareOffer(
        origin="SEA", destination="CCU", depart_date=dep, return_date=ret, cabin=cabin,
        airline=airline, price=price, currency="USD", stops_out=1, stops_ret=1,
        source=source, booking_url="https://example.com/x", fetched_at=utcnow(),
    )


def make_cfg(**over):
    base = dict(
        name="t", origin="SEA", destination="CCU", max_stops=1,
        depart_from=date(2026, 7, 21), depart_to=date(2026, 7, 25),
        trip_min_days=10, trip_max_days=20, cabins=("ECONOMY", "BUSINESS"),
        preferred_airlines=("SQ", "EK", "QR"), passengers=1, currency="USD",
        target_price_usd=1500.0, sampling=Sampling(1, 5), alert_policy="only_drops",
        crosscheck_max_calls_per_run=4,
    )
    base.update(over)
    return SearchConfig(**base)


class FakeGoogle:
    def __init__(self, offers):
        self._offers = offers
        self.calls = 0

    def search(self, cfg, date_pairs, cabins):
        self.calls += 1
        return list(self._offers)


class FakeTravelpayouts:
    def __init__(self, offers_by_key=None, configured=True):
        self.offers_by_key = offers_by_key or {}
        self._configured = configured
        self.pair_calls = []

    @property
    def configured(self):
        return self._configured

    def search_pair(self, cfg, dep, ret, cabin="ECONOMY"):
        self.pair_calls.append((dep, ret, cabin))
        if cabin != "ECONOMY":
            return []
        return list(self.offers_by_key.get((dep, ret, cabin), []))


def test_best_per_cabin_picks_cheapest_across_sources():
    offers = [
        offer("ECONOMY", "QR", 1700, "google"),
        offer("ECONOMY", "QR", 1783, "travelpayouts"),
    ]
    assert best_per_cabin(offers)["ECONOMY"].price == 1700  # cheapest wins regardless of source

    offers2 = [
        offer("ECONOMY", "QR", 1800, "google"),
        offer("ECONOMY", "QR", 1720, "travelpayouts"),
    ]
    best2 = best_per_cabin(offers2)["ECONOMY"]
    assert best2.price == 1720 and best2.source == "travelpayouts"


def test_best_per_cabin_optional_prefer_source():
    offers = [
        offer("ECONOMY", "QR", 1700, "google"),
        offer("ECONOMY", "QR", 1783, "travelpayouts"),
    ]
    best = best_per_cabin(offers, prefer_source="travelpayouts")
    assert best["ECONOMY"].source == "travelpayouts"


def test_run_search_crosschecks_economy_and_picks_cheaper():
    dep, ret = date(2026, 7, 21), date(2026, 8, 4)
    google_offers = [
        offer("ECONOMY", "QR", 1800, "google", dep, ret),
        offer("BUSINESS", "EK", 5100, "google", dep, ret),
    ]
    tp_offers = {(dep, ret, "ECONOMY"): [offer("ECONOMY", "QR", 1720, "travelpayouts", dep, ret)]}
    g, tp = FakeGoogle(google_offers), FakeTravelpayouts(tp_offers)
    res = run_search(make_cfg(), google=g, crosscheck=tp)
    assert res.best_by_cabin["ECONOMY"].price == 1720
    assert res.best_by_cabin["ECONOMY"].source == "travelpayouts"
    assert res.best_by_cabin["BUSINESS"].price == 5100  # business not cross-checked
    assert res.crosscheck_calls == 1
    assert all(c[2] == "ECONOMY" for c in tp.pair_calls)  # only economy cross-checked


def test_run_search_respects_crosscheck_quota_cap():
    dep = date(2026, 7, 21)
    goffers = [offer("ECONOMY", "QR", 1600 + i, "google", dep, date(2026, 8, 4 + i)) for i in range(6)]
    g = FakeGoogle(goffers)
    tp = FakeTravelpayouts({})
    res = run_search(make_cfg(crosscheck_max_calls_per_run=4), google=g, crosscheck=tp, top_n=10)
    assert res.crosscheck_calls == 4
    assert len(tp.pair_calls) == 4


def test_run_search_google_blocked_falls_back_to_crosscheck_sampling():
    g = FakeGoogle([])
    tp = FakeTravelpayouts({})
    res = run_search(make_cfg(crosscheck_max_calls_per_run=4), google=g, crosscheck=tp)
    assert res.google_offer_count == 0
    assert res.crosscheck_calls > 0
    assert any("google returned no offers" in n for n in res.notes)
    assert all(c[2] == "ECONOMY" for c in tp.pair_calls)


def test_run_search_crosscheck_unconfigured_is_google_only():
    res = run_search(
        make_cfg(),
        google=FakeGoogle([offer("ECONOMY", "QR", 1700, "google")]),
        crosscheck=FakeTravelpayouts({}, configured=False),
    )
    assert res.crosscheck_calls == 0
    assert res.best_by_cabin["ECONOMY"].source == "google"
    assert any("not configured" in n for n in res.notes)
