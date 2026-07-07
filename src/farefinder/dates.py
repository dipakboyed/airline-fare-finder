"""Generate the (depart, return) date matrix honoring the search window + trip length."""
from __future__ import annotations

from datetime import date, timedelta

from .config import SearchConfig


def generate_date_matrix(cfg: SearchConfig) -> list[tuple[date, date]]:
    """All (depart, return) pairs where:

    - depart in [depart_from, depart_to] stepped by sampling.depart_step_days
    - trip length in [trip_min_days, trip_max_days] stepped by
      sampling.trip_length_step_days (always including the max bound)

    Returned sorted and de-duplicated.
    """
    pairs: set[tuple[date, date]] = set()

    depart_step = timedelta(days=cfg.sampling.depart_step_days)
    length_step = cfg.sampling.trip_length_step_days

    # Trip lengths: min, min+step, ... plus the max bound explicitly.
    lengths = list(range(cfg.trip_min_days, cfg.trip_max_days + 1, length_step))
    if cfg.trip_max_days not in lengths:
        lengths.append(cfg.trip_max_days)

    depart = cfg.depart_from
    while depart <= cfg.depart_to:
        for length in lengths:
            pairs.add((depart, depart + timedelta(days=length)))
        depart += depart_step

    return sorted(pairs)
