"""Emerald-on-black palette and the global stylesheet."""

# --- palette ---------------------------------------------------------------
BG = "#050807"          # main background
BG2 = "#0B100E"         # secondary background (sidebar, inputs)
CARD = "#101714"        # card background
CHARCOAL = "#131A17"    # assistant message cards
GREEN = "#00F5A0"       # primary emerald
GLOW = "#00FF88"        # bright glow
MINT = "#B9FFD9"        # mint text / accents
TEXT = "#F4FFF8"        # main text
MUTED = "#83968B"       # secondary text
BORDER = "#20382D"      # thin borders
HOVER = "#153B2B"       # hover surfaces
WARN = "#E0B34A"
DANGER = "#FF5C6C"
FONT = "Segoe UI"

# Names used by older modules; they now resolve to the emerald palette.
PANEL = BG2
PANEL_ALT = CARD
BLUE = GREEN
PURPLE = GLOW


def rgba(hex_color: str, alpha: float) -> str:
    """'#00F5A0', 0.4 -> 'rgba(0,245,160,102)' for use inside stylesheets."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{int(alpha * 255)})"


STYLESHEET = f"""
* {{ font-family: "{FONT}"; color: {TEXT}; outline: none; }}
QMainWindow, #root {{ background: {BG}; }}
QToolTip {{
    background: {CARD}; color: {MINT}; border: 1px solid {BORDER};
    padding: 6px 8px; border-radius: 6px;
}}

/* ---- sidebar ---- */
#sidebar {{ background: {BG2}; border-right: 1px solid {BORDER}; }}
#brand {{ font-size: 22px; font-weight: 600; letter-spacing: 9px; color: {MINT}; }}
#brandSub {{ font-size: 10px; color: {MUTED}; letter-spacing: 2px; }}

QPushButton#navButton {{
    text-align: left;
    padding: 11px 16px;
    margin: 2px 14px 2px 0px;
    border: none;
    border-left: 3px solid transparent;
    border-top-right-radius: 10px;
    border-bottom-right-radius: 10px;
    background: transparent;
    color: {MUTED};
    font-size: 14px;
}}
QPushButton#navButton:hover {{ background: {HOVER}; color: {TEXT}; }}
QPushButton#navButton:checked {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {rgba(GREEN, 0.18)}, stop:1 {rgba(GREEN, 0.03)});
    border-left: 3px solid {GREEN};
    color: {MINT};
}}

/* ---- typography ---- */
#pageTitle {{ font-size: 26px; font-weight: 600; color: {TEXT}; }}
#pageSub {{ font-size: 13px; color: {MUTED}; }}
#greeting {{ font-size: 30px; font-weight: 300; color: {TEXT}; }}
#statusLabel {{ font-size: 13px; color: {MUTED}; letter-spacing: 1px; }}
#homeStatus {{ font-size: 17px; font-weight: 400; color: {MINT}; }}
#cardTitle {{ font-size: 16px; font-weight: 600; color: {MINT}; }}
#bannerText {{ font-size: 15px; font-weight: 600; color: {TEXT}; }}

/* ---- cards ---- */
#card {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 16px;
}}
#card:hover {{ border: 1px solid {rgba(GREEN, 0.45)}; }}
#banner {{
    background: {rgba(GREEN, 0.07)}; border: 1px solid {rgba(GREEN, 0.28)}; border-radius: 12px;
}}

QPushButton#suggestion {{
    text-align: left; padding: 12px 16px; border-radius: 14px;
    background: {CARD}; border: 1px solid {BORDER}; color: {TEXT}; font-size: 13px;
}}
QPushButton#suggestion:hover {{
    background: {HOVER}; border: 1px solid {rgba(GREEN, 0.55)}; color: {MINT};
}}

/* ---- chat ---- */
#chatScroll, #chatScroll > QWidget > QWidget {{ background: transparent; border: none; }}
QLabel#bubbleUser {{
    background: {rgba(GREEN, 0.10)}; border: 1px solid {rgba(GREEN, 0.38)};
    border-radius: 16px; padding: 11px 16px; font-size: 14px; color: {TEXT};
}}
QLabel#bubbleAssistant {{
    background: {CHARCOAL}; border: 1px solid {BORDER};
    border-radius: 16px; padding: 11px 16px; font-size: 14px; color: {TEXT};
}}
QLabel#bubbleSystem {{
    color: {MUTED}; font-size: 12px; font-style: italic; padding: 4px;
}}

QLineEdit#chatInput {{
    background: {BG2}; border: 1px solid {BORDER};
    border-radius: 22px; padding: 12px 20px; font-size: 14px; color: {TEXT};
    selection-background-color: {rgba(GREEN, 0.45)};
}}
QLineEdit#chatInput:hover {{ border: 1px solid {rgba(GREEN, 0.40)}; }}
QLineEdit#chatInput:focus {{ border: 1px solid {GREEN}; background: {CARD}; }}

/* ---- buttons ---- */
QPushButton {{
    background: {CARD}; border: 1px solid {BORDER}; color: {TEXT};
    border-radius: 10px; padding: 8px 16px; font-size: 13px;
}}
QPushButton:hover {{ background: {HOVER}; border: 1px solid {rgba(GREEN, 0.6)}; color: {MINT}; }}
QPushButton:pressed {{ background: {rgba(GREEN, 0.22)}; }}
QPushButton:focus {{ border: 1px solid {GREEN}; }}
QPushButton:disabled {{ color: {MUTED}; background: {BG2}; border: 1px solid {BORDER}; }}

/* primary emerald buttons: Send, Launch, hands-free */
QPushButton#sendButton {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {GREEN}, stop:1 #00C97F);
    border: 1px solid {rgba(GLOW, 0.7)}; border-radius: 20px; padding: 10px 24px;
    font-weight: 600; color: #03120B;
}}
QPushButton#sendButton:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {GLOW}, stop:1 {GREEN});
    border: 1px solid {MINT}; color: #03120B;
}}
QPushButton#sendButton:pressed {{ background: #00C97F; }}
QPushButton#sendButton:disabled {{
    background: {CARD}; color: {MUTED}; border: 1px solid {BORDER};
}}

/* ---- inputs / lists ---- */
QSpinBox {{
    background: {BG2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px 10px;
    selection-background-color: {rgba(GREEN, 0.45)};
}}
QSpinBox:hover {{ border: 1px solid {rgba(GREEN, 0.45)}; }}
QSpinBox:focus {{ border: 1px solid {GREEN}; }}
QListWidget, QTextBrowser {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px;
    padding: 6px; font-size: 13px;
    selection-background-color: {rgba(GREEN, 0.25)};
}}
QListWidget::item {{ padding: 10px; border-radius: 8px; color: {TEXT}; }}
QListWidget::item:hover {{ background: {HOVER}; }}
QListWidget::item:selected {{ background: {rgba(GREEN, 0.18)}; color: {MINT}; }}
QMessageBox, QInputDialog, QDialog {{ background: {BG2}; }}
QMessageBox QLabel, QInputDialog QLabel {{ color: {TEXT}; }}
QComboBox {{
    background: {BG2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px 10px;
}}
QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {BORDER}; selection-background-color: {HOVER}; }}

/* ---- scrollbars ---- */
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {rgba(GREEN, 0.5)}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ height: 0; }}
"""
