"""Colors and fonts: Docs Typer's warm dark palette, with Typofix's blue as the accent."""

from .motion import mix

C = {
    "bg": "#262624", "field": "#1F1E1D", "raised": "#30302E", "raised_hover": "#3A3A37",
    "border": "#3D3C38", "border_hover": "#55534E", "text": "#ECEAE3", "muted": "#A5A299",
    "faint": "#6E6B64", "danger": "#C9544E", "danger_hover": "#D86A64", "warn": "#E2A55C",
    "ok": "#8DBF7F", "track": "#3A3936", "disabled_fill": "#34332F", "disabled_text": "#6E6B64",
    "ink": "#141413",
}

FONT = "Segoe UI"
TITLE_FONT = "Georgia"


def configure_fonts(backend):
    global FONT, TITLE_FONT
    FONT, TITLE_FONT = backend.ui_font, backend.title_font


def on_accent(fn):
    pass  # Docs Typer lets you pick an accent; Typofix's is fixed, so nothing ever changes


ACCENT = "#6F8DFF"
C["accent"] = ACCENT
C["accent_hover"] = mix(ACCENT, "#FFFFFF", 0.16)
C["accent_dark"] = mix(ACCENT, "#000000", 0.25)
C["select"] = mix(C["field"], ACCENT, 0.35)
