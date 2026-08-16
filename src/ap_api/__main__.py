"""Run the interface layer locally: `PYTHONPATH=src python3 -m ap_api` (or the `ap-api` console script).

Binds to localhost by default (AP_API_HOST / AP_API_PORT env vars override) - phase 2 is local-first
per docs/DESIGN-FATHM-SYSTEM.md section 20a; nothing here presumes a hosting model.
"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "ap_api.app:app",
        host=os.environ.get("AP_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("AP_API_PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
