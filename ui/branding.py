"""Brand assets and palette shared by the theme, the sidebar and the login page.

The Streamlit-native part of the theme lives in .streamlit/config.toml; the colours below are the
same palette for the custom HTML/CSS. Logos are read from assets/ and inlined as data URIs so they
work in st.markdown without a static file server.
"""

import base64
import html
import logging
from functools import cache
from pathlib import Path

logger = logging.getLogger(__name__)

APP_NAME = "Living Liquidz Target App"

# FireAI palette (fireai.in)
PRIMARY = "#1068E8"
PRIMARY_LIGHT = "#2B7EFF"
PRIMARY_TINT = "#EEF4FE"
NAVY = "#030716"
NAVY_ACTIVE = "#101A3A"
TEXT = "#0A0A0A"
MUTED = "#5B6370"
MUTED_ON_DARK = "#A3A9B4"
BORDER = "#E5E5E5"
PAGE_BG = "#F5F5F5"
CARD_BG = "#FFFFFF"

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LIVING_LIQUIDZ_LOGO = "living-liquidz"
FIREAI_LOGO = "fireai"  # dark wordmark, for light backgrounds
FIREAI_LOGO_WHITE = "fireai-white"  # white wordmark, for the dark sidebar

_MIME = {".svg": "image/svg+xml", ".webp": "image/webp", ".png": "image/png", ".jpg": "image/jpeg"}


def logo_path(stem: str) -> Path | None:
    """First assets/<stem>.<ext> that exists (svg, webp, png, jpg), else None."""
    for ext in _MIME:
        path = ASSETS_DIR / f"{stem}{ext}"
        if path.is_file():
            return path
    return None


@cache
def _data_uri(stem: str) -> str | None:
    path = logo_path(stem)
    if path is None:
        logger.warning("Logo %r not found in %s; showing its name as text instead", stem, ASSETS_DIR)
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{_MIME[path.suffix]};base64,{encoded}"


def logo_html(stem: str, alt: str, height_px: int, css: str = "") -> str:
    """<img> tag for a logo in assets/; falls back to the name as text if the file is missing."""
    uri = _data_uri(stem)
    if uri is None:
        return f'<span style="font-weight:600">{html.escape(alt)}</span>'
    return f'<img src="{uri}" alt="{html.escape(alt)}" style="height:{height_px}px;width:auto;{css}">'
