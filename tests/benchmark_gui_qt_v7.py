"""Offscreen Milestone 7 GUI baseline using the disposable schema-v5 profile."""

from __future__ import annotations

import json
import os
import statistics
import tempfile
import time
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM","offscreen")

from PySide6.QtWidgets import QApplication

from anime_tracker.gui_qt.covers import CoverImageCache
from anime_tracker.gui_qt.data import ModernRepository
from anime_tracker.gui_qt.main_window import MainWindow, PAGE_LABELS
from anime_tracker.gui_qt.pages import DashboardPage, FranchisePage, ReviewPage
from anime_tracker.gui_qt.profile import ModernProfile, PROTOTYPE_DATABASE
from anime_tracker.gui_qt.widgets import AnimeTable


def measure(operation,repetitions=7):
    values=[]
    for _ in range(repetitions):started=time.perf_counter(); operation(); values.append((time.perf_counter()-started)*1000)
    return statistics.median(values)


def main():
    app=QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as folder:
        profile=ModernProfile(Path(folder)/"profile"); profile.initialize(prototype=PROTOTYPE_DATABASE); repo=ModernRepository(profile.database_path); rows=repo.tracked_media()
        windows=[]
        def construct():
            window=MainWindow(profile,repo); windows.append(window); app.processEvents(); window.close(); app.processEvents()
        construction=measure(construct,3)
        dashboard=DashboardPage(repo); dashboard_population=measure(dashboard.refresh,10)
        table=AnimeTable(); table_population=measure(lambda:table.set_rows(rows),15)
        search=measure(lambda:(table.set_search("airing tv"),table.set_search("")),30)
        franchise=measure(lambda:FranchisePage(repo),7); review=measure(lambda:ReviewPage(repo),7)
        window=MainWindow(profile,repo); app.processEvents()
        switching=measure(lambda:[window.show_page(label) for label in PAGE_LABELS],10)
        table.set_rows(rows); changed=replace(rows[0],coverage="Updated"); one_row=measure(lambda:table.model.update_row(changed),50)
        covers=CoverImageCache(Path(folder)/"covers"); placeholders=measure(lambda:[covers.placeholder() for _ in range(69)],20)
        window.close(); app.processEvents()
        print(json.dumps({
            "main_window_construction_ms_median":round(construction,4),
            "dashboard_population_ms_median":round(dashboard_population,4),
            "table_69_rows_ms_median":round(table_population,4),
            "search_filter_ms_median":round(search,4),
            "franchise_page_ms_median":round(franchise,4),
            "review_page_ms_median":round(review,4),
            "switch_all_pages_ms_median":round(switching,4),
            "update_one_row_ms_median":round(one_row,4),
            "create_69_cover_placeholders_ms_median":round(placeholders,4),
        },indent=2,sort_keys=True))


if __name__=="__main__":main()
