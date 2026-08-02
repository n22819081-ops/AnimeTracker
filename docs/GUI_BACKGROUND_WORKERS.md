# GUI Background Workers

`BackgroundWorker` is a `QRunnable` submitted to the main window's `QThreadPool`. Each worker has a unique identity, cancellation event, and signals for start, progress, partial result, final result, friendly error, cancellation, and finish.

Worker functions receive `cancel_event` and `progress`; they do not touch widgets. Qt queues signal handlers back to the GUI thread. Exceptions are converted to a short type and message rather than a full traceback in the normal interface.

Refresh and read-only test scans use this path in Milestone 7. Closing the window requests cancellation and waits briefly for the pool. Production AniList refresh, inventory, matching, notification processing, migration comparison, and diagnostics can use the same contract when their adapters are enabled later.
