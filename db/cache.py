"""Per-table cache invalidation.

Every cached read is keyed on its table's *data version*; every write bumps that version.
A save therefore refreshes only the tables it touched, for every user session at once,
instead of wiping all caches with st.cache_data.clear(). Writes made outside this app
(scripts, other servers) are picked up when the cache TTL expires.
"""

import streamlit as st


@st.cache_resource
def _versions() -> dict[str, int]:
    """Process-wide data version per table, shared by every user session."""
    return {}


def data_version(table: str) -> int:
    return _versions().get(table, 0)


def invalidate(*tables: str) -> None:
    """Mark tables as changed: their cached reads are refetched; other tables' stay cached."""
    versions = _versions()
    for table in tables:
        versions[table] = versions.get(table, 0) + 1
