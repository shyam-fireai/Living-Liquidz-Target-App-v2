import logging

# Streamlit logs "No runtime found" warnings when cached functions are imported outside `streamlit run`.
logging.getLogger("streamlit").setLevel(logging.ERROR)
