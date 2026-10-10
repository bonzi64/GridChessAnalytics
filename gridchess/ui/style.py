"""Application-wide QSS stylesheet, built from the palette in :mod:`gridchess.config`.

Design language: ultra-modern matte black with premium control detailing — subtle
vertical gradients on buttons, a 1px press "depress" shift and focus rings. Hairline
borders (#2A2A2A) react to hover; the muted-violet accent is used sparingly.
Typography: Inter with Segoe UI fallback. Re-skinning means editing colours in
config.py only. (Self-contained widgets — traffic lights, the segmented colour
selector — carry their own scoped stylesheets in widgets.py.)
"""

from __future__ import annotations

from .. import config


def build_stylesheet() -> str:
    c = config
    return f"""
    /* ---- Root surfaces ---- */
    QWidget#RootPanel {{
        background: transparent;
        color: {c.COLOR_TEXT};
        font-family: "Inter", "Segoe UI", sans-serif;
        font-size: 13px;
    }}
    QWidget#Card {{
        background-color: {c.COLOR_SURFACE};
        border: 1px solid {c.COLOR_BORDER};
        border-radius: {c.PANEL_RADIUS}px;
    }}

    /* ---- Typography ---- */
    QLabel {{ color: {c.COLOR_TEXT}; background: transparent; }}
    QLabel#Title {{
        font-size: 15px; font-weight: 700; letter-spacing: 0.2px;
    }}
    QLabel#Subtitle {{ color: {c.COLOR_TEXT_DIM}; font-size: 11px; }}
    QLabel#SectionLabel {{
        color: {c.COLOR_TEXT_DIM}; font-size: 10px; font-weight: 700;
        letter-spacing: 1.6px; padding-top: 2px;
    }}
    QLabel#FenValue {{
        background-color: {c.COLOR_SURFACE_2};
        border: 1px solid {c.COLOR_BORDER};
        border-radius: 8px;
        padding: 8px 10px;
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 11px;
        color: {c.COLOR_TEXT};
    }}
    QLabel#BestLine {{
        color: {c.COLOR_ACCENT};
        font-family: "Cascadia Mono", "Consolas", monospace;
        font-size: 12px;
        padding: 2px 0;
    }}

    /* ---- Buttons: matte gradient, hairline hover, 1px press shift, focus ring ---- */
    QPushButton {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #242427, stop:1 #1B1B1D);
        color: {c.COLOR_TEXT};
        border: 1px solid {c.COLOR_BORDER};
        border-radius: 10px;
        padding: 10px 16px;
        font-weight: 600;
        letter-spacing: 0.2px;
    }}
    QPushButton:hover {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #2B2B2F, stop:1 #222225);
        border-color: {c.COLOR_BORDER_HOVER};
    }}
    QPushButton:pressed {{
        background-color: #18181A;
        border-color: {c.COLOR_BORDER};
        padding-top: 11px; padding-bottom: 9px;
    }}
    QPushButton:focus {{ outline: none; border-color: rgba(138, 127, 214, 140); }}
    QPushButton:disabled {{
        color: {c.COLOR_TEXT_DIM};
        background-color: {c.COLOR_SURFACE};
        border-color: {c.COLOR_BORDER};
    }}
    QPushButton:checked {{
        border-color: {c.COLOR_ACCENT};
        color: {c.COLOR_ACCENT};
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #26242E, stop:1 #1C1B21);
    }}

    QPushButton#Primary {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #9A8FE6, stop:1 #7D71D2);
        border: 1px solid #6F64BE;
        color: #0F0F12;
    }}
    QPushButton#Primary:hover {{
        background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 #A89EEE, stop:1 #8A7EDB);
        border-color: {c.COLOR_ACCENT_HOVER};
    }}
    QPushButton#Primary:pressed {{ background-color: #7469C4; }}
    QPushButton#Primary:disabled {{
        background-color: {c.COLOR_SURFACE_2};
        border-color: {c.COLOR_BORDER};
        color: {c.COLOR_TEXT_DIM};
    }}

    """
