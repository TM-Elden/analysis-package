"""ap-api: the C3/C10 interface layer (design doc section 15) - phase-3 manager console's backend.

Import the FastAPI instance as `ap_api.app:app` (module path), not `ap_api.app` as an attribute of
this package - re-exporting it here would shadow the `ap_api.app` submodule itself, which is also
this file's name (`ap_api/app.py`). `uvicorn ap_api.app:app` and the `ap-api` console script both
already use the module-path form.
"""
