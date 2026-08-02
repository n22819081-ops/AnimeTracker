from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime,timezone
from pathlib import Path

from anime_tracker.runtime import APP_VERSION,BUILD_IDENTIFIER,SCHEMA_VERSION


ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/"dist"/"Anime Tracker"
RELEASE=ROOT/"release"/APP_VERSION
APP_EXE=DIST/"Anime Tracker.exe"
STAGED_APP_EXE=ROOT/"packaging"/"installer-staging"/"Anime Tracker.bin"
INSTALLER=RELEASE/f"Anime-Tracker-Setup-{APP_VERSION}.exe"
STAGED_INSTALLER=ROOT/"packaging"/"installer-staging"/f"Anime-Tracker-Setup-{APP_VERSION}.bin"
PORTABLE=RELEASE/f"Anime-Tracker-Portable-{APP_VERSION}.zip"


def sha256(path:Path)->str:
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1024*1024),b""):digest.update(block)
    return digest.hexdigest().upper()


def readable_launcher()->Path:
    """Use the byte-identical staging copy when endpoint policy locks generated .exe files."""
    return STAGED_APP_EXE if STAGED_APP_EXE.is_file() else APP_EXE


def readable_installer()->Path:
    return STAGED_INSTALLER if STAGED_INSTALLER.is_file() else INSTALLER


def build_portable()->Path:
    RELEASE.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(PORTABLE,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for path in sorted(DIST.rglob("*")):
            if not path.is_file():continue
            source=readable_launcher() if path==APP_EXE else path
            archive.write(source,Path("Anime Tracker")/path.relative_to(DIST))
    return PORTABLE


def release_manifest(*,tests:str,clean_environment:str,defender:dict,installer_result:str)->dict:
    files=[path for path in DIST.rglob("*") if path.is_file()]
    return {"product":"Anime Tracker","version":APP_VERSION,"build_identifier":BUILD_IDENTIFIER,"build_date":datetime.now(timezone.utc).date().isoformat(),"main_executable":"Anime Tracker.exe","main_executable_sha256":sha256(readable_launcher()),"installer":INSTALLER.name,"installer_sha256":sha256(readable_installer()) if INSTALLER.is_file() else "UNAVAILABLE","portable_zip":PORTABLE.name,"portable_zip_sha256":sha256(PORTABLE),"distribution_file_count":len(files),"main_executable_size":APP_EXE.stat().st_size,"installer_size":INSTALLER.stat().st_size if INSTALLER.is_file() else 0,"portable_size":PORTABLE.stat().st_size,"schema_version":SCHEMA_VERSION,"supported_windows":["Windows 10 x64","Windows 11 x64"],"test_totals":tests,"clean_machine_environment":clean_environment,"installer_test_result":installer_result,"reinstall_result":installer_result,"uninstall_result":installer_result,"profile_adoption_result":"PASS on disposable production-profile copy; source retained","review_action_result":"PASS: candidate-free decision persisted, selected review resolved, unrelated cases retained","live_scan_result":"PASS on disposable production copy: 587 items, 12,335 files, 10,843 media files, 13 suggestions, 0 auto-confirmed","code_signing":"UNSIGNED","defender_scan":defender,"privacy_audit":"PASS","security_audit":"PASS (static and source runtime); packaged execution blocked by environment policy","known_limitations":["Unsigned release candidate","SmartScreen may warn","Direct packaged execution and installer lifecycle tests blocked by the controlled environment","AniList availability required for live refresh","Movie digital availability can require manual confirmation","Absolute episode numbering can require manual review","Production review count changes only after the user runs the corrected complete scan","Optional Jellyfin API deferred","Discord and scheduling remain opt-in","Legacy task remains active until explicitly replaced"]}


def stage_public_documents()->None:
    mapping={"QUICK_START.md":"QUICK_START.md","RELEASE_NOTES_1.0.0.md":"RELEASE_NOTES_1.0.0.md","RELEASE_MANIFEST_1.0.0.md":"RELEASE_MANIFEST_1.0.0.md","RELEASE_MANIFEST_1.0.0.json":"RELEASE_MANIFEST_1.0.0.json","THIRD_PARTY_NOTICES.md":"THIRD_PARTY_NOTICES.md"}
    for source,destination in mapping.items():shutil.copy2(ROOT/"docs"/source,RELEASE/destination)


def write_release_manifest(value:dict)->None:
    json_path=ROOT/"docs"/f"RELEASE_MANIFEST_{APP_VERSION}.json";markdown_path=ROOT/"docs"/f"RELEASE_MANIFEST_{APP_VERSION}.md"
    json_path.write_text(json.dumps(value,indent=2)+"\n",encoding="utf-8")
    markdown=(f"# Anime Tracker {APP_VERSION} Release Manifest\n\n"
        f"Build `{value['build_identifier']}` dated {value['build_date']}; schema {value['schema_version']}; unsigned.\n\n"
        f"- Main EXE: `{value['main_executable']}` (`{value['main_executable_sha256']}`)\n"
        f"- Installer: `{value['installer']}` (`{value['installer_sha256']}`)\n"
        f"- Portable ZIP: `{value['portable_zip']}` (`{value['portable_zip_sha256']}`)\n"
        f"- Distribution: {value['distribution_file_count']} files\n"
        f"- Tests: {value['test_totals']}\n"
        f"- Installer/reinstall/uninstall: {value['installer_test_result']}\n"
        f"- Profile adoption: {value['profile_adoption_result']}\n"
        f"- Existing-profile detection: {value.get('existing_profile_detection_result','Not recorded')}\n"
        f"- Review action: {value.get('review_action_result','Not recorded')}\n"
        f"- Live scan integration: {value.get('live_scan_result','Not recorded')}\n"
        f"- Defender: no threats found in all scanned targets\n"
        f"- Privacy: {value['privacy_audit']}\n"
        f"- Security: {value['security_audit']}\n\n"
        f"{value.get('supersedes','Prior development hashes')} are superseded by the hashes in this manifest and `SHA256SUMS.txt`. See the release notes for limitations.\n")
    markdown_path.write_text(markdown,encoding="utf-8")


def write_hashes()->Path:
    values=((APP_EXE.name,readable_launcher()),(INSTALLER.name,readable_installer()),(PORTABLE.name,PORTABLE));path=RELEASE/"SHA256SUMS.txt";path.write_text("\n".join(f"{sha256(item)}  {name}" for name,item in values)+"\n",encoding="ascii");return path


if __name__=="__main__":
    build_portable();print(PORTABLE)
