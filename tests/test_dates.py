from datetime import date

from farefinder.config import SearchConfig, Sampling
from farefinder.dates import generate_date_matrix


def make_cfg(**over):
    base = dict(
        name="t",
        origin="SEA",
        destination="CCU",
        max_stops=1,
        depart_from=date(2026, 1, 1),
        depart_to=date(2026, 1, 22),
        trip_min_days=10,
        trip_max_days=20,
        cabins=("ECONOMY",),
        preferred_airlines=("SQ",),
        passengers=1,
        currency="USD",
        target_price_usd=1500.0,
        sampling=Sampling(1, 2),
        amadeus_max_calls_per_run=15,
        alert_policy="only_drops",
    )
    base.update(over)
    return SearchConfig(**base)


def test_matrix_respects_window_and_length_bounds():
    cfg = make_cfg()
    matrix = generate_date_matrix(cfg)
    assert matrix, "matrix should not be empty"
    for dep, ret in matrix:
        assert cfg.depart_from <= dep <= cfg.depart_to
        length = (ret - dep).days
        assert cfg.trip_min_days <= length <= cfg.trip_max_days


def test_matrix_includes_both_length_bounds():
    cfg = make_cfg()
    lengths = {(ret - dep).days for dep, ret in generate_date_matrix(cfg)}
    assert 10 in lengths  # min
    assert 20 in lengths  # max always included even with step=2


def test_depart_step_reduces_departures():
    fine = {dep for dep, _ in generate_date_matrix(make_cfg(sampling=Sampling(1, 2)))}
    coarse = {dep for dep, _ in generate_date_matrix(make_cfg(sampling=Sampling(7, 2)))}
    assert len(coarse) < len(fine)


def test_matrix_is_sorted_and_deduped():
    matrix = generate_date_matrix(make_cfg())
    assert matrix == sorted(matrix)
    assert len(matrix) == len(set(matrix))


def test_single_day_window():
    cfg = make_cfg(depart_from=date(2026, 1, 1), depart_to=date(2026, 1, 1))
    departs = {dep for dep, _ in generate_date_matrix(cfg)}
    assert departs == {date(2026, 1, 1)}
