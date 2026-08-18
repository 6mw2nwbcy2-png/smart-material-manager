# Streamlit page entrypoint wrapper
# Keep the stone UI isolated from Streamlit's page registry and execute it explicitly.
import runpy

runpy.run_path("pages/stone_impl_v2.py", run_name="__main__")
