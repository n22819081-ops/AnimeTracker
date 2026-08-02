from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication


@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    surface: str
    surface_alt: str
    text: str
    muted: str
    border: str
    accent: str
    selection: str
    danger: str
    success: str
    warning: str


DARK = Theme("Dark", "#111317", "#191c22", "#22262e", "#f3f5f7", "#a9b0bb", "#343a46", "#5aa9e6", "#174d70", "#ef6f6c", "#55c58a", "#e5b85c")
LIGHT = Theme("Light", "#f5f6f8", "#ffffff", "#edf0f4", "#17191d", "#626b78", "#cfd5de", "#1976b9", "#cce9fb", "#c53f3b", "#278a57", "#9a6b08")


def resolve_theme(name: str, app: QApplication) -> Theme:
    if name == "Light":
        return LIGHT
    if name == "Follow Windows":
        return DARK if app.palette().color(QPalette.Window).lightness() < 128 else LIGHT
    return DARK


def apply_theme(app: QApplication, name: str) -> Theme:
    theme = resolve_theme(name, app)
    app.setStyle("Fusion")
    app.setStyleSheet(stylesheet(theme))
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(theme.background))
    palette.setColor(QPalette.WindowText, QColor(theme.text))
    palette.setColor(QPalette.Base, QColor(theme.surface))
    palette.setColor(QPalette.AlternateBase, QColor(theme.surface_alt))
    palette.setColor(QPalette.Text, QColor(theme.text))
    palette.setColor(QPalette.Button, QColor(theme.surface_alt))
    palette.setColor(QPalette.ButtonText, QColor(theme.text))
    palette.setColor(QPalette.Highlight, QColor(theme.selection))
    palette.setColor(QPalette.HighlightedText, QColor(theme.text))
    app.setPalette(palette)
    return theme


def stylesheet(t: Theme) -> str:
    return f"""
    * {{ font-family: 'Segoe UI'; font-size: 10pt; }}
    QMainWindow, QWidget {{ background: {t.background}; color: {t.text}; }}
    QFrame#sidebar, QFrame#toolbar, QFrame#panel {{ background: {t.surface}; border: 1px solid {t.border}; }}
    QLabel#profileBanner {{ background: {t.warning}; color: #111317; padding: 6px 12px; font-weight: 700; }}
    QLabel#pageTitle {{ font-size: 20pt; font-weight: 700; }}
    QLabel#muted {{ color: {t.muted}; }}
    QPushButton, QToolButton, QComboBox, QLineEdit {{ background: {t.surface_alt}; color: {t.text}; border: 1px solid {t.border}; border-radius: 4px; padding: 7px 10px; }}
    QPushButton:hover, QToolButton:hover {{ border-color: {t.accent}; }}
    QPushButton:focus, QToolButton:focus, QLineEdit:focus, QComboBox:focus {{ border: 2px solid {t.accent}; }}
    QPushButton:disabled {{ color: {t.muted}; background: {t.surface}; }}
    QPushButton#primary {{ background: {t.accent}; color: #ffffff; border-color: {t.accent}; font-weight: 600; }}
    QListWidget {{ background: {t.surface}; border: 0; padding: 6px; }}
    QListWidget::item {{ padding: 10px; border-radius: 4px; }}
    QListWidget::item:selected {{ background: {t.selection}; color: {t.text}; }}
    QTableView, QTreeView {{ background: {t.surface}; alternate-background-color: {t.surface_alt}; color: {t.text}; gridline-color: {t.border}; border: 1px solid {t.border}; selection-background-color: {t.selection}; }}
    QHeaderView::section {{ background: {t.surface_alt}; color: {t.text}; padding: 7px; border: 0; border-right: 1px solid {t.border}; border-bottom: 1px solid {t.border}; font-weight: 600; }}
    QTabWidget::pane {{ border: 1px solid {t.border}; }}
    QTabBar::tab {{ background: {t.surface}; padding: 8px 14px; }}
    QTabBar::tab:selected {{ background: {t.surface_alt}; border-bottom: 2px solid {t.accent}; }}
    QProgressBar {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 3px; text-align: center; }}
    QProgressBar::chunk {{ background: {t.accent}; }}
    QToolTip {{ background: {t.surface_alt}; color: {t.text}; border: 1px solid {t.border}; }}
    """
