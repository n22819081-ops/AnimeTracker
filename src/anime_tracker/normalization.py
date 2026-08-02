from __future__ import annotations

import re
import unicodedata

NOISE_WORDS = {
    "tv",
    "movie",
    "season",
    "part",
    "cour",
    "the",
    "ova",
    "ona",
    "special",
}


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", title or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", text)
    text = re.sub(r"\b(s\d{1,2}|season\s+\d+|part\s+\d+)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = [token for token in text.split() if token not in NOISE_WORDS]
    return " ".join(tokens)


def normalize_title_keep_season(title: str) -> str:
    text = unicodedata.normalize("NFKD", title or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\([^)]*\)|\[[^]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def title_tokens(title: str) -> set[str]:
    return set(normalize_title(title).split())


def title_variants(*titles: str, alternates: list[str] | None = None) -> set[str]:
    values = set()
    for title in titles:
        for normalized in (normalize_title(title), normalize_title_keep_season(title)):
            if normalized:
                values.add(normalized)
    for title in alternates or []:
        for normalized in (normalize_title(title), normalize_title_keep_season(title)):
            if normalized:
                values.add(normalized)
    return values
