from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from .redaction import redact_mapping


def _fingerprint(value: str) -> str:
    return hashlib.sha256((value or "").casefold().encode("utf-8")).hexdigest()[:12]


def _rows(connection: sqlite3.Connection, query: str, parameters: tuple = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query, parameters)]


def _distribution(connection: sqlite3.Connection, column: str) -> dict[str, int]:
    return {
        str(row[0] if row[0] not in (None, "") else "<empty>"): int(row[1])
        for row in connection.execute(f"SELECT [{column}], COUNT(*) FROM anime GROUP BY [{column}] ORDER BY COUNT(*) DESC")
    }


def inspect_legacy_database(path: Path) -> dict[str, Any]:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        table_names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        schema: dict[str, Any] = {}
        counts: dict[str, int] = {}
        for table in table_names:
            columns = [
                {
                    "name": row[1],
                    "type": row[2],
                    "not_null": bool(row[3]),
                    "default": row[4],
                    "primary_key_position": int(row[5]),
                }
                for row in connection.execute(f"PRAGMA table_info([{table}])")
            ]
            foreign_keys = [dict(row) for row in connection.execute(f"PRAGMA foreign_key_list([{table}])")]
            schema[table] = {"columns": columns, "foreign_keys": foreign_keys}
            counts[table] = int(connection.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0])

        indexes = [
            {"name": row[0], "table": row[1], "sql": row[2] or ""}
            for row in connection.execute(
                "SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        duplicate_ids = _rows(
            connection,
            "SELECT anilist_id, COUNT(*) AS count FROM anime GROUP BY anilist_id HAVING COUNT(*) > 1 ORDER BY anilist_id",
        )
        malformed_ids = int(connection.execute(
            "SELECT COUNT(*) FROM anime WHERE anilist_id IS NULL OR typeof(anilist_id) != 'integer' OR anilist_id <= 0"
        ).fetchone()[0])
        active_ids = {int(row[0]) for row in connection.execute("SELECT anilist_id FROM anime WHERE anilist_id IS NOT NULL")}

        orphan_specs = {
            "server_matches": "anilist_id",
            "rejected_matches": "anilist_id",
            "match_candidates": "anilist_id",
            "status_history": "anilist_id",
            "notification_events": "anilist_id",
        }
        orphan_counts: dict[str, int] = {}
        orphan_ids: set[int] = set()
        for table, column in orphan_specs.items():
            rows = connection.execute(
                f"SELECT [{column}] FROM [{table}] WHERE [{column}] IS NOT NULL AND [{column}] NOT IN (SELECT anilist_id FROM anime)"
            ).fetchall()
            orphan_counts[table] = len(rows)
            orphan_ids.update(int(row[0]) for row in rows)

        mapping_distribution = Counter(
            int(row[0]) for row in connection.execute("SELECT anilist_id FROM server_matches") if row[0] is not None
        )
        shared_paths = _rows(
            connection,
            "SELECT lower(path) AS path, COUNT(DISTINCT anilist_id) AS anilist_count "
            "FROM server_matches GROUP BY lower(path) HAVING COUNT(DISTINCT anilist_id) > 1 ORDER BY anilist_count DESC",
        )
        shared_path_summary = [
            {"path_fingerprint": _fingerprint(row["path"]), "anilist_count": row["anilist_count"]}
            for row in shared_paths
        ]
        mappings_per_id_histogram = Counter(mapping_distribution.values())
        settings = {}
        for row in connection.execute("SELECT key, value FROM settings ORDER BY key"):
            key, value = str(row[0]), str(row[1])
            if any(word in key.casefold() for word in ("secret", "webhook", "token", "password", "key")):
                settings[key] = "<redacted>"
            elif key in {"tv_path", "movie_path"}:
                settings[key] = f"<configured-path:{_fingerprint(value)}>"
            else:
                settings[key] = value

        syntactically_empty_paths = {
            "server_matches": int(connection.execute("SELECT COUNT(*) FROM server_matches WHERE trim(path)='' OR path IS NULL").fetchone()[0]),
            "rejected_matches": int(connection.execute("SELECT COUNT(*) FROM rejected_matches WHERE trim(path)='' OR path IS NULL").fetchone()[0]),
            "match_candidates": int(connection.execute("SELECT COUNT(*) FROM match_candidates WHERE trim(path)='' OR path IS NULL").fetchone()[0]),
        }
        windows_path_pattern = re.compile(r"^(?:[A-Za-z]:\\|\\\\)")
        syntactically_invalid_paths = {}
        for table in ("server_matches", "rejected_matches", "match_candidates"):
            values = [str(row[0] or "").replace("/", "\\") for row in connection.execute(f"SELECT path FROM [{table}]")]
            syntactically_invalid_paths[table] = sum(
                1 for value in values if value.strip() and not windows_path_pattern.match(value.strip())
            )
        inconsistent = {
            "tracker_on_server_but_server_not_on_server": int(connection.execute(
                "SELECT COUNT(*) FROM anime WHERE tracker_status='On Server' AND server_status NOT LIKE 'On Server%'"
            ).fetchone()[0]),
            "server_on_server_but_tracker_not_on_server": int(connection.execute(
                "SELECT COUNT(*) FROM anime WHERE server_status LIKE 'On Server%' AND tracker_status<>'On Server'"
            ).fetchone()[0]),
            "on_server_without_server_mapping": int(connection.execute(
                "SELECT COUNT(*) FROM anime a LEFT JOIN server_matches s ON s.anilist_id=a.anilist_id "
                "WHERE a.tracker_status='On Server' AND s.anilist_id IS NULL"
            ).fetchone()[0]),
            "active_mapping_but_tracker_not_on_server": int(connection.execute(
                "SELECT COUNT(*) FROM server_matches s JOIN anime a ON a.anilist_id=s.anilist_id WHERE a.tracker_status<>'On Server'"
            ).fetchone()[0]),
            "needs_review_without_review_server_status": int(connection.execute(
                "SELECT COUNT(*) FROM anime WHERE tracker_status='Needs Review' AND server_status NOT IN ('Needs Review','Missing - Needs Review')"
            ).fetchone()[0]),
        }
        result = {
            "report_format_version": 1,
            "source": {"kind": "read-only backup copy", "filename": path.name},
            "schema_version": {"explicit": False, "value": None, "note": "Legacy schema has no schema-version table."},
            "tables": schema,
            "indexes": indexes,
            "foreign_key_count": sum(len(item["foreign_keys"]) for item in schema.values()),
            "row_counts": counts,
            "identity": {
                "active_tracked_records": counts.get("anime", 0),
                "archived_records": 0,
                "removed_records_inferred_from_orphan_ids": len(orphan_ids),
                "duplicate_anilist_ids": duplicate_ids,
                "malformed_anilist_id_count": malformed_ids,
            },
            "server_mappings": {
                "rows": counts.get("server_matches", 0),
                "anilist_ids_with_mappings": len(mapping_distribution),
                "maximum_mappings_per_anilist_id": max(mapping_distribution.values(), default=0),
                "mappings_per_anilist_id_histogram": {
                    str(mapping_count): id_count for mapping_count, id_count in sorted(mappings_per_id_histogram.items())
                },
                "paths_shared_by_multiple_anilist_ids": shared_path_summary,
            },
            "rejected_mapping_rows": counts.get("rejected_matches", 0),
            "match_candidate_rows": counts.get("match_candidates", 0),
            "history_rows": counts.get("status_history", 0),
            "notification_deduplication_rows": counts.get("notification_events", 0),
            "announcement_baseline_rows": counts.get("jellyfin_announcement_snapshot", 0),
            "manual_announcement_rows": counts.get("manual_announcement_queue", 0),
            "manual_announcement_title_rows": counts.get("manual_announcement_titles", 0),
            "orphan_counts": orphan_counts,
            "stored_path_validation": {
                "filesystem_existence_checked": False,
                "reason": "Milestone 1 must not scan Jellyfin media.",
                "syntactically_empty_paths": syntactically_empty_paths,
                "syntactically_invalid_windows_paths": syntactically_invalid_paths,
            },
            "status_distributions": {
                "anilist_status": _distribution(connection, "airing_status"),
                "tracker_status": _distribution(connection, "tracker_status"),
                "server_status": _distribution(connection, "server_status"),
                "format": _distribution(connection, "format"),
                "movie_availability": _distribution(connection, "movie_availability"),
            },
            "inconsistent_status_combinations": inconsistent,
            "settings": settings,
        }
        return redact_mapping(result)
    finally:
        connection.close()


def inventory_markdown(report: dict[str, Any]) -> str:
    counts = report["row_counts"]
    lines = [
        "# Legacy Data Integrity Report",
        "",
        "This report was generated from the verified read-only modernization backup. It contains no webhook values and did not inspect Jellyfin media.",
        "",
        "## Schema",
        "",
        f"- Explicit schema version: **No**",
        f"- Tables: **{len(report['tables'])}**",
        f"- Explicit foreign keys: **{report['foreign_key_count']}**",
        f"- Non-system indexes: **{len(report['indexes'])}**",
        "",
        "## Row Counts",
        "",
    ]
    lines.extend(f"- `{table}`: {count}" for table, count in sorted(counts.items()))
    lines.extend(["", "## Tables And Columns", ""])
    for table, details in report["tables"].items():
        column_text = ", ".join(
            f"`{column['name']}` ({column['type'] or 'untyped'})" for column in details["columns"]
        )
        lines.append(f"- **`{table}`:** {column_text}")
    lines.extend(["", "## Indexes", ""])
    if report["indexes"]:
        lines.extend(f"- `{index['name']}` on `{index['table']}`" for index in report["indexes"])
    else:
        lines.append("- No non-system indexes.")
    lines.extend(["", "## Identity And Preservation", ""])
    identity = report["identity"]
    lines.extend([
        f"- Active tracked records: {identity['active_tracked_records']}",
        f"- Duplicate AniList IDs: {len(identity['duplicate_anilist_ids'])}",
        f"- Null or malformed AniList IDs: {identity['malformed_anilist_id_count']}",
        f"- Distinct removed identities inferred from orphan records: {identity['removed_records_inferred_from_orphan_ids']}",
        "- Legacy rows have no archived flag. Removed identities are not reassociated automatically.",
        "",
        "## Server Mapping Summary",
        "",
        f"- Rows: {report['server_mappings']['rows']}",
        f"- AniList IDs with mappings: {report['server_mappings']['anilist_ids_with_mappings']}",
        f"- Maximum mappings for one AniList ID: {report['server_mappings']['maximum_mappings_per_anilist_id']}",
        "- Mappings-per-ID histogram: " + ", ".join(
            f"{mapping_count} mapping(s)={id_count} ID(s)"
            for mapping_count, id_count in report['server_mappings']['mappings_per_anilist_id_histogram'].items()
        ),
        f"- Shared paths used by multiple AniList IDs: {len(report['server_mappings']['paths_shared_by_multiple_anilist_ids'])}",
        "",
        "## Orphaned Records",
        "",
    ])
    lines.extend(f"- `{table}`: {count}" for table, count in report["orphan_counts"].items())
    lines.extend(["", "Every orphan is retained by the prototype in `archived_legacy_records` with `Manual review required`.", "", "## Status Distributions", ""])
    for category, values in report["status_distributions"].items():
        lines.append(f"- **{category}:** " + ", ".join(f"{key}={value}" for key, value in values.items()))
    lines.extend(["", "## Consistency Checks", ""])
    lines.extend(f"- `{key}`: {value}" for key, value in report["inconsistent_status_combinations"].items())
    lines.extend([
        "",
        "## Stored Paths",
        "",
        "Path existence was not checked. Only stored values, syntax, and database references were examined; path details are represented by fingerprints where needed.",
        f"- Empty stored paths: {sum(report['stored_path_validation']['syntactically_empty_paths'].values())}",
        f"- Syntactically invalid Windows paths: {sum(report['stored_path_validation']['syntactically_invalid_windows_paths'].values())}",
        "",
        "## Settings",
        "",
    ])
    lines.extend(f"- `{key}`: `{value}`" for key, value in report["settings"].items())
    return "\n".join(lines) + "\n"


def write_inventory_reports(report: dict[str, Any], markdown_path: Path, json_path: Path) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(inventory_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
