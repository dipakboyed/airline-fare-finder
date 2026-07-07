import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

import farefinder.__main__ as cli
from farefinder.config import Sampling, SearchConfig
from farefinder.history import compute_changes
from farefinder.models import FareOffer, utcnow
from farefinder.search import RunResult


def _offer(cabin, airline, price, source="travelpayouts"):
    return FareOffer(
        origin="SEA", destination="CCU", depart_date=date(2026, 7, 21),
        return_date=date(2026, 8, 4), cabin=cabin, airline=airline, price=price,
        currency="USD", stops_out=1, stops_ret=1, source=source,
        booking_url="https://www.google.com/travel/flights?q=x", fetched_at=utcnow(),
    )


def _make_result(best, when=None):
    return RunResult(
        config_name="sea-ccu", origin="SEA", destination="CCU",
        generated_at=when or datetime(2026, 7, 7, 12, tzinfo=timezone.utc),
        best_by_cabin=best, all_offers=list(best.values()), crosscheck_calls=2,
        google_offer_count=3, date_pairs=50, notes=[],
    )


def _write_cfg(tmp_path, policy="only_drops"):
    d = tmp_path / "searches"
    d.mkdir()
    (d / "sea-ccu.yaml").write_text(
        f"""
name: sea-ccu
origin: SEA
destination: CCU
max_stops: 1
depart_window: {{from: today, to: +21d}}
trip_length_days: [10, 20]
cabins: [ECONOMY]
preferred_airlines: [QR, EK, SQ]
passengers: 1
currency: USD
target_price_usd: 1500
alert_policy: {policy}
""",
        encoding="utf-8",
    )
    return d / "sea-ccu.yaml"


def test_should_email_policies():
    from farefinder.history import CabinChange

    def ch(drop, deal):
        return CabinChange("ECONOMY", "QR", 1400, "USD", "travelpayouts", 1800 if drop else None,
                           -400 if drop else None, drop, not drop, deal, _offer("ECONOMY", "QR", 1400))

    drop = [ch(True, True)]
    flat = [ch(False, False)]
    assert cli.should_email("every_run", flat) is True
    assert cli.should_email("only_drops", drop) is True
    assert cli.should_email("only_drops", flat) is False
    assert cli.should_email("only_target", [ch(False, True)]) is True
    assert cli.should_email("only_target", flat) is False
    assert cli.should_email("only_drops", []) is False


def test_cli_run_emits_report_and_outputs(tmp_path, monkeypatch, capsys):
    cfg_path = _write_cfg(tmp_path, policy="only_drops")
    data_dir = tmp_path / "data"
    report = tmp_path / "report.html"
    textout = tmp_path / "report.txt"
    gh_out = tmp_path / "gh_output"
    gh_out.write_text("", encoding="utf-8")
    monkeypatch.setenv("GITHUB_OUTPUT", str(gh_out))

    # First run: seed a snapshot at a high price (patch run_search).
    monkeypatch.setattr(cli, "run_search", lambda cfg: _make_result({"ECONOMY": _offer("ECONOMY", "QR", 1900)}))
    rc = cli.main(["run", "--config", str(cfg_path), "--data-dir", str(data_dir),
                   "--report-out", str(report), "--text-out", str(textout)])
    assert rc == 0
    capsys.readouterr()  # discard first-run output

    # Second run: price drops -> should_email true, report shows DROP.
    monkeypatch.setattr(cli, "run_search", lambda cfg: _make_result({"ECONOMY": _offer("ECONOMY", "QR", 1450)}))
    rc = cli.main(["run", "--config", str(cfg_path), "--data-dir", str(data_dir),
                   "--report-out", str(report), "--text-out", str(textout)])
    assert rc == 0

    out = json.loads(capsys.readouterr().out)
    assert out["should_email"] is True
    assert "DROP" in report.read_text(encoding="utf-8")
    gh = gh_out.read_text(encoding="utf-8")
    assert "should_email=true" in gh
    assert "subject=" in gh


def test_cli_dry_run_does_not_persist(tmp_path, monkeypatch, capsys):
    cfg_path = _write_cfg(tmp_path)
    data_dir = tmp_path / "data"
    monkeypatch.setattr(cli, "run_search", lambda cfg: _make_result({"ECONOMY": _offer("ECONOMY", "QR", 1450)}))
    rc = cli.main(["run", "--config", str(cfg_path), "--data-dir", str(data_dir),
                   "--report-out", str(tmp_path / "r.html"), "--text-out", str(tmp_path / "r.txt"),
                   "--dry-run"])
    assert rc == 0
    capsys.readouterr()
    assert not (data_dir / "latest").exists()  # nothing persisted


def test_load_dotenv_sets_missing_but_never_overrides(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# comment\nAMADEUS_CLIENT_ID=abc123\nAMADEUS_CLIENT_SECRET="sh h"\nEXISTING=fromfile\n\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("AMADEUS_CLIENT_ID", raising=False)
    monkeypatch.setenv("EXISTING", "fromenv")  # pre-set -> must NOT be overridden
    cli.load_dotenv(env_file)
    assert os.environ["AMADEUS_CLIENT_ID"] == "abc123"
    assert os.environ["AMADEUS_CLIENT_SECRET"] == "sh h"  # quotes stripped
    assert os.environ["EXISTING"] == "fromenv"  # existing env wins


def test_load_dotenv_missing_file_is_noop(tmp_path):
    cli.load_dotenv(tmp_path / "nope.env")  # must not raise
