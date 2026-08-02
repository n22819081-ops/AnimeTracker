from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path


def build_legacy_modern_comparison(legacy_copy: Path, modern_database: Path) -> dict:
    legacy=sqlite3.connect(f"file:{legacy_copy.as_posix()}?mode=ro&immutable=1",uri=True); legacy.row_factory=sqlite3.Row
    modern=sqlite3.connect(f"file:{modern_database.as_posix()}?mode=ro&immutable=1",uri=True); modern.row_factory=sqlite3.Row
    try:
        legacy_rows={int(row["anilist_id"]):row for row in legacy.execute("SELECT * FROM anime WHERE anilist_id IS NOT NULL") if int(row["anilist_id"])>0}
        modern_rows={int(row["anilist_id"]):row for row in modern.execute("""SELECT tm.anilist_id,tm.archived_at,am.anilist_status,ts.tracker_status,ts.server_presence,
        EXISTS(SELECT 1 FROM review_cases r WHERE r.anilist_id=tm.anilist_id AND r.state IN ('OPEN','ACKNOWLEDGED')) review_open,
        EXISTS(SELECT 1 FROM media_server_mappings m WHERE m.anilist_id=tm.anilist_id AND m.active=1) mapped
        FROM tracked_media tm JOIN anilist_media am ON am.anilist_id=tm.anilist_id LEFT JOIN tracking_state ts ON ts.tracked_media_id=tm.id""")}
        records=[]
        for anilist_id in sorted(modern_rows):
            old=legacy_rows.get(anilist_id); new=modern_rows[anilist_id]
            differences=[]
            if old is None: classification="POSSIBLE_MIGRATION_ERROR"; differences.append("Legacy active identity missing")
            else:
                if str(old["airing_status"] or "")!=str(new["anilist_status"] or ""): differences.append("AniList status differs")
                if str(old["tracker_status"] or "")!=str(new["tracker_status"] or ""): differences.append("Tracker status differs")
                legacy_on_server=str(old["server_status"] or "").startswith("On Server")
                modern_present=str(new["server_presence"] or "") in {"UNKNOWN_COVERAGE","PARTIAL","COMPLETE"}
                if legacy_on_server!=modern_present: differences.append("Server-presence interpretation differs")
                if str(old["tracker_status"] or "")=="Needs Review" or bool(new["review_open"]): classification="MODERN_UNCERTAINTY_PRESERVED"
                elif differences: classification="REQUIRES_MANUAL_REVIEW"
                elif legacy_on_server and str(new["server_presence"])=="UNKNOWN_COVERAGE": classification="EXPECTED_MODERNIZATION_IMPROVEMENT"
                else: classification="EQUIVALENT"
            records.append({"anilist_id":anilist_id,"legacy_anilist_status":str(old["airing_status"] or "") if old else "MISSING","modern_anilist_status":str(new["anilist_status"] or ""),"legacy_tracker_status":str(old["tracker_status"] or "") if old else "MISSING","modern_tracker_status":str(new["tracker_status"] or ""),"modern_server_presence":str(new["server_presence"] or ""),"modern_review_status":"OPEN" if new["review_open"] else "NONE","modern_mapping_present":bool(new["mapped"]),"classification":classification,"differences":differences})
        classes=Counter(item["classification"] for item in records)
        return {"report_format_version":1,"active_records_compared":len(records),"classification_counts":dict(sorted(classes.items())),"possible_migration_errors":sum(item["classification"]=="POSSIBLE_MIGRATION_ERROR" for item in records),"records":records}
    finally: legacy.close(); modern.close()


def comparison_markdown(report: dict) -> str:
    lines=["# Legacy-Modern Comparison Report","",f"All {report['active_records_compared']} active modern identities were compared against the verified legacy backup.","","## Classification Summary",""]
    lines.extend(f"- {key.replace('_',' ').title()}: {value}" for key,value in report["classification_counts"].items())
    lines.extend(["",f"Possible migration errors: {report['possible_migration_errors']}","","## Per-Title Comparison","","| AniList ID | Legacy tracker | Modern tracker | Server presence | Review | Classification |","|---:|---|---|---|---|---|"])
    for item in report["records"]: lines.append(f"| {item['anilist_id']} | {item['legacy_tracker_status']} | {item['modern_tracker_status']} | {item['modern_server_presence']} | {item['modern_review_status']} | {item['classification']} |")
    return "\n".join(lines)+"\n"


def write_comparison(report: dict, markdown_path: Path, json_path: Path) -> None:
    markdown_path.write_text(comparison_markdown(report),encoding="utf-8"); json_path.write_text(json.dumps(report,indent=2),encoding="utf-8")
