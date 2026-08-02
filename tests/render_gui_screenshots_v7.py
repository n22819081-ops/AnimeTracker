"""Render redacted synthetic Milestone 7 screenshots using Qt offscreen mode."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from anime_tracker.gui_qt.data import AnimeRow
from anime_tracker.gui_qt.dialogs import MatchingReviewDialog
from anime_tracker.gui_qt.main_window import MainWindow, PAGE_LABELS
from anime_tracker.gui_qt.profile import ModernProfile, PROTOTYPE_DATABASE


ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/"docs"/"screenshots"/"milestone_7"


def rows():
    return (
        AnimeRow(100,"Example Anime","Example Anime","例アニメ","TV","SPRING",2024,"FINISHED","On Server","COMPLETE","12/12","","NONE","2026-08-02",mapping_label="SERIES_SEASON · Season 01"),
        AnimeRow(200,"Example Anime Season 2","Example Anime 2","例アニメ2","TV","SUMMER",2026,"RELEASING","Currently Airing","PARTIAL","3/4","5","OPEN","2026-08-02",mapping_label="SERIES_SEASON · Season 02"),
        AnimeRow(300,"Example Anime OVA","Example OVA","例OVA","OVA","",2025,"FINISHED","Needs Review","NOT_FOUND","UNKNOWN","","OPEN","2026-08-01",mapping_label="SERIES_SPECIALS · Season 00"),
        AnimeRow(400,"Example Anime: The Movie","Example Movie","例映画","MOVIE","",2025,"FINISHED","On Server","COMPLETE","1/1","","NONE","2026-08-02",mapping_label="MOVIE_ITEM · Movies library"),
        AnimeRow(500,"Future Example","Future Example","未来","TV","FALL",2026,"NOT_YET_RELEASED","Upcoming","NOT_FOUND","NONE","","NONE","2026-08-01"),
    )


class SyntheticRepository:
    def tracked_media(self,*args,**kwargs):return rows()
    def dashboard_counts(self):return {"Currently Airing":1,"Missing Aired Episodes":1,"Finished / Ready to Add":0,"Upcoming This Month":1,"Movies Digitally Available":1,"On Server":2,"Needs Review":1,"Notification Queue Health":1}
    def notification_count(self,status):return 1 if status=="RETRY_WAIT" else 0
    def notification_rows(self):return ({"outbox_id":"safe","event_type":"NEW_EPISODE_AIRED","anilist_id":200,"channel_purpose":"PRIVATE_TRACKER","created_at":"2026-08-02 11:00 UTC","status":"RETRY_WAIT","attempt_count":1,"next_attempt_at":"2026-08-02 11:05 UTC","last_error_message":"Network timeout","delivered_at":"","payload_json":"{}"},)
    def review_rows(self):return ({"review_id":"review-safe","anilist_id":300,"review_type":"SPECIAL_PARENT_UNRESOLVED","severity":"BLOCKING","state":"OPEN","evidence_json":"Season 00 and a separate OVA folder are both plausible.","created_at":"2026-08-02"},)
    def history_rows(self):return ({"occurred":"MAPPING_CONFIRMED","occurred_at":"2026-08-02 10:30 UTC","source":"Manual confirmation"},)
    def import_preview(self):return {"active_titles":69,"archived_orphans":421,"baseline_rows":1312,"mappings":3,"rejections":2,"candidates":4}


def save(widget,name,app):
    widget.show(); app.processEvents(); widget.grab().save(str(OUTPUT/f"{name}.png")); widget.hide(); app.processEvents()


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True); app=QApplication.instance() or QApplication([]); app.setFont(QFont("Segoe UI",10))
    with tempfile.TemporaryDirectory() as folder:
        profile=ModernProfile(Path(folder)/"profile"); profile.initialize(prototype=PROTOTYPE_DATABASE)
        window=MainWindow(profile,SyntheticRepository()); window.resize(1380,860)
        for page,name in (("Dashboard","dashboard"),("Currently Airing","currently_airing"),("Franchises","franchises"),("Jellyfin Coverage","coverage"),("Notifications","notifications"),("Settings","settings")):
            window.show_page(page)
            if page=="Franchises":window.pages[page].tree.expandAll()
            if page=="Notifications":window.pages[page].tabs.setCurrentIndex(1)
            save(window,name,app)
        dialog=MatchingReviewDialog({"title":"Example Anime Season 2","candidates":[{"target":"Example Anime (2024), Season 02","confidence":"VERY STRONG","score":148,"evidence":"Exact title; Season 02 exists; Episodes 1-12 detected; folder year belongs to Season 1"}]},window); save(dialog,"matching_review",app)
        window.close(); app.processEvents()
    print(f"Rendered screenshots to {OUTPUT}")


if __name__=="__main__":main()
