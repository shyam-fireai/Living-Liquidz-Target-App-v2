"""Shared page widgets."""

import logging

import streamlit as st

logger = logging.getLogger(__name__)


def render_header(title="Dashboard", hide_upload=False):
    """Renders a single-row sticky toolbar at absolute zero-gap top."""
    logger.debug("Rendering header toolbar for: %s", title)

    if hide_upload:
        # Pushes single action col to far right next to profile
        col_brand, col_spacer, col_edit, col_profile = st.columns([3, 5, 1.4, 0.6], vertical_alignment="center")
        col_upload = None
    else:
        # Grid layout for the toolbar, slightly larger action cols to avoid text wrapping
        col_brand, col_spacer, col_edit, col_upload, col_profile = st.columns(
            [3, 3.6, 1.4, 1.4, 0.6], vertical_alignment="center"
        )

    with col_brand:
        st.markdown(
            f"""
            <div style="display: flex; align-items: center; gap: 12px;">
                <button
                    onclick="window.parent.document.querySelector('button[aria-label=\\'Open sidebar\\'], button[data-testid=\\'stSidebarCollapseButton\\']').click();"
                    style="
                        background: none;
                        border: none;
                        cursor: pointer;
                        font-size: 1.2rem;
                        padding: 0;
                        margin: 0;
                        display: flex;
                        align-items: center;
                        color: #1e293b;
                    "
                    class="mobile-menu-btn"
                >
                    ☰
                </button>
                <h2 style="margin: 0; font-size: 1.2rem; font-weight: 600; color: #1e293b; white-space: nowrap; border: none !important;">{title}</h2>
            </div>
            <style>
                /* Hide the custom menu button on Desktop, only show on Mobile/Tablet */
                .mobile-menu-btn {{
                    display: none !important;
                }}
                @media (max-width: 1024px) {{
                    .mobile-menu-btn {{
                        display: flex !important;
                    }}
                }}
            </style>
        """,
            unsafe_allow_html=True,
        )

    with col_profile:
        with st.popover("👤"):
            from auth import get_cookie_manager, logout

            user_name = st.session_state.get("username", "")
            user_email = st.session_state.get("user_email", "")

            # Show actual user details if we have profile data
            if "auth_profile" in st.session_state:
                p = st.session_state.auth_profile
                user_name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip() or user_name

            st.markdown(f"**{user_name}**")
            st.caption(user_email)
            st.divider()

            if st.button("Logout", use_container_width=True):
                logger.info("Logout button clicked in profile popover.")
                cm = get_cookie_manager()
                logout(cm)

    return col_edit, col_upload


def show_error(message: str, exc: BaseException | None = None) -> None:
    """Friendly error for users; technical details only in a collapsed expander (and in the logs)."""
    st.error(f"❌ {message}")
    if exc is not None:
        logger.error("%s: %r", message, exc)
        with st.expander("Technical details"):
            st.code(f"{type(exc).__name__}: {exc}")


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
        st.markdown(f"\U0001f464 **{name}**")
        if email and email != name:
            st.caption(email)
        expires_at = st.session_state.get("session_expires_at")
        if expires_at:
            ends = datetime.fromtimestamp(int(expires_at), tz=DISPLAY_TZ)
            st.caption(f"⏱️ Session ends at {ends:%H:%M} {ends.tzname()}")
        if st.button("\U0001f6aa Logout", width="stretch", key="sidebar_logout"):
            logout(get_cookie_manager())
