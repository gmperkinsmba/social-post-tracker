#!/usr/bin/env python3
"""Native macOS shell for Viral Content Lab."""
from __future__ import annotations

import threading

import server as product
import webview
from desktop_policy import install_policy


def run() -> None:
    server = product.make_server(port=0)
    worker = threading.Thread(target=server.serve_forever, name="viral-content-lab-http", daemon=True)
    started = False
    try:
        worker.start()
        started = True
        url = f"http://127.0.0.1:{server.server_port}/?desktop=1"
        install_policy(url)
        webview.create_window("Viral Content Lab", url, width=1080, height=760, min_size=(800, 580))
        webview.start()
    finally:
        if started:
            server.shutdown()
        server.server_close()
        if started:
            worker.join(timeout=3)


if __name__ == "__main__":
    try:
        run()
    except Exception:
        import AppKit

        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("Viral Content Lab could not start")
        alert.setInformativeText_("The local app could not open. Quit and try again.")
        alert.addButtonWithTitle_("OK")
        alert.runModal()
        raise SystemExit(1)
