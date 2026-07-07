from datetime import date

import pytest

from farefinder.config import ConfigError, load_search_config, load_all_search_configs

REPO_ROOT = None


def write(tmp_path, text):
    p = tmp_path / "trip.yaml"
    p.write_text(text, encoding="utf-8")
    return p


VALID = """
name: sea-ccu
origin: SEA
destination: CCU
max_stops: 1
depart_window: {from: today, to: +21d}
trip_length_days: [10, 20]
cabins: [ECONOMY, PREMIUM_ECONOMY, BUSINESS]
preferred_airlines: [SQ, EK, QR]
passengers: 1
currency: USD
target_price_usd: 1500
sampling: {depart_step_days: 1, trip_length_step_days: 2}
crosscheck_max_calls_per_run: 15
"""


def test_valid_config_resolves_relative_dates(tmp_path):
    today = date(2026, 1, 1)
    cfg = load_search_config(write(tmp_path, VALID), today=today)
    assert cfg.origin == "SEA"
    assert cfg.destination == "CCU"
    assert cfg.depart_from == date(2026, 1, 1)
    assert cfg.depart_to == date(2026, 1, 22)
    assert cfg.trip_min_days == 10 and cfg.trip_max_days == 20
    assert cfg.preferred_airlines == ("SQ", "EK", "QR")
    assert cfg.target_price_usd == 1500.0


def test_absolute_date_window(tmp_path):
    text = VALID.replace("{from: today, to: +21d}", "{from: 2026-03-01, to: 2026-03-15}")
    cfg = load_search_config(write(tmp_path, text), today=date(2026, 1, 1))
    assert cfg.depart_from == date(2026, 3, 1)
    assert cfg.depart_to == date(2026, 3, 15)


def test_invalid_cabin_rejected(tmp_path):
    text = VALID.replace("[ECONOMY, PREMIUM_ECONOMY, BUSINESS]", "[COACH]")
    with pytest.raises(ConfigError):
        load_search_config(write(tmp_path, text))


def test_bad_airport_rejected(tmp_path):
    text = VALID.replace("origin: SEA", "origin: SEATTLE")
    with pytest.raises(ConfigError):
        load_search_config(write(tmp_path, text))


def test_trip_length_max_lt_min_rejected(tmp_path):
    text = VALID.replace("[10, 20]", "[20, 10]")
    with pytest.raises(ConfigError):
        load_search_config(write(tmp_path, text))


def test_missing_file():
    with pytest.raises(ConfigError):
        load_search_config("does-not-exist.yaml")


def test_non_usd_currency_with_usd_target_rejected(tmp_path):
    text = VALID.replace("currency: USD", "currency: EUR")
    with pytest.raises(ConfigError):
        load_search_config(write(tmp_path, text))


def test_non_usd_currency_without_target_is_ok(tmp_path):
    text = VALID.replace("currency: USD", "currency: EUR").replace("target_price_usd: 1500", "target_price_usd:")
    cfg = load_search_config(write(tmp_path, text), today=date(2026, 1, 1))
    assert cfg.currency == "EUR"
    assert cfg.target_price_usd is None


def test_repo_sea_ccu_config_is_valid():
    # The shipped config must always load & validate.
    from pathlib import Path

    cfg_path = Path(__file__).resolve().parents[1] / "config" / "searches" / "sea-ccu.yaml"
    cfg = load_search_config(cfg_path, today=date(2026, 1, 1))
    assert cfg.name == "sea-ccu"
    assert cfg.max_stops == 1


def test_load_all_picks_up_directory():
    from pathlib import Path

    d = Path(__file__).resolve().parents[1] / "config" / "searches"
    cfgs = load_all_search_configs(d, today=date(2026, 1, 1))
    assert any(c.name == "sea-ccu" for c in cfgs)
