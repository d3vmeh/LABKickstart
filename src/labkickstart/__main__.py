"""Entry point for both `python -m labkickstart` and the PyInstaller
sidecar binary. Resolves a port (LK_PORT=0 means OS-assigned), prints
LK_PORT=<n> to stdout for a parent process to read, then runs uvicorn.
"""
from __future__ import annotations

import os
import socket
import sys

import uvicorn

from labkickstart.app import app


def _resolve_port() -> int:
    requested = int(os.environ.get("LK_PORT", "8000"))
    if requested != 0:
        return requested
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> None:
    port = _resolve_port()
    # The Tauri shell parses this exact line from stdout to learn the port.
    print(f"LK_PORT={port}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
    sys.exit(0)
