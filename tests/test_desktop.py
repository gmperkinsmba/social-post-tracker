import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import server
from desktop_policy import navigation_policy


class DesktopLifecycleTests(unittest.TestCase):
    def test_native_navigation_policy(self):
        origin = "http://127.0.0.1:49125/"
        self.assertEqual(navigation_policy(origin, origin, False, False), "allow")
        self.assertEqual(navigation_policy("blob:" + origin + "export", origin, False, True), "download")
        for url in ("file:///etc/passwd", "javascript:alert(1)", "data:text/html,no", "http://127.0.0.1:49126/"):
            self.assertEqual(navigation_policy(url, origin, False, False), "cancel")
        self.assertEqual(navigation_policy("https://example.org", origin, True, False), "external")
        self.assertEqual(navigation_policy("https://example.org", origin, False, False), "cancel")

    def test_ephemeral_server_uses_its_actual_origin_and_stops(self):
        saved = {name: getattr(server, name) for name in ("RUNTIME", "DATA_FILE")}
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            os.chmod(runtime, 0o700)
            server.RUNTIME = runtime
            server.DATA_FILE = runtime / "workspace.json"
            with patch("socket.getfqdn", side_effect=AssertionError("reverse DNS must not run")):
                http = server.make_server(port=0)
            worker = threading.Thread(target=http.serve_forever, daemon=True)
            worker.start()
            base = f"http://127.0.0.1:{http.server_port}"
            try:
                with urllib.request.urlopen(base + "/", timeout=3) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(b"<h1>Social Post Tracker</h1>", response.read())
                request = urllib.request.Request(base + "/api/state", headers={"Origin": base})
                with urllib.request.urlopen(request, timeout=3) as response:
                    self.assertEqual(response.status, 200)
                request = urllib.request.Request(base + "/api/state", headers={"Origin": "https://example.org"})
                with self.assertRaises(urllib.error.HTTPError) as failure:
                    urllib.request.urlopen(request, timeout=3)
                self.assertEqual(failure.exception.code, 403)
            finally:
                http.shutdown()
                http.server_close()
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(http.fileno(), -1)
        for name, value in saved.items():
            setattr(server, name, value)


if __name__ == "__main__":
    unittest.main()
