from datetime import date

from farefinder.config import SearchConfig, Sampling
from farefinder.models import FareOffer, utcnow
from farefinder.search import best_per_cabin, run_search


def offer(cabin, airline, price, source, dep=date(2026, 7, 21), ret=date(2026, 8, 4)):
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
        target_price_usd=1500.0, sampling=Sampling(1, 5), amadeus_max_calls_per_run=4,
        alert_policy="only_drops",
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


class FakeAmadeus:
    def __init__(self, offers_by_key=None, configured=True):
        self.offers_by_key = offers_by_key or {}
        self._configured = configured
        self.pair_calls = []

    @property
    def configured(self):
        return self._configured

    def search_pair(self, cfg, dep, ret, cabin, max_offers=5):
        self.pair_calls.append((dep, ret, cabin))
        return list(self.offers_by_key.get((dep, ret, cabin), []))


def test_best_per_cabin_prefers_amadeus():
    offers = [
        offer("ECONOMY", "QR", 1700, "google"),
        offer("ECONOMY", "EK", 1783, "amadeus"),  # pricier but authoritative -> preferred
    ]
    best = best_per_cabin(offers)
    assert best["ECONOMY"].source == "amadeus"
    assert best["ECONOMY"].price == 1783


def test_best_per_cabin_falls_back_to_google_when_no_amadeus():
    best = best_per_cabin([offer("BUSINESS", "SQ", 5200, "google")])
    assert best["BUSINESS"].source == "google"


def test_run_search_confirms_top_candidates_and_reconciles():
    dep, ret = date(2026, 7, 21), date(2026, 8, 4)
    google_offers = [
        offer("ECONOMY", "QR", 1700, "google", dep, ret),
        offer("BUSINESS", "EK", 5100, "google", dep, ret),
    ]
    amadeus_offers = {
        (dep, ret, "ECONOMY"): [offer("ECONOMY", "QR", 1783, "amadeus", dep, ret)],
        (dep, ret, "BUSINESS"): [offer("BUSINESS", "EK", 5300, "amadeus", dep, ret)],
    }
    g, a = FakeGoogle(google_offers), FakeAmadeus(amadeus_offers)
    res = run_search(make_cfg(), google=g, amadeus=a)
    assert res.best_by_cabin["ECONOMY"].source == "amadeus"
    assert res.best_by_cabin["ECONOMY"].price == 1783
    assert res.best_by_cabin["BUSINESS"].price == 5300
    assert res.amadeus_calls == 2  # one per cabin candidate


def test_run_search_respects_amadeus_quota_cap():
    dep, ret = date(2026, 7, 21), date(2026, 8, 4)
    # 6 distinct google candidates but budget is 4.
    goffers = [offer("ECONOMY", "QR", 1600 + i, "google", dep, date(2026, 8, 4 + i)) for i in range(6)]
    g = FakeGoogle(goffers)
    a = FakeAmadeus({})
    res = run_search(make_cfg(amadeus_max_calls_per_run=4), google=g, amadeus=a, top_n=10)
    assert res.amadeus_calls == 4
    assert len(a.pair_calls) == 4


def test_run_search_google_blocked_falls_back_to_amadeus_sampling():
    g = FakeGoogle([])  # google blocked
    a = FakeAmadeus({})
    res = run_search(make_cfg(amadeus_max_calls_per_run=4), google=g, amadeus=a)
    assert res.google_offer_count == 0
    assert res.amadeus_calls > 0  # fallback sampled the matrix against Amadeus
    assert any("google returned no offers" in n for n in res.notes)


def test_run_search_amadeus_unconfigured_is_google_only():
    res = run_search(
        make_cfg(),
        google=FakeGoogle([offer("ECONOMY", "QR", 1700, "google")]),
        amadeus=FakeAmadeus({}, configured=False),
    )
    assert res.amadeus_calls == 0
    assert res.best_by_cabin["ECONOMY"].source == "google"
    assert any("not configured" in n for n in res.notes)
