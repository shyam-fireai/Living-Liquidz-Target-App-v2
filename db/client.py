"""ClickHouse connection (one cached client per server process)."""

import logging

import clickhouse_connect
import streamlit as st

from config import get_db_settings

logger = logging.getLogger(__name__)


@st.cache_resource
def get_client():
    conf = get_db_settings()
    client = clickhouse_connect.get_client(
        host=conf["host"],
        port=conf["port"],
        username=conf["username"],
        password=conf["password"],
        database=conf["database"],
        secure=conf["secure"],  # true for TLS (live server), false for local Docker
        connect_timeout=30,
        send_receive_timeout=60,
    )
    logger.info("ClickHouse client connected to %s/%s", conf["host"], conf["database"])
    return client
