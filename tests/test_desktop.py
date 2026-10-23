import socket
import unittest
from unittest.mock import patch

from app.desktop_runtime import DesktopServer
from desktop_app import main


class DesktopRuntimeTests(unittest.TestCase):
    def test_invalid_ports_fail_without_starting_a_server(self):
        for port in [0, -1, 65536]:
            with self.subTest(port=port), self.assertRaises(ValueError):
                DesktopServer(port)

    def test_reused_service_is_not_owned_or_stopped(self):
        with patch("app.desktop_runtime.is_vrs", return_value=True), patch("app.desktop_runtime.socket.socket") as listener:
            server = DesktopServer(8765)
            self.assertEqual(server.start(), "http://127.0.0.1:8765")
            self.assertTrue(server.reused)
            server.stop()
            listener.assert_not_called()

    def test_unrelated_listener_is_not_terminated(self):
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            with patch("app.desktop_runtime.is_vrs", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "端口"):
                    DesktopServer(port).start()
            self.assertGreater(occupied.fileno(), -1)

    def test_cli_invalid_port_is_rejected_before_gui(self):
        with self.assertRaises(SystemExit) as error:
            main(["--port", "65536"])
        self.assertEqual(error.exception.code, 2)

    def test_backend_failure_releases_owned_listener(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = DesktopServer(port)
        with patch("app.desktop_runtime.is_vrs", return_value=False), patch("uvicorn.Server"):
            with self.assertRaisesRegex(RuntimeError, "启动失败"):
                server.start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))


if __name__ == "__main__":
    unittest.main()
