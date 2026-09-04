"""Headless CLI for the Anime Tracker.

Run it with the venv python from the project root:

    .venv\\Scripts\\python.exe -m anime_tracker.cli <command>

Commands:
    add <query or anilist id>   Search AniList, add the best match (or an
                                explicit --id), then run a scan.
    scan                        Scan the configured TV/Movie roots and
                                reconcile every tracked anime.
    list                        List tracked anime (optionally --status X).
    reject <anilist id> <path>  Reject a candidate server path for one anime.
    remove <anilist id>         Remove an anime from the tracker.
    health                      Check AniList reachability and DB size.

All mutations go through the same Database methods the GUI uses, and every
command takes a backup first (via Database.backup).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .constants import DEFAULT_MOVIE_PATH, DEFAULT_TV_PATH
from .database import Database
from .models import AnimeRecord
from .scanner import ServerCandidate
from .services.scan_service import run_server_scan
from .status import tracker_status_from_anilist


def _db() -> Database:
    return Database()


def _fetch_anilist(query: str, anilist_id: int | None):
    from .anilist import AniListClient

    client = AniListClient()
    if anilist_id:
        try:
            return client.get_by_id(anilist_id), f"AniList id {anilist_id}"
        except Exception as exc:  # noqa: BLE001 - surface any client error
            print(f"error: could not fetch AniList id {anilist_id}: {exc}")
            sys.exit(1)
    results = client.search(query)
    if not results:
        print(f"error: AniList has no results for {query!r}")
        sys.exit(1)
    return results[0], f"AniList search for {query!r} ({len(results)} result(s))"


def _print_table(rows, headers):
    if not rows:
        print("(none)")
        return
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(str(cell)))
    fmt = "  ".join("{:<" + str(w) + "}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for r in rows:
        print(fmt.format(*[str(c) for c in r]))


def cmd_add(args) -> int:
    payload, source = _fetch_anilist(args.query, args.id)
    status = tracker_status_from_anilist(
        payload.get("airingStatus") or "UNKNOWN",
        payload.get("format") or "TV",
        "unknown",
    )
    record = AnimeRecord.from_anilist(payload, status)
    db = _db()
    row_id = db.upsert_anime(record)
    print(f"added: {record.english_title} (anilist {record.anilist_id}, row {row_id}) [{source}]")

    if args.no_scan:
        print("scan skipped (--no-scan)")
    else:
        _run_scan(db, only_anilist_ids=(record.anilist_id,))
    return 0


def cmd_scan(args) -> int:
    db = _db()
    _run_scan(db)
    return 0


def _run_scan(db: Database, only_anilist_ids: tuple[int, ...] | None = None) -> None:
    settings = db.get_settings()
    print(f"scanning: TV={settings.get('tv_path') or DEFAULT_TV_PATH}  Movies={settings.get('movie_path') or DEFAULT_MOVIE_PATH}")

    def notify(kind: str, row, extra: dict) -> None:
        if kind == "server-found":
            print(f"  FOUND: {row['english_title']} -> {extra.get('Detected Path')}")
        elif kind == "server-missing":
            print(f"  MISSING: {row['english_title']} (was {extra.get('Previous Path')})")

    summary = run_server_scan(db, notify=notify, backup_label="cli-scan", only_anilist_ids=only_anilist_ids)
    print(f"done: {summary.total} scanned | {summary.found} on server, {summary.needs_review} needs review, "
          f"{summary.no_match} not found, {summary.review_missing} confirmed missing, {summary.kept_confirmed} confirmed retained")


def cmd_list(args) -> int:
    db = _db()
    rows = db.rows()
    if args.status:
        rows = [r for r in rows if r["tracker_status"] == args.status or r["server_status"] == args.status]
    if args.server:
        rows = [r for r in rows if r["server_status"] == args.server]
    if args.limit:
        rows = rows[: args.limit]
    _print_table(
        [
            (
                r["id"],
                r["anilist_id"],
                r["english_title"],
                r["tracker_status"],
                r["server_status"],
                r["detected_server_path"] or "",
            )
            for r in rows
        ],
        ("id", "anilist", "title", "tracker", "server", "path"),
    )
    return 0


def cmd_reject(args) -> int:
    db = _db()
    rows = [r for r in db.rows() if r["anilist_id"] == args.anilist_id]
    if not rows:
        print(f"error: no anime with anilist id {args.anilist_id}")
        return 1
    db.reject_match(args.anilist_id, args.path)
    print(f"rejected {args.path!r} for {rows[0]['english_title']}")
    return 0


def cmd_remove(args) -> int:
    db = _db()
    rows = [r for r in db.rows() if r["anilist_id"] == args.anilist_id]
    if not rows:
        print(f"error: no anime with anilist id {args.anilist_id}")
        return 1
    for r in rows:
        db.delete_anime(r["id"])
        print(f"removed: {r['english_title']} (row {r['id']})")
    return 0


def cmd_health(args) -> int:
    from .anilist import AniListClient

    db = _db()
    ok, message = AniListClient().health_check()
    print(f"anilist: {'ok' if ok else 'UNREACHABLE'} ({message})")
    print(f"db: {db.path} | {len(db.rows())} tracked anime")
    settings = db.get_settings()
    tv = Path(settings.get("tv_path", DEFAULT_TV_PATH))
    movie = Path(settings.get("movie_path", DEFAULT_MOVIE_PATH))
    print(f"tv root:   {tv}  ({'exists' if tv.exists() else 'MISSING'})")
    print(f"movie root:{movie}  ({'exists' if movie.exists() else 'MISSING'})")
    return 0 if ok else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="anime-tracker", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="add an anime by AniList search or id, then scan it")
    p_add.add_argument("query", help="title to search on AniList (ignored when --id given)")
    p_add.add_argument("--id", type=int, default=None, help="explicit AniList id (skips search)")
    p_add.add_argument("--no-scan", action="store_true", help="do not run a scan after adding")
    p_add.set_defaults(func=cmd_add)

    p_scan = sub.add_parser("scan", help="scan TV/Movie roots and reconcile all tracked anime")
    p_scan.set_defaults(func=cmd_scan)

    p_list = sub.add_parser("list", help="list tracked anime")
    p_list.add_argument("--status", help="filter by tracker status (e.g. 'Currently Airing')")
    p_list.add_argument("--server", help="filter by server status (e.g. 'On Server')")
    p_list.add_argument("--limit", type=int, help="show at most N rows")
    p_list.set_defaults(func=cmd_list)

    p_rej = sub.add_parser("reject", help="reject a candidate server path for one anime")
    p_rej.add_argument("anilist_id", type=int)
    p_rej.add_argument("path")
    p_rej.set_defaults(func=cmd_reject)

    p_rm = sub.add_parser("remove", help="remove an anime from the tracker")
    p_rm.add_argument("anilist_id", type=int)
    p_rm.set_defaults(func=cmd_remove)

    p_health = sub.add_parser("health", help="check AniList + DB + media roots")
    p_health.set_defaults(func=cmd_health)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
