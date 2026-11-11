import logging

import streamlit as st

logger = logging.getLogger(__name__)


def inject_minimalist_theme():
    """Injects high-quality CSS for an Absolute Top Toolbar style."""

    premium_css = """
    <style>
        /* Global Background & Font */
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

        html, body, [data-testid="stAppViewContainer"] {
            font-family: 'Inter', sans-serif;
            background-color: #FFFFFF !important;
        }

        /* 1. NUKE THE TOP WHITE SPACE BUT KEEP TOGGLE BUTTON */
        header[data-testid="stHeader"] {
            background-color: rgba(255, 255, 255, 0) !important;
            color: #1e293b !important;
        }

        [data-testid="stDecoration"] {
            display: none !important;
        }

        /* Ensure the sidebar toggle button is visible and matches our theme */
        [data-testid="stHeader"] button {
            color: #1e293b !important;
            background-color: transparent !important;
        }

        /* Target the Main Block Container to eliminate the huge default Streamlit gap */
        .block-container {
            padding-top: 1rem !important; /* Brings everything much higher */
            padding-bottom: 0rem !important;
            max-width: 98% !important;
            margin-top: -1.5rem !important; /* Pull up slightly more if needed */
        }

        /* 2. PIN THE NAVIGATION BAR */
        /* Target the row containing the header content */
        [data-testid="stVerticalBlock"] > div:has(h2) {
            position: sticky !important;
            top: 0 !important;
            left: 0 !important;
            right: 0 !important;
            z-index: 1000 !important;
            background-color: white !important;
            border: none !important; /* Remove ALL borders */
            padding: 1rem 40px !important;
            margin-bottom: 2rem !important;
            display: flex !important;
            align-items: center !important;
            box-shadow: none !important;
            border-radius: 0 !important; /* Un-box the top header */
        }

        /* Prevent rogue bottom borders on native elements */
        h2 {
            border: none !important;
            padding-bottom: 0 !important;
        }

        /* 3. FIX BUTTON SIZES AND ALLIGNMENT */
        /* Make Edit and Upload uniform */
        div.stButton > button {
            height: 42px !important;
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
            background: #2563EB !important;
            color: white !important;
            border-radius: 8px !important;
            font-size: 0.95rem !important;
            font-weight: 600 !important;
            padding: 0 20px !important;
            line-height: 1 !important;
            border: none !important;
            transition: background-color 0.2s ease !important;
        }

        div.stButton > button:hover {
            background-color: #1D4ED8 !important;
        }

        /* Force icon + text to align properly horizontally and never wrap */
        div.stButton > button p {
            white-space: nowrap !important;
            margin: 0 !important;
            display: flex !important;
            align-items: center !important;
            gap: 8px !important;
        }

        div.stButton > button div[data-testid="stMarkdownContainer"] {
            display: flex !important;
            flex-direction: row !important;
            align-items: center !important;
            justify-content: center !important;
        }

        /* 4. FIX PROFILE BUTTON TO BE EXACTLY CIRCULAR */
        [data-testid="stPopover"] button {
            width: 42px !important;
            height: 42px !important;
            min-width: 0 !important; /* Remove Streamlit's default min-width for buttons */
            border-radius: 50% !important; /* Perfect circle */
            padding: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            overflow: hidden !important;
            font-size: 1.2rem !important; /* Adjust emoji size */
            background: #F3F4F6 !important; /* Light background instead of loud blue */
            color: #1F2937 !important;
            border: 1px solid #E5E7EB !important;
        }

        [data-testid="stPopover"] button:hover {
            background: #E5E7EB !important;
        }

        [data-testid="stPopover"] button div[data-testid="stMarkdownContainer"] {
            width: 100% !important;
            height: 100% !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        /* 5. RESPONSIVENESS ENGINE (Media Queries) */

        /* Tablet & Mobile Tweaks */
        @media (max-width: 1024px) {
            .block-container {
                padding-left: 2rem !important;
                padding-right: 2rem !important;
            }
            [data-testid="stVerticalBlock"] > div:has(h2) {
                padding: 1rem 20px !important;
            }
        }

        /* Mobile Specific (< 768px) */
        @media (max-width: 768px) {
            /* 1. Nuke the huge sidebar spacing */
            [data-testid="stSidebar"] {
                width: 100% !important;
            }

            /* 2. Compact Sticky Header */
            [data-testid="stVerticalBlock"] > div:has(h2) {
                padding: 0.5rem 10px !important;
                margin-bottom: 1rem !important;
                flex-direction: column !important;
                align-items: flex-start !important;
                gap: 5px !important;
            }

            /* 3. Typography Scaling */
            h2 {
                font-size: 1rem !important;
            }

            /* 4. Column Stacking Fixes */
            /* Ensure buttons don't have massive gaps when Streamlit stacks them */
            [data-testid="column"] {
                width: 100% !important;
                flex: 1 1 100% !important;
                min-width: 100% !important;
                margin-bottom: 0.5rem !important;
            }

            /* Hide Spacers on Mobile to save vertical space */
            [data-testid="column"]:has(div[style*="height: 0px"]) {
                display: none !important;
            }

            /* Target columns that contain no visible Streamlit elements (spacers) */
            [data-testid="column"]:empty {
                display: none !important;
            }

            /* 5. Make buttons feel better on touch */
            div.stButton > button {
                width: 100% !important;
                height: 48px !important; /* Larger touch target */
                font-size: 1rem !important;
            }

            /* 6. Profile Button Alignment on Mobile */
            [data-testid="stPopover"] {
                width: 100% !important;
            }
            [data-testid="stPopover"] button {
                width: 100% !important;
                border-radius: 8px !important; /* Rectangular on mobile for better touch */
                justify-content: flex-start !important;
                padding-left: 15px !important;
            }
            [data-testid="stPopover"] button::after {
                content: "  Account Settings";
                font-size: 0.9rem;
                font-weight: 500;
                margin-left: 10px;
            }
        }

        /* 6. SIDEBAR ALIGNMENT */
        [data-testid="stSidebar"] {
            background-color: #F8FAFC !important;
            border-right: 1px solid #E2E8F0 !important;
        }

        footer {visibility: hidden !important;}
    </style>
    """
    st.markdown(premium_css, unsafe_allow_html=True)
