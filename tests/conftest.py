import logging

# Streamlit logs "No runtime found" warnings when cached functions are imported outside `streamlit run`.
logging.getLogger("streamlit").setLevel(logging.ERROR)

import pytest  # noqa: E402

import config  # noqa: E402


@pytest.fixture(autouse=True)
def no_streamlit_secrets(monkeypatch):
    """Tests never read a developer's .streamlit/secrets.toml; use `set_st_secrets` to provide some."""
    monkeypatch.setattr(config, "_streamlit_secrets", lambda: {})
