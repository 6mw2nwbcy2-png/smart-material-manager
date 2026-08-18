# Streamlit page entrypoint wrapper
# Keep the real stone implementation outside the page registry and execute it explicitly.
import runpy

runpy.run_path("pages/stone_impl.py", run_name="__main__")
