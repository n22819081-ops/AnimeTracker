"""Headless CLI for the Modern Anime Tracker.

Wraps the production operations (diagnostics, inventory, review resolution) so
they can be driven from a terminal without the GUI. This is the same code path
the GUI uses -- `DiagnosticsReporter`, `ProductionInventoryOperations` -- so the
behaviour is identical, just without a window.

Safety model:
  * READ-ONLY by default. `profile`, `health`, and `review list` never write.
  * WRITE commands (`review confirm`) are a no-op DRY RUN unless `--yes` is
    passed. With `--yes` they act on the database.
  * Every command prints the profile path + database path it is operating on,
    so there is never a "did I touch the wrong DB" question.
  * Every invocation is appended to `<profile>/logs/headless.log`.

The default profile is the LIVE production profile (not the dev one), overridable
with `--profile PATH` or the `ANIME_TRACKER_PROFILE` environment variable.

Usage (from C:\\AnimeTracker, using the venv python):
  .\\.venv\\Scripts\\python.exe -m anime_tracker.headless profile
  .\\.venv\\Scripts\\python.exe -m anime_tracker.headless health
  .\\.venv\\Scripts\\python.exe -m anime_tracker.headless review list
  .\\.venv\\Scripts\\python.exe -m anime_tracker.headless review confirm --all-ambiguous
  .\\.venv\\Scripts\\python.exe -m anime_tracker.headless review confirm --all-ambiguous --yes
  .\\.venv\\Scripts\\python.exe -m anime_tracker.headless review confirm --candidate-id 42 --yes
  .\\.venv\\Scripts\\python.exe -m anime_tracker.headless reconcile
  .\\.venv\\Scripts\\python.exe -m anime_tracker.headless reconcile --add 64,65,1719,2237,18041 --yes
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path


def _default_profile() -> Path:
    override = os.environ.get("ANIME_TRACKER_PROFILE")
    if override:
        return Path(override)
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "Anime Tracker" / "AnimeTracker"
    return Path.home() / "AnimeTracker"


def _json(obj) -> str:
    return json.dumps(obj, indent=2, default=str)


def _log(profile: Path, command: str, detail: str, ok: bool) -> None:
    try:
        logs = profile / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with (logs / "headless.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} ok={ok} cmd={command} :: {detail}\n")
    except OSError:
        # Logging must never break the command itself.
        pass


def _banner(profile: Path) -> None:
    db = profile / "data" / "anime_tracker_modern.db"
    state = "EXISTS" if db.is_file() else "MISSING"
    print(f"[profile] {profile}")
    print(f"[database] {db}  ({state})")
    print("-" * 72)


def _open_ro(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)


def _open_rw(db: Path) -> sqlite3.Connection:
    return sqlite3.connect(db)


# ---------------------------------------------------------------------------
# profile
# ---------------------------------------------------------------------------
def cmd_profile(profile: Path, _args: argparse.Namespace) -> int:
    _banner(profile)
    info = {
        "profile_root": str(profile),
        "database_path": str(profile / "data" / "anime_tracker_modern.db"),
        "database_exists": (profile / "data" / "anime_tracker_modern.db").is_file(),
        "logs_dir": str(profile / "logs"),
        "backups_dir": str(profile / "backups"),
        "settings_path": str(profile / "settings.json"),
        "bootstrap_path": str(profile / "bootstrap.json"),
    }
    try:
        from .production.profile import ProductionProfile
        prod = ProductionProfile(profile)
        bootstrap = prod.load_bootstrap()
        info["migration_state"] = bootstrap.get("migration_state")
        info["cutover_state"] = bootstrap.get("cutover_state")
    except Exception as exc:  # pragma: no cover - defensive
        info["bootstrap_error"] = str(exc)
    print(_json(info))
    return 0


# ---------------------------------------------------------------------------
# health
# ---------------------------------------------------------------------------
def cmd_health(profile: Path, _args: argparse.Namespace) -> int:
    _banner(profile)
    from .production.diagnostics import DiagnosticsReporter
    from .production.profile import ProductionProfile
    value = DiagnosticsReporter(ProductionProfile(profile)).health(local_only=True)
    print(_json(value))
    return 0


# ---------------------------------------------------------------------------
# review list
# ---------------------------------------------------------------------------
def cmd_review_list(profile: Path, args: argparse.Namespace) -> int:
    db = profile / "data" / "anime_tracker_modern.db"
    if not db.is_file():
        print(f"error: no database at {db}", file=sys.stderr)
        return 1
    _banner(profile)
    with closing(_open_ro(db)) as connection:
        connection.row_factory = sqlite3.Row
        cases = connection.execute(
            """
            SELECT rc.review_id, rc.review_type, rc.anilist_id, rc.severity, rc.state
            FROM review_cases rc
            WHERE rc.state IN ('OPEN','ACKNOWLEDGED')
            ORDER BY rc.review_id
            """
        ).fetchall()
        out = []
        for case in cases:
            title = connection.execute(
                "SELECT title FROM media_titles WHERE anilist_id=?",
                (case["anilist_id"],),
            ).fetchone()
            candidates = [
                {"candidate_id": c["candidate_id"], "normalized_path": c["normalized_path"],
                 "relative_path": c["relative_path"], "score": c["score"],
                 "path_state": c["path_state"], "season_number": c["season_number"]}
                for c in connection.execute(
                    """
                    SELECT candidate_id, normalized_path, relative_path, score, path_state, season_number
                    FROM server_match_candidates WHERE anilist_id=? ORDER BY score DESC, candidate_id ASC
                    """,
                    (case["anilist_id"],),
                )
            ]
            out.append({
                "review_id": case["review_id"],
                "type": case["review_type"],
                "state": case["state"],
                "anilist_id": case["anilist_id"],
                "title": title["title"] if title else None,
                "severity": case["severity"],
                "candidates": candidates,
            })
    scope = "open + acknowledged" if args.all else "open"
    print(f"[review] {len(out)} {scope} cases")
    print(_json(out))
    return 0


def _pick_best_candidate(connection: sqlite3.Connection, anilist_id: int):
    """Choose the strongest candidate for a title: prefer path_state='EXISTS',
    then highest score, tie-broken by candidate_id (stable order)."""
    rows = connection.execute(
        """
        SELECT candidate_id, normalized_path, relative_path, score, path_state, season_number
        FROM server_match_candidates
        WHERE anilist_id=?
        ORDER BY (CASE WHEN path_state='EXISTS' THEN 0 ELSE 1 END), score DESC, candidate_id ASC
        """,
        (anilist_id,),
    ).fetchall()
    if not rows:
        return None
    row = rows[0]
    exists = row["path_state"] == "EXISTS"
    return (row, exists)


def cmd_review_confirm(profile: Path, args: argparse.Namespace) -> int:
    db = profile / "data" / "anime_tracker_modern.db"
    if not db.is_file():
        print(f"error: no database at {db}", file=sys.stderr)
        return 1
    _banner(profile)

    if args.candidate_id is None and not args.all_ambiguous:
        print("error: pass --candidate-id <id> or --all-ambiguous to pick what to confirm.", file=sys.stderr)
        return 1

    # Build the plan first (read-only), so a dry run is safe.
    with closing(_open_ro(db)) as connection:
        connection.row_factory = sqlite3.Row
        cases = connection.execute(
            """
            SELECT rc.review_id, rc.review_type, rc.anilist_id, rc.severity
            FROM review_cases rc
            WHERE rc.state='OPEN' AND rc.review_type='AMBIGUOUS_STRONG_CANDIDATES'
            ORDER BY rc.review_id
            """
        ).fetchall()
        plan = []
        for case in cases:
            if args.candidate_id is not None:
                # Single explicit candidate: only act on the case it belongs to.
                row = connection.execute(
                    "SELECT anilist_id FROM server_match_candidates WHERE candidate_id=?",
                    (args.candidate_id,),
                ).fetchone()
                if not row or str(row["anilist_id"]) != str(case["anilist_id"]):
                    continue
                chosen_row = connection.execute(
                    "SELECT candidate_id, normalized_path, relative_path, score, path_state FROM server_match_candidates WHERE candidate_id=?",
                    (args.candidate_id,),
                ).fetchone()
                chosen = (chosen_row, chosen_row["path_state"] == "EXISTS")
            else:
                chosen = _pick_best_candidate(connection, case["anilist_id"])
            if not chosen:
                plan.append({"review_id": case["review_id"], "anilist_id": case["anilist_id"],
                             "action": "SKIP (no candidate)"})
                continue
            row, exists = chosen
            title = connection.execute(
                "SELECT title FROM media_titles WHERE anilist_id=?", (case["anilist_id"],)
            ).fetchone()
            plan.append({
                "review_id": case["review_id"], "anilist_id": case["anilist_id"],
                "title": title["title"] if title else None,
                "candidate_id": row["candidate_id"], "normalized_path": row["normalized_path"],
                "score": row["score"], "path_state": row["path_state"],
                "action": "confirm" if exists else "confirm (path UNKNOWN - may be INCOMPLETE)",
            })

    if args.candidate_id is not None:
        plan = [p for p in plan if "candidate_id" in p]

    print(f"[plan] {len(plan)} action(s)")
    print(_json(plan))

    if not args.yes:
        print("\nDRY RUN - no changes made. Re-run with --yes to apply.")
        _log(profile, "review confirm", f"dry-run planned={len(plan)}", True)
        return 0

    # Apply via the app's own operation.
    from .production.operations import ProductionInventoryOperations
    from .production.profile import ProductionProfile
    ops = ProductionInventoryOperations(ProductionProfile(profile))
    results = []
    for item in plan:
        if "candidate_id" not in item:
            continue
        try:
            result = ops.confirm_candidate(item["candidate_id"], item["anilist_id"])
            entry = asdict(result) if is_dataclass(result) else dict(result)
            entry["anilist_id"] = item["anilist_id"]
            entry["normalized_path"] = item["normalized_path"]
            results.append(entry)
        except Exception as exc:
            results.append({"error": str(exc), "candidate_id": item["candidate_id"],
                            "anilist_id": item["anilist_id"]})
    print("[applied]")
    print(_json(results))

    ok = all("error" not in r for r in results)
    _log(profile, "review confirm", f"applied={len(results)} ok={ok}", ok)
    return 0 if ok else 2


# ---------------------------------------------------------------------------
# reconcile
# ---------------------------------------------------------------------------
def cmd_reconcile(profile: Path, args: argparse.Namespace) -> int:
    db = profile / "data" / "anime_tracker_modern.db"
    if not db.is_file():
        print(f"error: no database at {db}", file=sys.stderr)
        return 1
    _banner(profile)

    # Cache-only titles: present in anilist_media_cache but with no active
    # tracked row. This is the signature of a half-persisted add (cache wrote,
    # tracked rows never committed) OR a plain search that was never tracked.
    with closing(_open_ro(db)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT c.anilist_id, c.retrieved_at, c.stale,
                   am.media_format AS fmt, am.anilist_status AS status
            FROM anilist_media_cache c
            LEFT JOIN tracked_media tm
                   ON tm.anilist_id = c.anilist_id AND tm.archived_at IS NULL
            LEFT JOIN anilist_media am
                   ON am.anilist_id = c.anilist_id
            WHERE tm.id IS NULL
            ORDER BY c.retrieved_at DESC
            """
        ).fetchall()
        report = []
        for r in rows:
            anilist_id = r["anilist_id"]
            title = connection.execute(
                "SELECT title FROM anilist_title_variants WHERE anilist_id=? "
                "ORDER BY CASE title_type WHEN 'english' THEN 0 WHEN 'primary' THEN 1 "
                "WHEN 'romaji' THEN 2 WHEN 'native' THEN 3 ELSE 4 END LIMIT 1",
                (anilist_id,),
            ).fetchone()
            report.append({
                "anilist_id": anilist_id,
                "title": title["title"] if title else None,
                "media_format": r["fmt"] or None,
                "anilist_status": r["status"] or None,
                "retrieved_at": r["retrieved_at"],
                "stale": bool(r["stale"]),
            })

    if args.add is None:
        print(f"[reconcile] {len(report)} cache-only title(s) (in cache, not tracked)")
        print(_json(report))
        _log(profile, "reconcile", f"report-only found={len(report)}", True)
        return 0

    # --add id1,id2[,id3]: backfill explicit ids via the app's own atomic op.
    requested = [int(x) for x in args.add.split(",") if x.strip()]
    cache_only_ids = {r["anilist_id"] for r in report}
    not_in_cache = [x for x in requested if x not in cache_only_ids]
    plan = [r for r in report if r["anilist_id"] in requested]
    print(f"[plan] {len(plan)} of {len(requested)} requested id(s) are cache-only")
    if not_in_cache:
        print(f"[plan] note: not cache-only (already tracked or not cached): {not_in_cache}")
    print(_json(plan))

    if not args.yes:
        print("\nDRY RUN - no changes made. Re-run with --yes to apply.")
        _log(profile, "reconcile", f"dry-run planned={len(plan)}", True)
        return 0

    from .production.operations import ProductionAniListOperations
    from .production.profile import ProductionProfile
    ops = ProductionAniListOperations(ProductionProfile(profile))
    result = ops.add_tracked_media(requested)
    entry = dict(result)
    entry["requested_ids"] = requested
    entry["not_in_cache_only"] = not_in_cache
    print("[applied]")
    print(_json(entry))
    ok = result["failed"] == 0
    _log(profile, "reconcile", f"applied added={result['added']} existing={result['existing']} failed={result['failed']}", ok)
    return 0 if ok else 2


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="anime_tracker.headless",
        description="Headless operations for the Modern Anime Tracker.",
    )
    parser.add_argument("--profile", type=Path, default=None,
                        help="Production profile root (default: live production profile, or $ANIME_TRACKER_PROFILE).")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("profile", help="Show which profile/database this targets.")
    sub.add_parser("health", help="Read-only health report (integrity, counts, media-safety).")

    review = sub.add_parser("review", help="Review-case operations.")
    review_sub = review.add_subparsers(dest="review_command")
    rlist = review_sub.add_parser("list", help="List open review cases + candidate folders.")
    rlist.add_argument("--all", action="store_true", help="Include ACKNOWLEDGED cases.")
    rconf = review_sub.add_parser("confirm", help="Confirm a candidate folder (WRITE).")
    rconf.add_argument("--candidate-id", type=str, default=None, help="Confirm one specific candidate (e.g. legacy-candidate-18).")
    rconf.add_argument("--all-ambiguous", action="store_true",
                       help="Confirm the best candidate for every open AMBIGUOUS case.")
    rconf.add_argument("--yes", action="store_true", help="Actually write (without this it is a dry run).")

    rec = sub.add_parser(
        "reconcile",
        help="Find cache-only titles (in cache, not tracked) and optionally backfill them.",
    )
    rec.add_argument("--add", type=str, default=None, metavar="ID1,ID2",
                     help="Backfill these cache-only anilist ids (dry run without --yes).")
    rec.add_argument("--yes", action="store_true", help="Actually write (without this --add is a dry run).")

    args = parser.parse_args(argv)
    profile = args.profile or _default_profile()
    profile = profile.expanduser().resolve()

    exit_code = 0
    try:
        if args.command == "profile":
            exit_code = cmd_profile(profile, args)
        elif args.command == "health":
            exit_code = cmd_health(profile, args)
        elif args.command == "review" and args.review_command == "list":
            exit_code = cmd_review_list(profile, args)
        elif args.command == "review" and args.review_command == "confirm":
            exit_code = cmd_review_confirm(profile, args)
        elif args.command == "reconcile":
            exit_code = cmd_reconcile(profile, args)
        else:
            parser.print_help()
            return 1
    except Exception as exc:  # top-level: never leak a stack for expected failures
        print(f"error: {exc}", file=sys.stderr)
        _log(profile, args.command or "?", f"EXC {exc}", False)
        return 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
