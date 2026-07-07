"""Live smoke tests — skipped unless real creds / opt-in are present.

Run explicitly with:  pytest -m live
These hit real external services and validate against the source of truth.
"""
import os
from datetime import date, timedelta

import pytest

from farefinder.config import SearchConfig, Sampling
from farefinder.providers.google_flights import GoogleFlightsProvider
from farefinder.providers.travelpayouts import TravelpayoutsProvider

pytestmark = pytest.mark.live


def _cfg():
    dep = date.today() + timedelta(days=21)
    return SearchConfig(
        name="smoke", origin="SEA", destination="CCU", max_stops=1,
        depart_from=dep, depart_to=dep, trip_min_days=14, trip_max_days=14,
        cabins=("ECONOMY",), preferred_airlines=("SQ", "EK", "QR"), passengers=1,
        currency="USD", target_price_usd=1500.0, sampling=Sampling(1, 1),
        crosscheck_max_calls_per_run=15, alert_policy="only_drops",
    )


@pytest.mark.skipif(
    not os.environ.get("TRAVELPAYOUTS_TOKEN"),
    reason="Travelpayouts token not set",
)
def test_travelpayouts_live_returns_wellformed_offers():
    cfg = _cfg()
    dep = cfg.depart_from
    ret = dep + timedelta(days=14)
    offers = TravelpayoutsProvider().search_pair(cfg, dep, ret, "ECONOMY")
    # May be empty on a given date, but any returned offer must be well-formed.
    for o in offers:
        assert o.is_well_formed()
        assert o.airline in {"SQ", "EK", "QR"}
        assert o.max_stops <= 1


@pytest.mark.skipif(
    os.environ.get("FAREFINDER_LIVE_GOOGLE") != "1",
    reason="set FAREFINDER_LIVE_GOOGLE=1 to run the Google live smoke",
)
def test_google_live_returns_wellformed_offers():
    cfg = _cfg()
    dep = cfg.depart_from
    ret = dep + timedelta(days=14)
    offers = GoogleFlightsProvider(request_delay_s=0).search_pair(cfg, dep, ret, "ECONOMY")
    for o in offers:
        assert o.is_well_formed()
        assert o.max_stops <= 1
