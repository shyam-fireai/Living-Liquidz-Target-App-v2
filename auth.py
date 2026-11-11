import base64
import datetime
import hashlib
import json
import logging
import os
import time
import urllib.parse

import extra_streamlit_components as stx
import requests
import streamlit as st

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fallback Cookie Secret since user stated they don't have one right now
COOKIE_SECRET = "fallback_temporary_dev_secret_key"


# AuthService class (backend)
class AuthService:
    def __init__(self):
        # Load from secrets.json as requested, fallback to environment variables
        logger.info("Initializing AuthService...")
        try:
            with open("secrets.json") as f:
                creds = json.load(f)
            self.base_url = creds.get("FIREAI_BASE_URL", os.getenv("FIREAI_BASE_URL"))
            self.api_key = creds.get("FIREAI_API_KEY", os.getenv("FIREAI_API_KEY"))
            raw_allowed = os.getenv("ALLOWED_EMAILS") or creds.get("ALLOWED_EMAILS", [])
            if isinstance(raw_allowed, list):
                self.allowed_emails = [e.strip().lower() for e in raw_allowed if e.strip()]
            elif isinstance(raw_allowed, str):
                self.allowed_emails = [e.strip().lower() for e in raw_allowed.split(",") if e.strip()]
            else:
                self.allowed_emails = []
            logger.info(f"AuthService initialized with Base URL: {self.base_url}")
        except Exception as e:
            logger.error(f"Failed to load secrets for AuthService: {e}")
            self.base_url = os.getenv("FIREAI_BASE_URL")
            self.api_key = os.getenv("FIREAI_API_KEY")
            raw_allowed = os.getenv("ALLOWED_EMAILS", "")
            if isinstance(raw_allowed, list):
                self.allowed_emails = [e.strip().lower() for e in raw_allowed if e.strip()]
            elif isinstance(raw_allowed, str):
                self.allowed_emails = [e.strip().lower() for e in raw_allowed.split(",") if e.strip()]
            else:
                self.allowed_emails = []

    def login(self, email, password):
        # Restrict to allowed emails (loaded from ENV/secrets)
        logger.info(f"Login attempt for email: {email}")
        if email.lower().strip() not in self.allowed_emails:
            logger.warning(f"Login attempt rejected: {email} not in allowed list")
            return False, "Access denied: Email not authorized."

        if not self.base_url or not self.api_key:
            logger.error("Authentication service not configured (missing URL or API Key).")
            return False, "Authentication service not configured. Please check secrets.json"

        url = f"{self.base_url}/users/v1/authentication/login"
        payload = {"data": {"email": email, "password": password, "provider": "fireai", "platform": "app"}}
        headers = {"Content-Type": "application/json", "x-fireai-api-key": self.api_key}

        try:
            logger.info(f"Sending login request to: {url}")
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            data = response.json()

            if response.status_code == 200 and data.get("status") == 200 and "data" in data:
                logger.info(f"Login success for: {email}")
                return True, data["data"]
            else:
                error_msg = data.get("message", "Invalid email or password.")
                logger.warning(f"Login failed for {email}: {error_msg} (Status: {response.status_code})")
                return False, error_msg
        except requests.exceptions.RequestException as e:
            logger.error(f"API request error during login: {e}")
            return False, "Could not connect to authentication server."
        except Exception as e:
            logger.error(f"Unexpected error during login: {e}")
            return False, "An unexpected error occurred."


# Initialize auth service
auth_service = AuthService()


def log_to_audit(action_type, message=None, user_email=None):
    """Bridge to the audit logger in db.py"""
    try:
        from db import log_audit_action

        log_audit_action(action_type=action_type, error_message=message, user_email=user_email)
    except Exception as e:
        logger.error(f"Audit Log Failed: {e}")


# Helper functions
def _generate_session_token(username: str) -> str:
    timestamp = str(int(time.time()))
    data = f"{username}:{timestamp}:{COOKIE_SECRET}"
    return base64.b64encode(hashlib.sha256(data.encode()).digest()).decode()[:32]


def get_cookie_manager():
    if "cookie_manager_instance" not in st.session_state:
        logger.info("Initializing CookieManager component...")
        st.session_state.cookie_manager_instance = stx.CookieManager(key="cookie_manager")
    return st.session_state.cookie_manager_instance


def show_login_page():
    cookie_manager = get_cookie_manager()

    st.markdown(
        """
        <style>
        /* 1. Global Centering Reset */
        [data-testid="stAppViewContainer"] {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            height: 100vh !important;
            overflow: hidden !important;
        }

        .main {
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            height: 100vh !important;
            width: 100% !important;
            overflow: hidden !important;
        }

        .block-container {
            padding: 0 !important;
            margin: 0 !important;
            max-width: 450px !important;
            display: block !important;
        }

        /* 2. Remove Scrollbars and Chrome */
        * {
            -ms-overflow-style: none !important;
            scrollbar-width: none !important;
        }
        *::-webkit-scrollbar {
            display: none !important;
        }
        [data-testid="stHeader"], [data-testid="stSidebar"], [data-testid="stSidebarNav"], [data-testid="stBottom"] {
            display: none !important;
        }

        /* 3. Button Polish */
        .stButton>button {
            width: 100%;
            border-radius: 8px;
            height: 3rem;
            font-weight: 600;
        }
        </style>
    """,
        unsafe_allow_html=True,
    )

    # Clean, Centered Content
    st.title("Secure Login")
    st.markdown("Enter your credentials to access the Application.")
    st.divider()

    with st.form("login_form"):
        username_or_email = st.text_input("Company Email", placeholder="Enter your email")
        password = st.text_input("Password", type="password", placeholder="Enter your password")
        submitted = st.form_submit_button("Login", type="primary")

        if submitted:
            st.info("Authenticating...")
            success, response_data = auth_service.login(username_or_email, password)

            if success:
                st.session_state.authenticated = True
                st.session_state.username = username_or_email
                st.session_state.user_email = username_or_email
                log_to_audit("LOGIN", user_email=username_or_email)
                token = _generate_session_token(username_or_email)

                user_data = response_data.get("user", {})
                profile = {
                    "profile_image_url": user_data.get("profile_image_url"),
                    "first_name": user_data.get("first_name"),
                    "last_name": user_data.get("last_name"),
                    "id": user_data.get("id"),
                    "access_token": response_data.get("access_token"),
                    "refresh_token": response_data.get("refresh_token"),
                }
                # 4. Store in session state (Fast path access)
                st.session_state.session_token = token
                st.session_state.auth_profile = profile

                # 4b. CLEAR the Hard Logout Lock (Unlock the door)
                st.session_state.logout_triggered = False
                if "logout_audited" in st.session_state:
                    del st.session_state.logout_audited

                # 5. Set cookies (1-Hour Secure Persistence)
                # This ensures the session handles Ctrl+R but stays secure
                expiry = datetime.datetime.now() + datetime.timedelta(hours=1)

                cookie_manager.set("auth_token", token, key="set_at", expires_at=expiry)
                cookie_manager.set("auth_user", username_or_email, key="set_au", expires_at=expiry)
                cookie_manager.set("auth_profile", json.dumps(profile), key="set_ap", expires_at=expiry)

                # Set the Sentinel Switch
                cookie_manager.set("auth_session_active", "1", key="set_asa", expires_at=expiry)

                logger.info(f"User {username_or_email} logged in successfully with 1-hr expiry.")
                # Force a cache clear to ensure the first dashboard load is live and correct
                st.cache_data.clear()
                st.rerun()
            else:
                logger.warning(f"Login failed for {username_or_email}: {response_data}")
                st.error(f"🔒 {response_data}")

    st.stop()


def require_login():
    cookie_manager = get_cookie_manager()

    # 0. Synchronous Header Check (Frame 0 Fast-Check)
    ctx_cookies = st.context.cookies

    # 1. PRIORITY 1: Logout/Purge Guard (MUST OVERRIDE EVERYTHING)
    # Check for both Session state AND the "Hard Purge" cookie from the browser
    logout_in_progress = st.session_state.get("logout_triggered") or ctx_cookies.get("auth_logout_in_progress") == "1"

    if logout_in_progress:
        logger.info("Logout/Purge in progress: Blocking auto-login and cleaning tokens.")

        # Capture user before purging cookies/session
        logout_email = (
            st.session_state.get("user_email")
            or st.session_state.get("username")
            or (urllib.parse.unquote(ctx_cookies.get("auth_user")) if ctx_cookies.get("auth_user") else None)
        )

        # Purge ALL auth cookies from the browser immediately
        for cname in ["auth_token", "auth_user", "auth_profile", "auth_session_active", "auth_logout_in_progress"]:
            try:
                cookie_manager.delete(cname, key=f"purge_{cname}")
            except KeyError:
                pass

        # Reset server-side flags
        st.session_state.authenticated = False

        # Log the action (Once)
        if "logout_audited" not in st.session_state:
            log_to_audit("LOGOUT", user_email=logout_email)
            st.session_state.logout_audited = True

        # Show login page directly and return False to halt app.py
        # Crucially, we do NOT reset 'logout_triggered' here.
        # This keeps the door "Hard Locked" until a new login happens.
        show_login_page()
        return False

    # 2. PRIORITY 2: Check current session state (Fast path: already initialized)
    if st.session_state.get("authenticated", False):
        return True

    # 3. PRIORITY 3: Hybrid Cookie Check (Fast Header + Patient Component)
    # Check 1: Synchronous Headers (Fast)
    session_active = ctx_cookies.get("auth_session_active")

    # Check 2: Patient Sync (If headers are empty, we wait once for the JS component)
    all_cookies = {}
    if session_active != "1":
        # Check if the component has data
        all_cookies = cookie_manager.get_all()
        session_active = all_cookies.get("auth_session_active")

        # If still nothing, wait one cycle ONLY if we were previously logged in or expect to be
        if not session_active:
            if "cookie_wait_count" not in st.session_state:
                st.session_state.cookie_wait_count = 0

            if st.session_state.cookie_wait_count < 1:
                st.session_state.cookie_wait_count += 1
                time.sleep(0.1)
                st.rerun()

    # 4. Final Sentinel Check
    if session_active != "1":
        # Truly no session found. Show login page.
        show_login_page()
        return False

    # 5. Restore Session (Frame 0 Restoration)
    # Prefer context cookies for speed, fallback to all_cookies for robustness
    # Decoding is REQUIRED for context cookies as they are URL-encoded
    raw_token = ctx_cookies.get("auth_token") or all_cookies.get("auth_token")
    raw_user = ctx_cookies.get("auth_user") or all_cookies.get("auth_user")

    saved_token = urllib.parse.unquote(raw_token) if raw_token else None
    saved_user = urllib.parse.unquote(raw_user) if raw_user else None

    if saved_token and saved_user:
        logger.info(f"Restoring 1-hour session instantly for: {saved_user}")
        st.session_state.authenticated = True
        st.session_state.username = saved_user
        st.session_state.user_email = saved_user
        st.session_state.session_token = saved_token

        raw_profile = ctx_cookies.get("auth_profile") or all_cookies.get("auth_profile")
        if raw_profile:
            try:
                decoded_profile = urllib.parse.unquote(raw_profile)
                st.session_state.auth_profile = json.loads(decoded_profile)
            except Exception:
                pass
        return True

    # 6. Fallback (If sentinel exists but data is missing)
    show_login_page()
    return False

    # 5. Completely unauthenticated
    show_login_page()
    return False


def logout(cookie_manager=None):
    """Stages a logout request. The actual purge happens in the top-level require_login guard."""
    logger.info("Logout button clicked. Staging secure exit with Hard Sentinel...")

    # 1. Set a "Hard Purge" cookie that the browser will see on the NEXT incoming header
    if cookie_manager:
        # Short 30-second duration is enough to bridge the logout cycle
        expiry = datetime.datetime.now() + datetime.timedelta(seconds=30)
        cookie_manager.set("auth_logout_in_progress", "1", key="set_hard_sentinel", expires_at=expiry)

    # 2. Stage the server-side trigger
    st.session_state.logout_triggered = True
    st.rerun()


# Main logic
if __name__ == "__main__":
    require_login()
