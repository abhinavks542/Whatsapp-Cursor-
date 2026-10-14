#!/usr/bin/env python3
"""Start the local Flask bridge and WhatsApp web console together."""

from __future__ import annotations

import subprocess
import time
import webbrowser
from pathlib import Path
from threading import Thread
from urllib.error import URLError
from urllib.request import urlopen

from bridge import app as bridge_app


PROJECT_ROOT = Path(__file__).resolve().parent
BRIDGE_HEALTH_URL = "http://127.0.0.1:5001/health"
WEB_CONSOLE_URL = "http://127.0.0.1:5002"
WEB_STATUS_URL = f"{WEB_CONSOLE_URL}/api/status"


def serve_bridge() -> None:
    bridge_app.run(
        host="127.0.0.1",
        port=5001,
        debug=False,
        use_reloader=False,
    )


def wait_for_bridge(timeout_seconds: float = 15) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urlopen(BRIDGE_HEALTH_URL, timeout=0.5) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(0.2)
    raise RuntimeError("The local message bridge did not become ready in time.")


def endpoint_is_available(url: str) -> bool:
    try:
        with urlopen(url, timeout=0.5) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def wait_for_console(client: subprocess.Popen, timeout_seconds: float = 15) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if endpoint_is_available(WEB_STATUS_URL):
            return
        if client.poll() is not None:
            raise RuntimeError("The WhatsApp console stopped before it became ready.")
        time.sleep(0.2)
    raise RuntimeError("The WhatsApp web console did not become ready in time.")


def main() -> None:
    if endpoint_is_available(WEB_STATUS_URL):
        print("WhatsApp console is already running; opening it.", flush=True)
        webbrowser.open(WEB_CONSOLE_URL)
        return

    if not endpoint_is_available(BRIDGE_HEALTH_URL):
        bridge_thread = Thread(target=serve_bridge, daemon=True)
        bridge_thread.start()
        print("Starting local WhatsApp bridge...", flush=True)
        wait_for_bridge()

    client = subprocess.Popen(
        ["node", str(PROJECT_ROOT / "baileys_client.js")],
        cwd=PROJECT_ROOT,
    )

    try:
        wait_for_console(client)
        print(f"Opening {WEB_CONSOLE_URL}", flush=True)
        webbrowser.open(WEB_CONSOLE_URL)
        client.wait()
    except KeyboardInterrupt:
        print("Stopping local WhatsApp client...", flush=True)
    finally:
        if client.poll() is None:
            client.terminate()
            try:
                client.wait(timeout=5)
            except subprocess.TimeoutExpired:
                client.kill()
                client.wait()


if __name__ == "__main__":
    main()