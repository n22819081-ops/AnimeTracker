from __future__ import annotations

import tkinter as tk
from tkinter import ttk


DARK = {
    "bg": "#14161a",
    "panel": "#1e2229",
    "field": "#252a33",
    "text": "#f3f5f7",
    "muted": "#b9c0cc",
    "accent": "#4f8cff",
    "selected": "#315fba",
    "button": "#2c323d",
}

LIGHT = {
    "bg": "#f4f5f7",
    "panel": "#ffffff",
    "field": "#ffffff",
    "text": "#1c2027",
    "muted": "#4f5866",
    "accent": "#2456b8",
    "selected": "#b9d1ff",
    "button": "#e8ebf0",
}


def resolve_theme(choice: str) -> str:
    if choice in {"Dark", "Light"}:
        return choice
    if choice == "Follow Windows":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                return "Light" if int(value) == 1 else "Dark"
        except Exception:
            return "Dark"
    return "Dark"


def palette(choice: str) -> dict[str, str]:
    return DARK if resolve_theme(choice) == "Dark" else LIGHT


def apply_theme(root: tk.Misc, choice: str) -> None:
    colors = palette(choice)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    root.option_add("*Background", colors["bg"])
    root.option_add("*Foreground", colors["text"])
    root.option_add("*Entry.Background", colors["field"])
    root.option_add("*Entry.Foreground", colors["text"])
    root.option_add("*Listbox.Background", colors["field"])
    root.option_add("*Listbox.Foreground", colors["text"])
    root.configure(bg=colors["bg"])
    style.configure(".", background=colors["bg"], foreground=colors["text"], fieldbackground=colors["field"])
    style.configure("TFrame", background=colors["bg"])
    style.configure("TLabel", background=colors["bg"], foreground=colors["text"])
    style.configure("TButton", background=colors["button"], foreground=colors["text"], bordercolor=colors["panel"])
    style.map("TButton", background=[("active", colors["selected"])], foreground=[("active", colors["text"])])
    style.configure("TEntry", fieldbackground=colors["field"], foreground=colors["text"], insertcolor=colors["text"])
    style.configure("TCombobox", fieldbackground=colors["field"], foreground=colors["text"], background=colors["button"])
    style.map("TCombobox", fieldbackground=[("readonly", colors["field"])], foreground=[("readonly", colors["text"])])
    style.configure("Treeview", background=colors["panel"], fieldbackground=colors["panel"], foreground=colors["text"], rowheight=25)
    style.configure("Treeview.Heading", background=colors["button"], foreground=colors["text"])
    style.map("Treeview", background=[("selected", colors["selected"])], foreground=[("selected", colors["text"])])
    style.configure("Horizontal.TScrollbar", background=colors["button"], troughcolor=colors["panel"])
    style.configure("Vertical.TScrollbar", background=colors["button"], troughcolor=colors["panel"])


def style_window(window: tk.Misc, choice: str) -> None:
    apply_theme(window, choice)
