"""Command line entry point.

Examples:
  python -m farefinder run --config config/searches/sea-ccu.yaml
  python -m farefinder run --config-dir config/searches --data-dir data --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .config import SearchConfig, load_all_search_configs, load_search_config
from .history import (
    CabinChange,
    compute_changes,
    has_deals,
    has_drops,
    load_latest,
    save_run,
)
from .report import build_html, build_subject, build_text
from .search import run_search


def load_dotenv(path: str | Path = ".env") -> None:
    """Load KEY=VALUE lines from a .env file into os.environ (no override).

    Lightweight, dependency-free. Existing env vars win, so GitHub Actions
    secrets are never shadowed by a stray local file.
    """
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def should_email(policy: str, changes: list[CabinChange]) -> bool:
    if not changes:
        return False
    if policy in ("every_run", "every_run_plus_drops"):
        return True
    if policy == "only_drops":
        return has_drops(changes)
    if policy == "only_target":
        return has_deals(changes)
    return has_drops(changes)


def _process(cfg: SearchConfig, data_dir: Path, dry_run: bool):
    result = run_search(cfg)
    previous = load_latest(data_dir, cfg.name)
    changes = compute_changes(previous, result, cfg.target_price_usd)
    if not dry_run:
        save_run(result, data_dir)
    return result, changes


def _write_github_output(**kv):
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a", encoding="utf-8") as fh:
        for key, value in kv.items():
            # Single-line outputs: strip CR/LF so a value can't inject extra
            # key=value lines into the Actions step output.
            sanitized = str(value).replace("\r", " ").replace("\n", " ")
            fh.write(f"{key}={sanitized}\n")


def cmd_run(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    if args.config_dir:
        configs = load_all_search_configs(args.config_dir)
    elif args.config:
        configs = [load_search_config(args.config)]
    else:
        print("error: provide --config or --config-dir", file=sys.stderr)
        return 2
    if not configs:
        print("error: no search configs found", file=sys.stderr)
        return 2

    html_parts: list[str] = []
    text_parts: list[str] = []
    subjects: list[str] = []
    any_email = False
    summaries = []

    for cfg in configs:
        result, changes = _process(cfg, data_dir, args.dry_run)
        emit = should_email(cfg.alert_policy, changes)
        any_email = any_email or emit
        html_parts.append(build_html(cfg, changes, result.notes))
        text_parts.append(build_text(cfg, changes, result.notes))
        subjects.append(build_subject(cfg, changes))
        summaries.append(
            {
                "config": cfg.name,
                "route": f"{cfg.origin}->{cfg.destination}",
                "should_email": emit,
                "amadeus_calls": result.amadeus_calls,
                "google_offers": result.google_offer_count,
                "date_pairs": result.date_pairs,
                "best": {c: {"price": o.price, "airline": o.airline, "source": o.source}
                         for c, o in result.best_by_cabin.items()},
                "drops": [c.cabin for c in changes if c.is_drop],
                "deals": [c.cabin for c in changes if c.is_deal],
            }
        )

    subject = subjects[0] if len(subjects) == 1 else f"[fare-finder] {len(configs)} routes updated"
    html_body = "<hr>".join(html_parts)
    text_body = ("\n\n" + "=" * 60 + "\n\n").join(text_parts)

    Path(args.report_out).write_text(html_body, encoding="utf-8")
    Path(args.text_out).write_text(text_body, encoding="utf-8")

    _write_github_output(
        should_email=str(any_email).lower(),
        subject=subject,
        report_path=args.report_out,
        text_path=args.text_out,
    )

    print(json.dumps({"should_email": any_email, "subject": subject, "runs": summaries}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="farefinder", description="Cheapest airline fare finder")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run a fare search and produce a report")
    run.add_argument("--config", help="Path to a single search YAML")
    run.add_argument("--config-dir", help="Directory of search YAMLs (all are run)")
    run.add_argument("--data-dir", default="data", help="Where snapshots/history live")
    run.add_argument("--report-out", default="report.html", help="HTML report output path")
    run.add_argument("--text-out", default="report.txt", help="Plaintext report output path")
    run.add_argument("--dry-run", action="store_true", help="Do not persist snapshots")
    run.set_defaults(func=cmd_run)
    return parser


def main(argv=None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
