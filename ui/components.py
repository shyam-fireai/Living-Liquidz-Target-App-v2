"""Shared page widgets."""

import html
import logging

import streamlit as st

from ui.branding import FIREAI_LOGO_WHITE, LIVING_LIQUIDZ_LOGO, logo_html

logger = logging.getLogger(__name__)


def render_header(title="Dashboard", buttons=2, crumb=""):
    """Toolbar row: title on the left, `buttons` equal button slots on the right (returned as a list).

    `crumb` is a small line above the title (e.g. "Sales targets").
    """
    logger.debug("Rendering header toolbar for: %s", title)

    # User details and Logout live in the sidebar user card (render_user_card), not in the header.
    # The keyed container gets the CSS class .st-key-ll_header, which ui/theme.py pins to the top.
    with st.container(key="ll_header"):
        spacer = max(1.0, 7.0 - 1.4 * buttons)
        col_brand, _, *slots = st.columns([3, spacer] + [1.4] * buttons, vertical_alignment="center")
        crumb_html = f'<div class="ll-crumb">{html.escape(crumb)}</div>' if crumb else ""
        col_brand.markdown(
            f'{crumb_html}<div class="ll-title">{html.escape(title)}</div>',
            unsafe_allow_html=True,
        )
    return slots


def go_to(page: str) -> None:
    """on_click callback for navigation buttons ("dashboard", "edit", "upload", "history").

    As a callback it runs before the script, so a click costs one run instead of two
    (setting the page and calling st.rerun() would first re-run the old screen).
    """
    st.session_state.page = page


def show_error(message: str, exc: BaseException | None = None) -> None:
    """Friendly error for users; technical details only in a collapsed expander (and in the logs)."""
    st.error(message, icon=":material/error:")
    if exc is not None:
        logger.error("%s: %r", message, exc)
        with st.expander("Technical details"):
            st.code(f"{type(exc).__name__}: {exc}")


def sidebar_label(text: str) -> None:
    """Small upper-case section label in the sidebar (Tables, Filters)."""
    st.sidebar.markdown(f'<div class="ll-side-label">{html.escape(text)}</div>', unsafe_allow_html=True)


def render_sidebar_brand() -> None:
    """Living Liquidz logo at the top of the sidebar."""
    logo = logo_html(LIVING_LIQUIDZ_LOGO, "Living Liquidz", 84, "border-radius:12px;display:block")
    st.sidebar.markdown(f'<div class="ll-brand">{logo}</div>', unsafe_allow_html=True)


def render_user_card() -> None:
    """Sidebar card: who is logged in, when the session ends, and a logout button."""
    from datetime import datetime

    from auth import get_cookie_manager, logout
    from config import DISPLAY_TZ

    profile = st.session_state.get("auth_profile") or {}
    email = st.session_state.get("user_email", "")
    name = f"{profile.get('first_name') or ''} {profile.get('last_name') or ''}".strip() or email

    st.sidebar.divider()
    with st.sidebar.container(border=True):
        st.markdown(f"**{name}**")
        if email and email != name:
            # Raw HTML: st.caption would turn the address into a link, which is dark blue on the navy sidebar.
            st.markdown(f'<div class="ll-user-email">{html.escape(email)}</div>', unsafe_allow_html=True)
        expires_at = st.session_state.get("session_expires_at")
        if expires_at:
            ends = datetime.fromtimestamp(int(expires_at), tz=DISPLAY_TZ)
            st.caption(f"Session ends at {ends:%H:%M} {ends.tzname()}")
        if st.button("Log out", icon=":material/logout:", width="stretch", key="sidebar_logout"):
            logout(get_cookie_manager())

    fireai = logo_html(FIREAI_LOGO_WHITE, "FireAI", 26)
    st.sidebar.markdown(f'<div class="ll-powered">Powered by {fireai}</div>', unsafe_allow_html=True)
