from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Y, BooleanVar, Button, Canvas, Checkbutton, Entry, Frame, Label, Menu, StringVar, Tk, Toplevel, messagebox, simpledialog
from tkinter import filedialog, ttk

from .anilist import AniListClient, AniListError, parse_anilist_input
from .announcements import (
    LibraryChange,
    LibraryInventoryError,
    SnapshotItem,
    announcement_review_required,
    build_library_snapshot,
    default_selected,
    detect_changes,
    send_reviewed_batch,
    shared_announcements_apply_to_scan,
)
from .config import NotificationConfig, load_notification_config, masked_webhook, save_notification_config, save_shared_silent_setting
from .constants import (
    APP_NAME,
    LOG_DIR,
    SERVER_MISSING_NEEDS_REVIEW,
    SERVER_NEEDS_REVIEW,
    SERVER_NOT_FOUND,
    SERVER_ON_SERVER,
    SERVER_ON_SERVER_MANUAL,
    REVIEW_MULTIPLE_MATCHES,
    REVIEW_NO_MATCH,
    REVIEW_POSSIBLE_MATCHES,
    TRACKER_AIRING,
    TRACKER_GROUPS,
    TRACKER_NEEDS_REVIEW,
    TRACKER_ON_SERVER,
    TRACKER_READY,
    TRACKER_UPCOMING,
)
from .database import Database
from .models import AnimeRecord
from .manual_announcements import (
    DuplicateManualAnnouncementError,
    ManualAnnouncement,
    ManualAnnouncementValidationError,
    build_manual_announcement,
)
from .notifications import Notifier
from .path_utils import normalize_windows_path
from .review import build_review_state
from .scheduler import ScheduledCheckStats, record_schedule_install, run_scheduled_check
from .scanner import (
    confirmed_match_has_evidence,
    infer_tracked_seasons,
    match_record,
    multi_season_ids,
    scan_roots,
)
from .status import is_meaningful_transition, notification_key, tracker_status_from_anilist
from .task_scheduler import (
    build_elevated_scheduled_task_args,
    build_verify_task_args,
    format_command_for_error,
    is_uac_cancellation,
    parse_task_verification,
    registration_error_message,
)
from .theme import apply_theme, palette, style_window
from .tree_copy import COPY_ANILIST_ID, COPY_ENGLISH_TITLE, COPY_ROMAJI_TITLE, COPY_SELECTED_ROW, copy_value, default_copy_value, row_to_select
from .ui_layout import MAINTENANCE_ACTIONS, MAIN_TOOLBAR_ACTIONS


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=LOG_DIR / "anime_tracker.log",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


class AnimeTrackerApp:
    def __init__(self) -> None:
        setup_logging()
        self.db = Database()
        self.client = AniListClient()
        self.notifier = Notifier(load_notification_config())
        self.root = Tk()
        self.root.title(APP_NAME)
        self.root.geometry("1220x680")
        self.theme_choice = self.db.get_settings().get("theme", "Dark")
        apply_theme(self.root, self.theme_choice)
        self.search_var = StringVar()
        self.filter_var = StringVar(value="All")
        self.sort_column = "english_title"
        self.sort_reverse = False
        self.rows = []
        self._operation_lock = threading.Lock()
        self._announcement_review_active = False
        self._build_ui()
        self.refresh_table()

    def run(self) -> None:
        self.root.mainloop()

    def _build_ui(self) -> None:
        top = Frame(self.root)
        top.pack(fill=X, padx=8, pady=8)
        Label(top, text="Search").pack(side=LEFT)
        search = Entry(top, textvariable=self.search_var, width=30)
        search.pack(side=LEFT, padx=6)
        search.bind("<KeyRelease>", lambda _event: self.refresh_table())
        Label(top, text="Status").pack(side=LEFT, padx=(12, 0))
        filter_box = ttk.Combobox(top, textvariable=self.filter_var, values=["All"] + TRACKER_GROUPS, width=26, state="readonly")
        filter_box.pack(side=LEFT, padx=6)
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self.refresh_table())

        button_bar = Frame(self.root)
        button_bar.pack(fill=X, padx=8)
        for text, action in MAIN_TOOLBAR_ACTIONS:
            Button(button_bar, text=text, command=self._command_for_action(action)).pack(side=LEFT, padx=3, pady=6)

        columns = (
            "id",
            "english_title",
            "romaji_title",
            "anilist_id",
            "season",
            "year",
            "format",
            "relation_label",
            "airing_status",
            "tracker_status",
            "server_status",
            "review_reason",
            "detected_server_path",
        )
        table_frame = Frame(self.root)
        table_frame.pack(fill=BOTH, expand=True, padx=8, pady=8)
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings")
        headings = {
            "id": "ID",
            "english_title": "Full English Title",
            "romaji_title": "Romaji Title",
            "anilist_id": "AniList ID",
            "season": "Season",
            "year": "Year",
            "format": "Format",
            "relation_label": "Relation / Season Label",
            "airing_status": "AniList Status",
            "tracker_status": "Tracker Status",
            "server_status": "Server Status",
            "review_reason": "Review Reason",
            "detected_server_path": "Detected Path",
        }
        widths = {
            "id": 50,
            "english_title": 320,
            "romaji_title": 280,
            "anilist_id": 95,
            "season": 90,
            "year": 75,
            "format": 80,
            "relation_label": 175,
            "airing_status": 110,
            "tracker_status": 170,
            "server_status": 160,
            "review_reason": 230,
            "detected_server_path": 440,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column], command=lambda c=column: self.sort_by(c))
            self.tree.column(column, width=widths[column], minwidth=60, anchor="w", stretch=True)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        self._configure_status_tags()
        self._configure_tree_copy_actions()
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)
        self.status_label = Label(self.root, text="Ready", anchor="w")
        self.status_label.pack(fill=X, padx=8, pady=(0, 8))
        self.schedule_label = Label(self.root, text="", anchor="w")
        self.schedule_label.pack(fill=X, padx=8, pady=(0, 8))
        self.refresh_schedule_summary()

    def _command_for_action(self, action: str):
        if action == "check_all_threaded":
            return lambda: self.run_threaded(self.check_all)
        if action == "scan_jellyfin_threaded":
            return self.start_jellyfin_scan
        if action == "run_scheduled_check_now_threaded":
            return lambda: self.run_threaded(self.run_scheduled_check_now)
        return getattr(self, action)

    def start_jellyfin_scan(self) -> None:
        if self._announcement_review_active:
            messagebox.showinfo(APP_NAME, "Finish or cancel the open announcement review before scanning again.")
            return
        self.run_threaded(self.scan_jellyfin)

    def _configure_tree_copy_actions(self) -> None:
        colors = palette(self.theme_choice)
        self.tree_copy_menu = Menu(self.root, tearoff=0, bg=colors["panel"], fg=colors["text"], activebackground=colors["selected"], activeforeground=colors["text"])
        self.tree_copy_menu.add_command(label="Copy English Title", command=lambda: self.copy_selected_tree_value(COPY_ENGLISH_TITLE))
        self.tree_copy_menu.add_command(label="Copy Romaji Title", command=lambda: self.copy_selected_tree_value(COPY_ROMAJI_TITLE))
        self.tree_copy_menu.add_command(label="Copy AniList ID", command=lambda: self.copy_selected_tree_value(COPY_ANILIST_ID))
        self.tree_copy_menu.add_separator()
        self.tree_copy_menu.add_command(label="Copy Selected Row", command=lambda: self.copy_selected_tree_value(COPY_SELECTED_ROW))
        self.tree.bind("<Button-3>", self.show_tree_context_menu)
        self.tree.bind("<Control-c>", self.copy_default_tree_value)

    def show_tree_context_menu(self, event) -> None:
        row_id = row_to_select(self.tree.identify_row(event.y))
        if not row_id:
            return
        self.tree.selection_set(row_id)
        self.tree.focus(row_id)
        self.tree_copy_menu.tk_popup(event.x_root, event.y_root)

    def copy_selected_tree_value(self, action: str) -> None:
        row = self.selected_row()
        if not row:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(copy_value(dict(row), action))

    def copy_default_tree_value(self, _event=None) -> str:
        row = self.selected_row()
        if not row:
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(default_copy_value(dict(row)))
        return "break"

    def sort_by(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False
        self.refresh_table()

    def refresh_table(self) -> None:
        query = self.search_var.get().lower().strip()
        status_filter = self.filter_var.get()
        rows = self.db.rows()
        if query:
            rows = [
                row for row in rows
                if query in row["english_title"].lower()
                or query in row["romaji_title"].lower()
                or query in row["native_title"].lower()
                or query in row["alternate_titles"].lower()
            ]
        if status_filter != "All":
            rows = [row for row in rows if row["tracker_status"] == status_filter]
        rows.sort(key=lambda row: str(row[self.sort_column] or "").lower(), reverse=self.sort_reverse)
        self.rows = rows
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in rows:
            self.tree.insert(
                "",
                END,
                iid=str(row["id"]),
                tags=(row["tracker_status"],),
                values=(
                    row["id"],
                    row["english_title"],
                    row["romaji_title"],
                    row["anilist_id"],
                    row["season"],
                    row["year"] or "",
                    row["format"],
                    row["relation_label"],
                    row["airing_status"],
                    row["tracker_status"],
                    row["server_status"],
                    row["review_reason"],
                    row["detected_server_path"],
                ),
            )
        self.status_label.config(text=f"{len(rows)} item(s)")
        self.refresh_schedule_summary()

    def refresh_schedule_summary(self) -> None:
        settings = self.db.get_settings()
        text = (
            f"Last scheduled check: {settings.get('scheduled_last_check', '') or 'Never'} | "
            f"Next scheduled check: {settings.get('scheduled_next_check', '') or 'Not installed'} | "
            f"Last result: {settings.get('scheduled_last_result', 'Never run')} | "
            f"Titles updated: {settings.get('scheduled_titles_updated', '0')} | "
            f"Moved On Server: {settings.get('scheduled_moved_on_server', '0')} | "
            f"Moved Ready: {settings.get('scheduled_moved_ready', '0')}"
        )
        if hasattr(self, "schedule_label"):
            self.schedule_label.config(text=text)

    def _configure_status_tags(self) -> None:
        colors = {
            TRACKER_UPCOMING: "#9ecbff",
            TRACKER_AIRING: "#7ee787",
            TRACKER_READY: "#ffd866",
            "Movie Theatrical Only": "#c9a0ff",
            "Movie Digitally Available": "#ffb86c",
            TRACKER_ON_SERVER: "#8be9fd",
            TRACKER_NEEDS_REVIEW: "#ff7b72",
        }
        for status, color in colors.items():
            self.tree.tag_configure(status, foreground=color)

    def selected_row(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo(APP_NAME, "Select an anime first.")
            return None
        return self.db.get(int(selected[0]))

    def add_anime(self) -> None:
        value = simpledialog.askstring(APP_NAME, "Enter an anime title, AniList URL, or AniList ID:")
        if not value:
            return
        self.run_threaded(lambda: self._add_anime_worker(value))

    def _add_anime_worker(self, value: str) -> None:
        try:
            parsed = parse_anilist_input(value)
            if isinstance(parsed, int):
                media = self.client.get_by_id(parsed)
            else:
                matches = self.client.search(parsed)
                if not matches:
                    self.show_message("No Results", "AniList did not return any matches.")
                    return
                media = matches[0] if len(matches) == 1 else self.choose_match(matches)
                if media is None:
                    return
            status = tracker_status_from_anilist(media.get("status") or "", media.get("format") or "")
            record = AnimeRecord.from_anilist(media, status)
            self.db.upsert_anime(record)
            self.root.after(0, self.refresh_table)
        except AniListError as exc:
            self.show_error("AniList Error", str(exc))

    def choose_match(self, matches):
        result = {"media": None}
        event = threading.Event()

        def open_dialog():
            window = Toplevel(self.root)
            style_window(window, self.theme_choice)
            window.title("Select AniList Match")
            window.geometry("760x360")
            tree = ttk.Treeview(window, columns=("id", "title", "format", "year", "status"), show="headings")
            for column in ("id", "title", "format", "year", "status"):
                tree.heading(column, text=column.title())
                tree.column(column, width=130 if column != "title" else 300)
            tree.pack(fill=BOTH, expand=True, padx=8, pady=8)
            for media in matches:
                title = (media.get("title") or {}).get("english") or (media.get("title") or {}).get("romaji") or ""
                tree.insert("", END, iid=str(media["id"]), values=(media["id"], title, media.get("format") or "", media.get("seasonYear") or "", media.get("status") or ""))

            def select():
                selected = tree.selection()
                if selected:
                    result["media"] = next(item for item in matches if str(item["id"]) == selected[0])
                window.destroy()
                event.set()

            Button(window, text="Select", command=select).pack(side=RIGHT, padx=8, pady=8)
            Button(window, text="Cancel", command=lambda: (window.destroy(), event.set())).pack(side=RIGHT, padx=8, pady=8)
            window.protocol("WM_DELETE_WINDOW", lambda: (window.destroy(), event.set()))

        self.root.after(0, open_dialog)
        event.wait()
        return result["media"]

    def check_all(self, silent: bool = False) -> None:
        self.db.backup("bulk-check")
        changed = 0
        for row in self.db.rows():
            try:
                media = self.client.get_by_id(row["anilist_id"])
                movie_availability = row["movie_availability"] or "unknown"
                new_status = tracker_status_from_anilist(media.get("status") or "", media.get("format") or "", movie_availability)
                display_status = TRACKER_ON_SERVER if row["tracker_status"] == TRACKER_ON_SERVER else new_status
                record = AnimeRecord.from_anilist(media, new_status)
                record.movie_availability = movie_availability
                old_status = row["tracker_status"]
                state = row["notification_state"] or ""
                if self._notify_status_change(row, old_status, new_status, record.cover_image_url):
                    state = notification_key(row["anilist_id"], old_status, new_status)
                    changed += 1
                if self._notify_release_date_change(row, record):
                    changed += 1
                record.tracker_status = display_status
                self.db.update_from_anilist(row["id"], record, old_status, state)
                self.db.reset_api_failure(row["id"])
            except Exception as exc:
                logging.exception("Refresh failed for %s: %s", row["anilist_id"], exc)
                self._record_api_failure(row)
        if not silent:
            self.show_message(APP_NAME, f"Status refresh complete. {changed} meaningful change(s).")
            self.root.after(0, self.refresh_table)

    def scan_jellyfin(self, silent: bool = False) -> None:
        self.db.backup("server-scan")
        settings = self.db.get_settings()
        candidates = scan_roots(settings.get("tv_path", ""), settings.get("movie_path", ""))
        rows = self.db.rows()
        season_numbers = infer_tracked_seasons(rows)
        multi_ids = multi_season_ids(rows)
        found = 0
        uncertain = 0
        for row in rows:
            season_number = season_numbers.get(row["anilist_id"])
            rejected_paths = self.db.rejected_paths_for(row["anilist_id"])
            confirmed = self.db.confirmed_match_for(row["anilist_id"])
            if confirmed and normalize_windows_path(confirmed["path"]) in rejected_paths:
                self.db.remove_confirmed_match(row["anilist_id"], confirmed["path"])
                confirmed = None
            if confirmed:
                confirmed_path = Path(confirmed["path"])
                if confirmed_path.exists():
                    if confirmed_match_has_evidence(confirmed, candidates, season_number):
                        if row["tracker_status"] != TRACKER_ON_SERVER or row["server_status"] != SERVER_ON_SERVER:
                            self.db.set_on_server(
                                row["id"], confirmed["path"], SERVER_ON_SERVER, row["manual_notes"],
                                "Confirmed server match retained", confirmed["confirmation_type"],
                            )
                        continue
                    self.db.clear_unsupported_automatic_match(row["id"], confirmed["path"])
                    confirmed = None
                if confirmed is None:
                    pass
                else:
                    self.db.set_needs_review_missing(row["id"], confirmed["path"])
                    key = f"server-missing:{row['anilist_id']}:{confirmed['path']}"
                    if not self.db.event_was_sent(key):
                        self.notifier.send_anime_event(
                            "Confirmed Jellyfin Folder Missing",
                            row,
                            TRACKER_ON_SERVER,
                            TRACKER_NEEDS_REVIEW,
                            False,
                            "server-missing",
                            row["cover_image_url"],
                            {"Previous Path": confirmed["path"]},
                        )
                        self.db.mark_event_sent(key, "server-missing", row["anilist_id"])
                    uncertain += 1
                    continue
            result = match_record(row, candidates, rejected_paths, season_number, multi_ids)
            self.db.save_match_candidates(row["anilist_id"], result.candidates)
            if result.confidence == "confident":
                previous_status = row["tracker_status"]
                self.db.set_on_server(
                    row["id"], result.path, SERVER_ON_SERVER, row["manual_notes"],
                    f"{previous_status} -> On Server", "automatic",
                )
                self._notify_found_on_server(row, previous_status, result.path)
                found += 1
            elif result.confidence == "uncertain":
                reason = REVIEW_MULTIPLE_MATCHES if len(result.candidates) > 1 else REVIEW_POSSIBLE_MATCHES
                self.db.set_review_state(row["id"], SERVER_NEEDS_REVIEW, TRACKER_NEEDS_REVIEW, reason, row["detected_server_path"], result.notes)
                uncertain += 1
            else:
                self.db.mark_no_match_found(row["id"])
        if shared_announcements_apply_to_scan(silent):
            self.show_message(APP_NAME, f"Jellyfin scan complete. Found {found}; needs review {uncertain}.")
            self.root.after(0, self.refresh_table)
            config = load_notification_config()
            if config.shared_announcements_enabled:
                if not config.has_shared_webhook:
                    self.show_error(APP_NAME, "Shared announcements are enabled, but no shared Discord webhook is saved.")
                else:
                    try:
                        snapshot = build_library_snapshot(settings.get("tv_path", ""), settings.get("movie_path", ""))
                    except LibraryInventoryError as exc:
                        self.show_error(APP_NAME, f"Shared announcement scan was not completed.\n\n{exc}\n\nThe previous baseline was preserved.")
                    else:
                        self.root.after(0, lambda current=snapshot, cfg=config: self._review_library_announcements(current, cfg))

    def _review_library_announcements(self, current: list[SnapshotItem], config: NotificationConfig) -> None:
        if self._announcement_review_active:
            messagebox.showinfo(APP_NAME, "An announcement review is already open. The duplicate review was not created.")
            return
        self._announcement_review_active = True
        if not self.db.has_announcement_baseline():
            self._offer_announcement_baseline(current)
            return
        changes = detect_changes(self.db.get_announcement_snapshot(), current)
        manual_items = self.db.manual_announcements()
        if not announcement_review_required(changes, manual_items):
            self._announcement_review_active = False
            messagebox.showinfo(APP_NAME, "No Jellyfin library changes detected.")
            return
        self._open_announcement_review(current, changes, manual_items, config)

    def _offer_announcement_baseline(self, current: list[SnapshotItem]) -> None:
        window = Toplevel(self.root)
        style_window(window, self.theme_choice)
        window.title("Jellyfin Announcement Baseline")
        window.transient(self.root)
        window.grab_set()
        Label(
            window,
            text="No announcement baseline exists yet. The current Jellyfin library will be saved as the starting point.\nNo Discord messages will be sent.",
            justify="left",
        ).pack(fill=X, padx=16, pady=16)
        actions = Frame(window)
        actions.pack(fill=X, padx=12, pady=(0, 12))

        def create_baseline() -> None:
            try:
                self.db.replace_announcement_snapshot(current)
            except Exception as exc:
                logging.exception("Announcement baseline creation failed")
                messagebox.showerror(APP_NAME, f"The announcement baseline could not be saved: {exc}", parent=window)
                return
            window.destroy()
            self._announcement_review_active = False
            messagebox.showinfo(APP_NAME, "Announcement baseline created. No Discord message was sent.")

        Button(actions, text="Create Baseline", command=create_baseline).pack(side=RIGHT, padx=4)
        def cancel_baseline() -> None:
            self._announcement_review_active = False
            window.destroy()

        Button(actions, text="Cancel", command=cancel_baseline).pack(side=RIGHT, padx=4)
        window.protocol("WM_DELETE_WINDOW", cancel_baseline)

    def _open_announcement_review(
        self,
        current: list[SnapshotItem],
        changes: list[LibraryChange],
        manual_items: list[ManualAnnouncement],
        config: NotificationConfig,
    ) -> None:
        window = Toplevel(self.root)
        style_window(window, self.theme_choice)
        window.title("Review Jellyfin Announcements")
        window.geometry("720x520")
        window.minsize(620, 420)
        window.transient(self.root)
        window.grab_set()
        body = Frame(window)
        body.pack(fill=BOTH, expand=True)
        canvas = Canvas(body, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=canvas.yview)
        scrollable = Frame(canvas)
        scrollable.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas_window = canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=LEFT, fill=BOTH, expand=True)
        scrollbar.pack(side=RIGHT, fill=Y)
        choices: list[tuple[LibraryChange, BooleanVar]] = []
        for change_type, heading in (("added", "Added"), ("removed", "Removed")):
            section_changes = [item for item in changes if item.change_type == change_type]
            if not section_changes:
                continue
            section = ttk.LabelFrame(scrollable, text=heading)
            section.pack(fill=X, padx=12, pady=8)
            for change in section_changes:
                selected = BooleanVar(value=default_selected(change, config.shared_announce_additions, config.shared_announce_removals))
                Checkbutton(section, text=change.display_text, variable=selected, anchor="w").pack(fill=X, padx=8, pady=3)
                choices.append((change, selected))
        manual_choices: list[tuple[ManualAnnouncement, BooleanVar]] = []
        if manual_items:
            manual_section = ttk.LabelFrame(scrollable, text="Manual Announcements")
            manual_section.pack(fill=X, padx=12, pady=8)
            for item in manual_items:
                selected = BooleanVar(value=config.shared_announcements_enabled)
                Checkbutton(manual_section, text=item.display_text, variable=selected, anchor="w").pack(fill=X, padx=8, pady=3)
                manual_choices.append((item, selected))
        status = Label(window, text="", anchor="w")
        status.pack(fill=X, padx=12)
        actions = Frame(window, name="fixed_review_actions")
        actions.pack(fill=X, padx=12, pady=12)
        send_button = Button(actions, text="Send Selected Announcements")
        send_button.pack(side=RIGHT, padx=4)
        def cancel_review() -> None:
            self._announcement_review_active = False
            window.destroy()

        Button(actions, text="Cancel", command=cancel_review).pack(side=RIGHT, padx=4)
        window.protocol("WM_DELETE_WINDOW", cancel_review)

        def send_selected() -> None:
            selected = [change for change, variable in choices if variable.get()]
            selected_manual = [item for item, variable in manual_choices if variable.get()]
            manual_changes = [
                LibraryChange(
                    "added",
                    "TV_EPISODE" if item.media_type == "TV_SHOW" else "MOVIE",
                    item.title,
                    item.year,
                    custom_display=item.display_text,
                )
                for item in selected_manual
            ]
            combined = selected + manual_changes
            if not combined:
                messagebox.showinfo(APP_NAME, "Select at least one library change to announce.", parent=window)
                return
            send_button.config(state="disabled")
            status.config(text="Sending selected announcements...")

            def worker() -> None:
                error = None
                try:
                    sent = send_reviewed_batch(
                        self.db,
                        config.shared_discord_webhook_url,
                        combined,
                        current,
                        send_silently=config.shared_send_silently,
                        manual_queue_ids=[item.id for item in selected_manual if item.id is not None],
                    )
                except Exception as exc:
                    logging.exception("Announcement snapshot update failed")
                    sent = False
                    error = exc

                def finish() -> None:
                    if not sent:
                        send_button.config(state="normal")
                        status.config(text="Sending or snapshot storage failed. The baseline was not updated; you can retry.")
                        detail = f" ({type(error).__name__})" if error else ""
                        messagebox.showerror(APP_NAME, f"Shared announcements were not completed{detail}. The baseline was preserved.", parent=window)
                        return
                    window.destroy()
                    self._announcement_review_active = False
                    delivery = " silently" if config.shared_send_silently else ""
                    messagebox.showinfo(APP_NAME, f"Selected Jellyfin announcements were sent{delivery}.")

                self.root.after(0, finish)

            threading.Thread(target=worker, daemon=True).start()

        send_button.config(command=send_selected)

    def mark_added(self) -> None:
        row = self.selected_row()
        if not row:
            return
        if row["detected_server_path"]:
            self.db.set_on_server(row["id"], row["detected_server_path"], SERVER_ON_SERVER, row["manual_notes"], "Manually marked on server")
            self.refresh_table()
            return
        self._open_mark_added_choice(row)

    def _open_mark_added_choice(self, row) -> None:
        window = Toplevel(self.root)
        style_window(window, self.theme_choice)
        window.title("Mark Added")
        Label(window, text=f"No confirmed Jellyfin path is saved for {row['english_title']}.").pack(fill=X, padx=12, pady=10)

        def select_folder():
            window.destroy()
            self.select_jellyfin_folder(row)

        def manual_without_path():
            notes = (row["manual_notes"] or "").strip()
            if notes:
                notes += "\n"
            notes += "Manually confirmed on server without a saved path."
            self.db.set_on_server(row["id"], "", SERVER_ON_SERVER_MANUAL, notes, "Manually marked on server")
            self.refresh_table()
            window.destroy()

        Button(window, text="Select Jellyfin Folder", command=select_folder).pack(fill=X, padx=12, pady=4)
        Button(window, text="Mark On Server Without Path", command=manual_without_path).pack(fill=X, padx=12, pady=4)
        Button(window, text="Cancel", command=window.destroy).pack(fill=X, padx=12, pady=(4, 12))

    def select_jellyfin_folder(self, row=None) -> None:
        row = row or self.selected_row()
        if not row:
            return
        settings = self.db.get_settings()
        initial = settings.get("tv_path") if row["format"] != "MOVIE" else settings.get("movie_path")
        path = filedialog.askdirectory(title="Select existing Jellyfin folder", initialdir=initial or "")
        if not path:
            return
        self.db.set_on_server(row["id"], path, SERVER_ON_SERVER_MANUAL, row["manual_notes"], "Manually selected Jellyfin folder")
        self.refresh_table()

    def edit_selected(self) -> None:
        row = self.selected_row()
        if not row:
            return
        window = Toplevel(self.root)
        style_window(window, self.theme_choice)
        window.title(f"Edit {row['english_title']}")
        fields = {
            "tracker_status": StringVar(value=row["tracker_status"]),
            "server_status": StringVar(value=row["server_status"]),
            "detected_server_path": StringVar(value=row["detected_server_path"]),
            "movie_availability": StringVar(value=row["movie_availability"]),
            "manual_notes": StringVar(value=row["manual_notes"]),
        }
        labels = [
            ("Tracker Status", "tracker_status"),
            ("Server Status", "server_status"),
            ("Detected Server Path", "detected_server_path"),
            ("Movie Availability (unknown/digital)", "movie_availability"),
            ("Manual Notes", "manual_notes"),
        ]
        for idx, (label, key) in enumerate(labels):
            Label(window, text=label).grid(row=idx, column=0, sticky="w", padx=8, pady=4)
            if key == "tracker_status":
                ttk.Combobox(window, textvariable=fields[key], values=TRACKER_GROUPS, width=40).grid(row=idx, column=1, padx=8, pady=4)
            else:
                Entry(window, textvariable=fields[key], width=70).grid(row=idx, column=1, padx=8, pady=4)

        def save():
            self.db.update_manual(
                row["id"],
                fields["tracker_status"].get(),
                fields["server_status"].get(),
                fields["detected_server_path"].get(),
                fields["manual_notes"].get(),
                fields["movie_availability"].get(),
            )
            window.destroy()
            self.refresh_table()

        Button(window, text="Save", command=save).grid(row=len(labels), column=1, sticky="e", padx=8, pady=8)

    def review_match(self) -> None:
        row = self.selected_row()
        if not row:
            return
        candidates = self.db.get_match_candidates(row["anilist_id"])
        review_state = build_review_state(row, candidates)
        window = Toplevel(self.root)
        style_window(window, self.theme_choice)
        window.title(f"Review Match - {row['english_title']}")
        window.geometry("980x560")
        details = (
            f"English: {row['english_title']}\n"
            f"Romaji: {row['romaji_title']}\n"
            f"AniList ID: {row['anilist_id']} | Season: {row['season']} {row['year'] or ''} | Format: {row['format']}\n"
            f"Relation / Season Label: {row['relation_label'] or 'Unknown'}\n"
            f"Episodes: {row['total_episodes'] or 'Unknown'} | AniList Status: {row['airing_status']}\n"
            f"Tracker Status: {row['tracker_status']} | Server Status: {row['server_status']}"
        )
        Label(window, text=details, justify=LEFT, anchor="w").pack(fill=X, padx=10, pady=8)
        Label(window, text=f"Why this item needs review: {review_state['reason']}", justify=LEFT, anchor="w").pack(fill=X, padx=10, pady=(0, 8))
        columns = ("score", "confidence", "path", "reasons")
        tree = ttk.Treeview(window, columns=columns, show="headings", height=12)
        tree.heading("score", text="Confidence Score")
        tree.heading("confidence", text="Confidence")
        tree.heading("path", text="Exact Jellyfin Path")
        tree.heading("reasons", text="Reasons")
        tree.column("score", width=120, anchor="w")
        tree.column("confidence", width=110, anchor="w")
        tree.column("path", width=390, anchor="w")
        tree.column("reasons", width=340, anchor="w")
        x_scroll = ttk.Scrollbar(window, orient="horizontal", command=tree.xview)
        tree.configure(xscrollcommand=x_scroll.set)
        tree.pack(fill=BOTH, expand=True, padx=10, pady=(0, 0))
        x_scroll.pack(fill=X, padx=10)
        if candidates:
            for candidate in candidates:
                reasons = "; ".join(json.loads(candidate["reasons"] or "[]"))
                tree.insert("", END, iid=candidate["path"], values=(candidate["score"], candidate["confidence"], candidate["path"], reasons))
        else:
            tree.insert("", END, iid="__empty__", values=("", "", "No possible Jellyfin matches were found.", "This title may not be on the server, or the folder name may be too different for automatic matching."))

        def selected_path() -> str | None:
            selected = tree.selection()
            if not selected:
                messagebox.showinfo(APP_NAME, "Select a proposed match first.")
                return None
            return selected[0]

        def confirm():
            path = selected_path()
            if not path:
                return
            self.db.confirm_match(row["id"], path)
            self.refresh_table()
            window.destroy()

        def reject():
            path = selected_path()
            if not path:
                return
            self.db.reject_match(row["anilist_id"], path)
            tree.delete(path)

        def not_on_server():
            selected = tree.selection()
            rejected_path = None
            if selected and selected[0] != "__empty__":
                rejected_path = selected[0]
            elif row["detected_server_path"]:
                rejected_path = row["detected_server_path"]
            self.db.mark_not_on_server(row["id"], rejected_path)
            self.refresh_table()
            window.destroy()

        actions = Frame(window)
        actions.pack(fill=X, padx=10, pady=10)
        confirm_button = Button(actions, text="Confirm Match", command=confirm)
        reject_button = Button(actions, text="Reject Match", command=reject)
        if not review_state["has_candidates"]:
            confirm_button.config(state="disabled")
            reject_button.config(state="disabled")
        confirm_button.pack(side=LEFT, padx=4)
        reject_button.pack(side=LEFT, padx=4)
        Button(actions, text="Not On Server", command=not_on_server).pack(side=LEFT, padx=4)
        Button(actions, text="Select Jellyfin Folder", command=lambda: (window.destroy(), self.select_jellyfin_folder(row))).pack(side=LEFT, padx=4)

    def remove_selected(self) -> None:
        row = self.selected_row()
        if not row:
            return
        if messagebox.askyesno(APP_NAME, f"Remove '{row['english_title']}' from the tracker?\n\nThis only deletes the local tracker record."):
            self.db.delete_anime(row["id"])
            self.refresh_table()

    def open_anilist(self) -> None:
        row = self.selected_row()
        if row:
            webbrowser.open(row["anilist_url"])

    def export_csv(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if path:
            self.db.export_csv(Path(path), self.rows)
            messagebox.showinfo(APP_NAME, f"Exported to {path}")

    def check_anilist_status(self) -> None:
        """Run a manual AniList API health check without freezing the UI."""
        if getattr(self, "_anilist_check_active", False):
            return
        self._anilist_check_active = True
        self._anilist_check_button.config(state="disabled")
        self._anilist_status_label.config(text="● Checking...", fg=palette(self.theme_choice)["muted"])
        threading.Thread(target=self._anilist_status_worker, daemon=True).start()

    def _anilist_status_worker(self) -> None:
        try:
            online, detail = self.client.health_check(timeout=8.0)
        except Exception as exc:
            online, detail = False, f"Unexpected error: {exc}"
        self.root.after(0, self._finish_anilist_status_check, online, detail)

    def _finish_anilist_status_check(self, online: bool, detail: str) -> None:
        if online:
            text, color = "● Online", "#2fbf71"
        else:
            text, color = "● Offline", "#e5534b"
        self._anilist_status_label.config(text=text, fg=color)
        self._anilist_check_button.config(state="normal")
        self._anilist_check_active = False
        state = "Online" if online else "Offline"
        self.show_message(APP_NAME, f"AniList API is {state}: {detail}")

    def edit_settings(self) -> None:
        config = load_notification_config()
        settings = self.db.get_settings()
        window = Toplevel(self.root)
        style_window(window, self.theme_choice)
        window.title("Settings")
        window.geometry("820x690")
        notebook = ttk.Notebook(window)
        notebook.pack(fill=BOTH, expand=True, padx=8, pady=8)
        general = ttk.Frame(notebook)
        announcements = ttk.Frame(notebook)
        notebook.add(general, text="General")
        notebook.add(announcements, text="Announcements")
        fields = {
            "tv_path": StringVar(value=settings.get("tv_path", "")),
            "movie_path": StringVar(value=settings.get("movie_path", "")),
            "webhook": StringVar(value=""),
            "theme": StringVar(value=settings.get("theme", "Dark")),
            "schedule_frequency": StringVar(value=settings.get("schedule_frequency", "Weekly")),
            "schedule_day": StringVar(value=settings.get("schedule_day", "Sunday")),
            "schedule_time": StringVar(value=settings.get("schedule_time", "10:00")),
            "shared_webhook": StringVar(value=""),
            "queue_type": StringVar(value="TV Show"),
            "queue_title": StringVar(value=""),
            "queue_year": StringVar(value=""),
            "queue_season": StringVar(value=""),
            "queue_episodes": StringVar(value=""),
        }
        toggles = {
            "discord_enabled": BooleanVar(value=config.discord_enabled),
            "windows_enabled": BooleanVar(value=config.windows_enabled),
            "notify_airing_starts": BooleanVar(value=config.notify_airing_starts),
            "notify_airing_finishes": BooleanVar(value=config.notify_airing_finishes),
            "notify_found_on_server": BooleanVar(value=config.notify_found_on_server),
            "notify_errors": BooleanVar(value=config.notify_errors),
            "notify_release_date_changes": BooleanVar(value=config.notify_release_date_changes),
            "schedule_enabled": BooleanVar(value=settings.get("schedule_enabled", "false") == "true"),
            "schedule_start_when_available": BooleanVar(value=settings.get("schedule_start_when_available", "true") == "true"),
            "schedule_discord_summary_changes_only": BooleanVar(value=settings.get("schedule_discord_summary_changes_only", "true") == "true"),
            "shared_announcements_enabled": BooleanVar(value=config.shared_announcements_enabled),
            "shared_send_silently": BooleanVar(value=config.shared_send_silently),
            "shared_announce_additions": BooleanVar(value=config.shared_announce_additions),
            "shared_announce_removals": BooleanVar(value=config.shared_announce_removals),
        }
        Label(general, text="TV shows Jellyfin path").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        Entry(general, textvariable=fields["tv_path"], width=74).grid(row=0, column=1, padx=8, pady=4)
        Label(general, text="Movies Jellyfin path").grid(row=1, column=0, sticky="w", padx=8, pady=4)
        Entry(general, textvariable=fields["movie_path"], width=74).grid(row=1, column=1, padx=8, pady=4)
        Label(general, text="Theme").grid(row=2, column=0, sticky="w", padx=8, pady=4)
        ttk.Combobox(general, textvariable=fields["theme"], values=["Dark", "Light", "Follow Windows"], state="readonly", width=30).grid(row=2, column=1, sticky="w", padx=8, pady=4)
        Checkbutton(general, text="Enable scheduled checks", variable=toggles["schedule_enabled"]).grid(row=3, column=1, sticky="w", padx=8, pady=2)
        Label(general, text="Frequency").grid(row=4, column=0, sticky="w", padx=8, pady=4)
        ttk.Combobox(general, textvariable=fields["schedule_frequency"], values=["Daily", "Weekly"], state="readonly", width=30).grid(row=4, column=1, sticky="w", padx=8, pady=4)
        Label(general, text="Day of week").grid(row=5, column=0, sticky="w", padx=8, pady=4)
        ttk.Combobox(general, textvariable=fields["schedule_day"], values=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], state="readonly", width=30).grid(row=5, column=1, sticky="w", padx=8, pady=4)
        Label(general, text="Time (24-hour HH:MM)").grid(row=6, column=0, sticky="w", padx=8, pady=4)
        Entry(general, textvariable=fields["schedule_time"], width=18).grid(row=6, column=1, sticky="w", padx=8, pady=4)
        Checkbutton(general, text="Run missed check as soon as possible after startup", variable=toggles["schedule_start_when_available"]).grid(row=7, column=1, sticky="w", padx=8, pady=2)
        Checkbutton(general, text="Send Discord summary only when something changes", variable=toggles["schedule_discord_summary_changes_only"]).grid(row=8, column=1, sticky="w", padx=8, pady=2)
        Label(general, text=f"Discord webhook URL: {masked_webhook(config.discord_webhook_url)}").grid(row=9, column=0, sticky="w", padx=8, pady=4)
        Entry(general, textvariable=fields["webhook"], width=74, show="*").grid(row=9, column=1, padx=8, pady=4)
        Label(general, text="Leave blank to keep the saved webhook.").grid(row=10, column=1, sticky="w", padx=8, pady=(0, 8))
        labels = [
            ("Discord enabled", "discord_enabled"),
            ("Windows notifications enabled", "windows_enabled"),
            ("Notify when airing starts", "notify_airing_starts"),
            ("Notify when airing finishes", "notify_airing_finishes"),
            ("Notify when found on server", "notify_found_on_server"),
            ("Notify on errors", "notify_errors"),
            ("Notify on release-date changes", "notify_release_date_changes"),
        ]
        for index, (label, key) in enumerate(labels, start=11):
            Checkbutton(general, text=label, variable=toggles[key]).grid(row=index, column=1, sticky="w", padx=8, pady=2)

        maintenance_row = len(labels) + 11
        maintenance = ttk.LabelFrame(general, text="Maintenance")
        maintenance.grid(row=maintenance_row, column=0, columnspan=2, sticky="ew", padx=8, pady=(10, 4))
        for index, (label, action) in enumerate(MAINTENANCE_ACTIONS):
            Button(maintenance, text=label, command=self._command_for_action(action)).grid(row=index // 2, column=index % 2, sticky="ew", padx=6, pady=4)
        maintenance.grid_columnconfigure(0, weight=1)
        maintenance.grid_columnconfigure(1, weight=1)

        api_status_row = maintenance_row + 1
        api_status = ttk.LabelFrame(general, text="AniList API Status")
        api_status.grid(row=api_status_row, column=0, columnspan=2, sticky="ew", padx=8, pady=(10, 4))
        theme_colors = palette(self.theme_choice)
        self._anilist_status_label = Label(api_status, text="● Not checked", fg=theme_colors["muted"], bg=theme_colors["bg"])
        self._anilist_status_label.grid(row=0, column=0, sticky="w", padx=8, pady=6)
        self._anilist_check_button = Button(api_status, text="Check Status", command=self.check_anilist_status)
        self._anilist_check_button.grid(row=0, column=1, padx=8, pady=6)
        Label(api_status, text="Manual check only — never polls AniList automatically.", fg=theme_colors["muted"], bg=theme_colors["bg"]).grid(row=1, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))

        Checkbutton(announcements, text="Enable shared Discord announcements", variable=toggles["shared_announcements_enabled"]).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(14, 6))
        Label(announcements, text=f"Shared Discord webhook URL: {masked_webhook(config.shared_discord_webhook_url)}").grid(row=1, column=0, sticky="w", padx=12, pady=6)
        Entry(announcements, textvariable=fields["shared_webhook"], width=62, show="*").grid(row=1, column=1, sticky="ew", padx=12, pady=6)
        Label(announcements, text="Leave blank to keep the saved shared webhook.").grid(row=2, column=1, sticky="w", padx=12, pady=(0, 10))
        silent_help = "Suppresses Discord push/banner notifications. The message still appears normally in the channel and may create an unread badge."
        silent_saved_label = Label(announcements, text=silent_help, anchor="w", justify="left", wraplength=720)

        def persist_silent_setting() -> None:
            saved = save_shared_silent_setting(toggles["shared_send_silently"].get())
            config.shared_send_silently = saved.shared_send_silently
            state = "Silent delivery saved" if saved.shared_send_silently else "Normal Discord notifications saved"
            silent_saved_label.config(text=f"{silent_help} {state}.")

        Checkbutton(
            announcements,
            text="Send silently",
            variable=toggles["shared_send_silently"],
            command=persist_silent_setting,
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=12, pady=(4, 0))
        silent_saved_label.grid(row=4, column=0, columnspan=2, sticky="w", padx=30, pady=(0, 8))
        Checkbutton(announcements, text="Announce additions", variable=toggles["shared_announce_additions"]).grid(row=5, column=0, columnspan=2, sticky="w", padx=12, pady=4)
        Checkbutton(announcements, text="Announce removals", variable=toggles["shared_announce_removals"]).grid(row=6, column=0, columnspan=2, sticky="w", padx=12, pady=4)
        announcements.grid_columnconfigure(1, weight=1)

        queue_frame = ttk.LabelFrame(announcements, text="Manual Announcement Queue")
        queue_frame.grid(row=7, column=0, columnspan=2, sticky="nsew", padx=12, pady=(12, 8))
        announcements.grid_rowconfigure(7, weight=1)
        queue_frame.grid_columnconfigure(1, weight=1)
        editing_queue_id: dict[str, int | None] = {"value": None}

        Label(queue_frame, text="Type").grid(row=0, column=0, sticky="w", padx=8, pady=3)
        type_box = ttk.Combobox(queue_frame, textvariable=fields["queue_type"], values=["TV Show", "Movie"], state="readonly", width=16)
        type_box.grid(row=0, column=1, sticky="w", padx=8, pady=3)
        Label(queue_frame, text="Title").grid(row=1, column=0, sticky="w", padx=8, pady=3)
        title_box = ttk.Combobox(queue_frame, textvariable=fields["queue_title"])
        title_box.grid(row=1, column=1, sticky="ew", padx=8, pady=3)
        Label(queue_frame, text="Year").grid(row=2, column=0, sticky="w", padx=8, pady=3)
        year_controls = Frame(queue_frame)
        year_controls.grid(row=2, column=1, sticky="w", padx=8, pady=3)
        Entry(year_controls, textvariable=fields["queue_year"], width=12).pack(side=LEFT)
        Label(year_controls, text="Recommended for movies; optional for TV shows.").pack(side=LEFT, padx=8)
        season_label = Label(queue_frame, text="Season")
        season_entry = Entry(queue_frame, textvariable=fields["queue_season"], width=12)
        episodes_label = Label(queue_frame, text="Episodes")
        episodes_entry = Entry(queue_frame, textvariable=fields["queue_episodes"], width=28)
        season_label.grid(row=3, column=0, sticky="w", padx=8, pady=3)
        season_entry.grid(row=3, column=1, sticky="w", padx=8, pady=3)
        episodes_label.grid(row=4, column=0, sticky="w", padx=8, pady=3)
        episodes_entry.grid(row=4, column=1, sticky="w", padx=8, pady=3)
        preview = Label(queue_frame, text="Preview: Complete the required fields.", anchor="w", justify="left")
        preview.grid(row=5, column=0, columnspan=2, sticky="ew", padx=8, pady=(5, 3))
        queue_actions = Frame(queue_frame)
        queue_actions.grid(row=6, column=0, columnspan=2, sticky="ew", padx=4, pady=3)
        pending_label = Label(queue_frame, text="Pending announcements: 0", anchor="w")
        pending_label.grid(row=7, column=0, columnspan=2, sticky="ew", padx=8, pady=(3, 0))
        queue_tree = ttk.Treeview(queue_frame, columns=("type", "preview"), show="headings", height=5, selectmode="browse")
        queue_tree.heading("type", text="Type")
        queue_tree.heading("preview", text="Announcement")
        queue_tree.column("type", width=90, stretch=False)
        queue_tree.column("preview", width=560, stretch=True)
        queue_tree.grid(row=8, column=0, columnspan=2, sticky="nsew", padx=8, pady=(3, 8))
        queue_frame.grid_rowconfigure(8, weight=1)

        def queue_form_item() -> ManualAnnouncement:
            return build_manual_announcement(
                fields["queue_type"].get(),
                fields["queue_title"].get(),
                fields["queue_year"].get(),
                fields["queue_season"].get(),
                fields["queue_episodes"].get(),
                editing_queue_id["value"],
            )

        def update_queue_preview(*_args) -> None:
            is_tv = fields["queue_type"].get() == "TV Show"
            for widget in (season_label, season_entry, episodes_label, episodes_entry):
                if is_tv:
                    widget.grid()
                else:
                    widget.grid_remove()
            media_type = "TV_SHOW" if is_tv else "MOVIE"
            suggestions = self.db.manual_title_suggestions(media_type)
            title_box.configure(values=[title for title, _year in suggestions])
            try:
                preview.config(text=f"Preview: {queue_form_item().display_text}")
            except ManualAnnouncementValidationError:
                preview.config(text="Preview: Complete the required fields.")

        def apply_title_suggestion(_event=None) -> None:
            media_type = "TV_SHOW" if fields["queue_type"].get() == "TV Show" else "MOVIE"
            selected_title = fields["queue_title"].get().casefold()
            suggestion = next(
                ((title, year) for title, year in self.db.manual_title_suggestions(media_type) if title.casefold() == selected_title),
                None,
            )
            if suggestion and suggestion[1]:
                fields["queue_year"].set(str(suggestion[1]))

        def clear_queue_form() -> None:
            editing_queue_id["value"] = None
            fields["queue_type"].set("TV Show")
            for key in ("queue_title", "queue_year", "queue_season", "queue_episodes"):
                fields[key].set("")
            add_button.config(text="Add to Queue")
            update_queue_preview()

        def refresh_queue_list() -> None:
            for iid in queue_tree.get_children():
                queue_tree.delete(iid)
            items = self.db.manual_announcements()
            for item in items:
                queue_tree.insert("", END, iid=str(item.id), values=("TV Show" if item.media_type == "TV_SHOW" else "Movie", item.display_text))
            pending_label.config(text=f"Pending announcements: {len(items)}")

        def save_queue_item() -> None:
            try:
                item = queue_form_item()
                if editing_queue_id["value"] is None:
                    self.db.add_manual_announcement(item)
                else:
                    self.db.update_manual_announcement(editing_queue_id["value"], item)
            except (ManualAnnouncementValidationError, DuplicateManualAnnouncementError, KeyError) as exc:
                messagebox.showerror(APP_NAME, str(exc), parent=window)
                return
            clear_queue_form()
            refresh_queue_list()

        def edit_queue_item(_event=None) -> None:
            selected = queue_tree.selection()
            if not selected:
                messagebox.showinfo(APP_NAME, "Select a pending announcement to edit.", parent=window)
                return
            item_id = int(selected[0])
            item = next((entry for entry in self.db.manual_announcements() if entry.id == item_id), None)
            if not item:
                refresh_queue_list()
                return
            editing_queue_id["value"] = item_id
            fields["queue_type"].set("TV Show" if item.media_type == "TV_SHOW" else "Movie")
            fields["queue_title"].set(item.title)
            fields["queue_year"].set(str(item.year or ""))
            fields["queue_season"].set(str(item.season_number or ""))
            fields["queue_episodes"].set(",".join(str(number) for number in item.episodes))
            add_button.config(text="Save Changes")
            update_queue_preview()

        def remove_queue_item() -> None:
            selected = queue_tree.selection()
            if not selected:
                messagebox.showinfo(APP_NAME, "Select a pending announcement to remove.", parent=window)
                return
            if not messagebox.askyesno(APP_NAME, "Remove the selected pending announcement?", parent=window):
                return
            item_id = int(selected[0])
            self.db.delete_manual_announcements([item_id])
            if editing_queue_id["value"] == item_id:
                clear_queue_form()
            refresh_queue_list()

        add_button = Button(queue_actions, text="Add to Queue", command=save_queue_item)
        add_button.pack(side=LEFT, padx=4)
        Button(queue_actions, text="Edit Selected", command=edit_queue_item).pack(side=LEFT, padx=4)
        Button(queue_actions, text="Remove Selected", command=remove_queue_item).pack(side=LEFT, padx=4)
        queue_tree.bind("<Double-1>", edit_queue_item)
        type_box.bind("<<ComboboxSelected>>", update_queue_preview)
        title_box.bind("<<ComboboxSelected>>", apply_title_suggestion)
        for key in ("queue_title", "queue_year", "queue_season", "queue_episodes"):
            fields[key].trace_add("write", update_queue_preview)
        update_queue_preview()
        refresh_queue_list()

        def save():
            self.db.set_settings(
                {
                    "tv_path": fields["tv_path"].get(),
                    "movie_path": fields["movie_path"].get(),
                    "theme": fields["theme"].get(),
                    "schedule_enabled": "true" if toggles["schedule_enabled"].get() else "false",
                    "schedule_frequency": fields["schedule_frequency"].get(),
                    "schedule_day": fields["schedule_day"].get(),
                    "schedule_time": fields["schedule_time"].get(),
                    "schedule_start_when_available": "true" if toggles["schedule_start_when_available"].get() else "false",
                    "schedule_discord_summary_changes_only": "true" if toggles["schedule_discord_summary_changes_only"].get() else "false",
                }
            )
            webhook = fields["webhook"].get().strip() or config.discord_webhook_url
            shared_webhook = fields["shared_webhook"].get().strip() or config.shared_discord_webhook_url
            save_notification_config(
                NotificationConfig(
                    discord_webhook_url=webhook,
                    discord_enabled=toggles["discord_enabled"].get(),
                    windows_enabled=toggles["windows_enabled"].get(),
                    notify_airing_starts=toggles["notify_airing_starts"].get(),
                    notify_airing_finishes=toggles["notify_airing_finishes"].get(),
                    notify_found_on_server=toggles["notify_found_on_server"].get(),
                    notify_errors=toggles["notify_errors"].get(),
                    notify_release_date_changes=toggles["notify_release_date_changes"].get(),
                    shared_discord_webhook_url=shared_webhook,
                    shared_announcements_enabled=toggles["shared_announcements_enabled"].get(),
                    shared_send_silently=toggles["shared_send_silently"].get(),
                    shared_announce_additions=toggles["shared_announce_additions"].get(),
                    shared_announce_removals=toggles["shared_announce_removals"].get(),
                )
            )
            self.notifier.reload()
            self.theme_choice = fields["theme"].get()
            apply_theme(self.root, self.theme_choice)
            self.refresh_schedule_summary()
            window.destroy()

        Button(window, text="Save", command=save).pack(side=RIGHT, padx=12, pady=(0, 10))

    def install_or_update_scheduled_task(self) -> None:
        try:
            settings = self.db.get_settings()
            project_root = Path(__file__).resolve().parents[2]
            args = build_elevated_scheduled_task_args(project_root, settings)
            result = subprocess.run(
                args,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=300,
            )
            if is_uac_cancellation(result.returncode, result.stderr, result.stdout):
                messagebox.showinfo(APP_NAME, "Scheduled task installation was canceled.")
                return
            if result.returncode != 0:
                raise RuntimeError(registration_error_message(args, result.stderr, result.stdout))
            verify_args = build_verify_task_args()
            verify = subprocess.run(
                verify_args,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=60,
            )
            if verify.returncode != 0:
                details = verify.stderr.strip() or verify.stdout.strip() or "Task verification failed."
                raise RuntimeError(f"Scheduled task registration finished, but verification failed:\n{format_command_for_error(verify_args)}\n\n{details}")
            info = parse_task_verification(verify.stdout)
            record_schedule_install(self.db)
            messagebox.showinfo(
                APP_NAME,
                "Scheduled task installed or updated.\n\n"
                f"Task name: {info['task_name']}\n"
                f"Next run time: {info['next_run_time'] or 'Not scheduled'}\n"
                f"Enabled: {info['enabled']}",
            )
            self.refresh_schedule_summary()
        except Exception as exc:
            logging.exception("Installing scheduled task failed")
            messagebox.showerror(APP_NAME, str(exc))

    def run_scheduled_check_now(self) -> None:
        stats = run_scheduled_check(db=self.db, check_func=silent_check)
        self._send_scheduled_summary_if_needed(stats)
        self.root.after(0, self.refresh_table)
        self.show_message(APP_NAME, f"Scheduled check complete: {stats.result}")

    def _send_scheduled_summary_if_needed(self, stats: ScheduledCheckStats) -> None:
        settings = self.db.get_settings()
        changes_only = settings.get("schedule_discord_summary_changes_only", "true") == "true"
        if changes_only and stats.changes == 0:
            return
        self.notifier.send_scheduled_summary(stats)

    def send_test_notification(self) -> None:
        self.notifier.reload()
        if not self.notifier.config.discord_enabled or not self.notifier.config.has_webhook:
            messagebox.showinfo(APP_NAME, "Discord notifications are not enabled or no webhook is saved.")
            return
        self.run_threaded(self._send_test_notification_worker)

    def _send_test_notification_worker(self) -> None:
        sent = self.notifier.send_test()
        if sent:
            self.show_message(APP_NAME, "Test Discord notification sent.")
        else:
            self.show_error(APP_NAME, "Test notification failed. Check the log and webhook settings.")

    def _notify_status_change(self, row, old_status: str, new_status: str, cover_image_url: str) -> bool:
        config = self.notifier.config
        if old_status == TRACKER_ON_SERVER or not is_meaningful_transition(old_status, new_status):
            return False
        if old_status == TRACKER_UPCOMING and new_status == TRACKER_AIRING and not config.notify_airing_starts:
            return False
        if old_status == TRACKER_AIRING and new_status == TRACKER_READY and not config.notify_airing_finishes:
            return False
        key = notification_key(row["anilist_id"], old_status, new_status)
        if self.db.event_was_sent(key):
            return False
        self.notifier.send_anime_event("Anime Status Changed", row, old_status, new_status, row["server_status"] == "Found", "status", cover_image_url)
        self.db.mark_event_sent(key, "status", row["anilist_id"])
        return True

    def _notify_release_date_change(self, row, record: AnimeRecord) -> bool:
        config = self.notifier.config
        if not config.notify_release_date_changes:
            return False
        old_dates = (row["start_date"] or "", row["expected_end_date"] or "")
        new_dates = (record.start_date or "", record.expected_end_date or "")
        if old_dates == new_dates or not any(old_dates):
            return False
        key = f"release-date:{row['anilist_id']}:{old_dates[0]}:{old_dates[1]}->{new_dates[0]}:{new_dates[1]}"
        if self.db.event_was_sent(key):
            return False
        self.notifier.send_anime_event(
            "Release Date Changed",
            row,
            " / ".join(old_dates) or "Unknown",
            " / ".join(new_dates) or "Unknown",
            row["server_status"] == "Found",
            "release-date",
            record.cover_image_url,
            {"Previous Dates": " / ".join(old_dates), "New Dates": " / ".join(new_dates)},
        )
        self.db.mark_event_sent(key, "release-date", row["anilist_id"])
        return True

    def _notify_found_on_server(self, row, previous_status: str, path: str) -> None:
        if not self.notifier.config.notify_found_on_server:
            return
        key = f"server-found:{row['anilist_id']}:{path}"
        if self.db.event_was_sent(key):
            return
        self.notifier.send_anime_event(
            "Tracked Title Found on Jellyfin",
            row,
            previous_status,
            TRACKER_ON_SERVER,
            True,
            "server-found",
            row["cover_image_url"],
            {"Detected Path": path},
        )
        self.db.mark_event_sent(key, "server-found", row["anilist_id"])

    def _record_api_failure(self, row) -> None:
        count = self.db.record_api_failure(row["id"])
        if count < 3 or not self.notifier.config.notify_errors:
            return
        key = f"api-failure:{row['anilist_id']}:3"
        if self.db.event_was_sent(key):
            return
        self.notifier.send_anime_event(
            "Repeated AniList API Failure",
            row,
            row["tracker_status"],
            "Needs attention",
            row["server_status"] == "Found",
            "api-failure",
            row["cover_image_url"],
            {"Failure Count": str(count)},
        )
        self.db.mark_event_sent(key, "api-failure", row["anilist_id"])

    def run_threaded(self, func) -> bool:
        if not self._operation_lock.acquire(blocking=False):
            messagebox.showinfo(APP_NAME, "Another Anime Tracker operation is already running.")
            return False
        self.status_label.config(text="Working...")
        thread = threading.Thread(target=lambda: self._thread_wrapper(func), daemon=True)
        thread.start()
        return True

    def _thread_wrapper(self, func) -> None:
        try:
            func()
        except Exception as exc:
            logging.exception("Operation failed")
            self.show_error(APP_NAME, str(exc))
        finally:
            self._operation_lock.release()
            self.root.after(0, lambda: self.status_label.config(text="Ready"))

    def show_message(self, title: str, message: str) -> None:
        self.root.after(0, lambda: messagebox.showinfo(title, message))

    def show_error(self, title: str, message: str) -> None:
        self.root.after(0, lambda: messagebox.showerror(title, message))


def silent_check() -> ScheduledCheckStats:
    setup_logging()
    db = Database()
    client = AniListClient()
    notifier = Notifier(load_notification_config())
    changed = 0
    stats = ScheduledCheckStats()
    db.backup("scheduled-check")
    for row in db.rows():
        try:
            media = client.get_by_id(row["anilist_id"])
            movie_availability = row["movie_availability"] or "unknown"
            new_status = tracker_status_from_anilist(media.get("status") or "", media.get("format") or "", movie_availability)
            display_status = TRACKER_ON_SERVER if row["tracker_status"] == TRACKER_ON_SERVER else new_status
            record = AnimeRecord.from_anilist(media, new_status)
            record.movie_availability = movie_availability
            old_status = row["tracker_status"]
            state = row["notification_state"] or ""
            config = notifier.config
            can_notify_start = old_status == TRACKER_UPCOMING and new_status == TRACKER_AIRING and config.notify_airing_starts
            can_notify_finish = old_status == TRACKER_AIRING and new_status == TRACKER_READY and config.notify_airing_finishes
            if old_status != TRACKER_ON_SERVER and is_meaningful_transition(old_status, new_status) and (can_notify_start or can_notify_finish):
                key = notification_key(row["anilist_id"], old_status, new_status)
                if not db.event_was_sent(key):
                    notifier.send_anime_event("Anime Status Changed", row, old_status, new_status, row["server_status"] == "Found", "status", record.cover_image_url)
                    db.mark_event_sent(key, "status", row["anilist_id"])
                    state = key
                    changed += 1
            if old_status != TRACKER_READY and display_status == TRACKER_READY:
                stats.moved_ready += 1
            old_dates = (row["start_date"] or "", row["expected_end_date"] or "")
            new_dates = (record.start_date or "", record.expected_end_date or "")
            if config.notify_release_date_changes and old_dates != new_dates and any(old_dates):
                key = f"release-date:{row['anilist_id']}:{old_dates[0]}:{old_dates[1]}->{new_dates[0]}:{new_dates[1]}"
                if not db.event_was_sent(key):
                    notifier.send_anime_event(
                        "Release Date Changed",
                        row,
                        " / ".join(old_dates) or "Unknown",
                        " / ".join(new_dates) or "Unknown",
                        row["server_status"] == "Found",
                        "release-date",
                        record.cover_image_url,
                        {"Previous Dates": " / ".join(old_dates), "New Dates": " / ".join(new_dates)},
                    )
                    db.mark_event_sent(key, "release-date", row["anilist_id"])
                    changed += 1
            record.tracker_status = display_status
            db.update_from_anilist(row["id"], record, old_status, state)
            stats.titles_updated += 1
            db.reset_api_failure(row["id"])
        except Exception:
            logging.exception("Scheduled refresh failed for %s", row["anilist_id"])
            count = db.record_api_failure(row["id"])
            key = f"api-failure:{row['anilist_id']}:3"
            if count >= 3 and notifier.config.notify_errors and not db.event_was_sent(key):
                notifier.send_anime_event(
                    "Repeated AniList API Failure",
                    row,
                    row["tracker_status"],
                    "Needs attention",
                    row["server_status"] == "Found",
                    "api-failure",
                    row["cover_image_url"],
                    {"Failure Count": str(count)},
                )
                db.mark_event_sent(key, "api-failure", row["anilist_id"])
    settings = db.get_settings()
    candidates = scan_roots(settings.get("tv_path", ""), settings.get("movie_path", ""))
    rows = db.rows()
    season_numbers = infer_tracked_seasons(rows)
    multi_ids = multi_season_ids(rows)
    for row in rows:
        season_number = season_numbers.get(row["anilist_id"])
        rejected_paths = db.rejected_paths_for(row["anilist_id"])
        confirmed = db.confirmed_match_for(row["anilist_id"])
        if confirmed and normalize_windows_path(confirmed["path"]) in rejected_paths:
            db.remove_confirmed_match(row["anilist_id"], confirmed["path"])
            confirmed = None
        if confirmed:
            confirmed_path = Path(confirmed["path"])
            if confirmed_path.exists():
                if confirmed_match_has_evidence(confirmed, candidates, season_number):
                    if row["tracker_status"] != TRACKER_ON_SERVER or row["server_status"] != SERVER_ON_SERVER:
                        db.set_on_server(
                            row["id"], confirmed["path"], SERVER_ON_SERVER, row["manual_notes"],
                            "Confirmed server match retained", confirmed["confirmation_type"],
                        )
                    continue
                db.clear_unsupported_automatic_match(row["id"], confirmed["path"])
                confirmed = None
            if confirmed is not None:
                db.set_needs_review_missing(row["id"], confirmed["path"])
                key = f"server-missing:{row['anilist_id']}:{confirmed['path']}"
                if not db.event_was_sent(key):
                    notifier.send_anime_event(
                        "Confirmed Jellyfin Folder Missing",
                        row,
                        TRACKER_ON_SERVER,
                        TRACKER_NEEDS_REVIEW,
                        False,
                        "server-missing",
                        row["cover_image_url"],
                        {"Previous Path": confirmed["path"]},
                    )
                    db.mark_event_sent(key, "server-missing", row["anilist_id"])
                continue
        result = match_record(row, candidates, rejected_paths, season_number, multi_ids)
        db.save_match_candidates(row["anilist_id"], result.candidates)
        if result.confidence == "confident":
            previous_status = row["tracker_status"]
            db.set_on_server(
                row["id"], result.path, SERVER_ON_SERVER, row["manual_notes"],
                f"{previous_status} -> On Server", "automatic",
            )
            if previous_status != TRACKER_ON_SERVER:
                stats.moved_on_server += 1
            key = f"server-found:{row['anilist_id']}:{result.path}"
            if notifier.config.notify_found_on_server and not db.event_was_sent(key):
                notifier.send_anime_event(
                    "Tracked Title Found on Jellyfin",
                    row,
                    previous_status,
                    TRACKER_ON_SERVER,
                    True,
                    "server-found",
                    row["cover_image_url"],
                    {"Detected Path": result.path},
                )
                db.mark_event_sent(key, "server-found", row["anilist_id"])
        elif result.confidence == "uncertain":
            reason = REVIEW_MULTIPLE_MATCHES if len(result.candidates) > 1 else REVIEW_POSSIBLE_MATCHES
            db.set_review_state(row["id"], SERVER_NEEDS_REVIEW, TRACKER_NEEDS_REVIEW, reason, row["detected_server_path"], result.notes)
        else:
            db.mark_no_match_found(row["id"])
    logging.info("Silent check complete; %s notification-worthy changes", changed)
    stats.changes = changed + stats.moved_on_server + stats.moved_ready
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--check-silent", action="store_true", help="Refresh and scan without opening the GUI.")
    parser.add_argument("--scheduled-check", action="store_true", help="Run scheduled refresh/scan with duplicate-run protection and saved result stats.")
    parser.add_argument("--sample-data", action="store_true", help="Add sample records and exit.")
    parser.add_argument("--record-schedule-install", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    setup_logging()
    if args.sample_data:
        Database().add_sample_data()
        print("Sample data added.")
        return 0
    if args.record_schedule_install:
        record_schedule_install()
        return 0
    if args.check_silent:
        silent_check()
        return 0
    if args.scheduled_check:
        stats = run_scheduled_check(check_func=silent_check)
        settings = Database().get_settings()
        changes_only = settings.get("schedule_discord_summary_changes_only", "true") == "true"
        if not changes_only or stats.changes > 0:
            sent = Notifier(load_notification_config()).send_scheduled_summary(stats)
            if sent:
                logging.info("Scheduled Discord summary sent successfully")
            else:
                logging.error("Scheduled Discord summary was requested but could not be sent")
                Database().set_settings({"scheduled_last_result": f"{stats.result}; Discord summary failed"})
        else:
            logging.info("Scheduled Discord summary skipped because no changes were detected")
        return 0 if not stats.error else 1
    AnimeTrackerApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
