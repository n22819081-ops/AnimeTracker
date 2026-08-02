# Modern GUI Architecture

Milestone 7 adds `src/anime_tracker/gui_qt` beside the legacy Tkinter application. `application.py` owns startup, `main_window.py` composes navigation and task state, `pages/core.py` contains focused page widgets, and `dialogs.py` contains Add, details, review, and import-preview workflows.

Widgets depend on `ModernRepository`, not SQLite. The repository stores only a database path and opens a short-lived connection for each operation. `ModernProfile` owns the disposable database, cache, and sanitized JSON settings. The profile refuses the live database path and strips webhook- or secret-named settings.

`AnimeTableModel` and its proxy provide sorting, token search, filtering, and single-row updates. `theme.py` centrally applies Dark, Light, or Follow Windows styling. `CoverImageCache` provides placeholders and bounded caching through Qt's nonblocking network manager.

The main window is a 12-page `QStackedWidget` selected by the sidebar. Long operations are dispatched to `QThreadPool`; widgets receive signals only on the Qt main thread. Production adapters are deliberately not injected in Milestone 7.
