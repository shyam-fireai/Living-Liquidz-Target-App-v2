"""ClickHouse connection (one cached client per server process)."""

import logging

import clickhouse_connect
import streamlit as st

from config import load_secrets

logger = logging.getLogger(__name__)


@st.cache_resource
def get_client():
    conf = load_secrets()["data_clickhouse"]
    client = clickhouse_connect.get_client(
        host=conf["host"],
        port=conf["port"],
        username=conf["username"],
        password=conf["password"],
        database=conf["database"],
        # Local Docker: "secure": false in secrets.json; live server: "secure": true
        secure=bool(conf.get("secure", False)),
        connect_timeout=30,
        send_receive_timeout=60,
    )
    logger.info("ClickHouse client connected to %s/%s", conf["host"], conf["database"])
    return client
