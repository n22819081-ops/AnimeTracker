from __future__ import annotations

from pathlib import Path

APP_NAME = "Anime Tracker"
BASE_DIR = Path(__file__).resolve().parents[2]
LEGACY_DIR = BASE_DIR / "Legacy Anime Tracker"
DATA_DIR = LEGACY_DIR / "data"
DB_PATH = DATA_DIR / "anime_tracker.db"
LOG_DIR = LEGACY_DIR / "logs"
BACKUP_DIR = LEGACY_DIR / "backups"

DEFAULT_TV_PATH = r"I:\Jellyfin_Media\TV-SHOWs"
DEFAULT_MOVIE_PATH = r"I:\Jellyfin_Media\Movies"

TRACKER_UPCOMING = "Upcoming"
TRACKER_AIRING = "Currently Airing"
TRACKER_READY = "Finished / Ready to Add"
TRACKER_MOVIE_THEATRICAL = "Movie Theatrical Only"
TRACKER_MOVIE_DIGITAL = "Movie Digitally Available"
TRACKER_ON_SERVER = "On Server"
TRACKER_NEEDS_REVIEW = "Needs Review"

TRACKER_GROUPS = [
    TRACKER_UPCOMING,
    TRACKER_AIRING,
    TRACKER_READY,
    TRACKER_MOVIE_THEATRICAL,
    TRACKER_MOVIE_DIGITAL,
    TRACKER_ON_SERVER,
    TRACKER_NEEDS_REVIEW,
]

TRACKER_STATUS_PRIORITY = {
    TRACKER_ON_SERVER: 1,
    TRACKER_NEEDS_REVIEW: 2,
    TRACKER_MOVIE_DIGITAL: 3,
    TRACKER_MOVIE_THEATRICAL: 4,
    TRACKER_READY: 5,
    TRACKER_AIRING: 6,
    TRACKER_UPCOMING: 7,
}

SERVER_ON_SERVER = "On Server"
SERVER_ON_SERVER_MANUAL = "On Server - Manual"
SERVER_NEEDS_REVIEW = "Needs Review"
SERVER_MISSING_NEEDS_REVIEW = "Missing - Needs Review"
SERVER_NOT_FOUND = "Not Found"
SERVER_NOT_ON_SERVER = "Not On Server"

REVIEW_POSSIBLE_MATCHES = "Possible Jellyfin matches found"
REVIEW_NO_MATCH = "No Jellyfin match found"
REVIEW_AMBIGUOUS_IDENTITY = "Ambiguous title identity"
REVIEW_INVALID_PATH = "Missing or invalid server path"
REVIEW_CONFIRMED_PATH_MISSING = "Previously confirmed path missing"
REVIEW_MULTIPLE_MATCHES = "Multiple possible matches"

ANILIST_STATUSES = {
    "FINISHED": "Finished",
    "RELEASING": "Releasing",
    "NOT_YET_RELEASED": "Not Yet Released",
    "CANCELLED": "Cancelled",
    "HIATUS": "Hiatus",
}
