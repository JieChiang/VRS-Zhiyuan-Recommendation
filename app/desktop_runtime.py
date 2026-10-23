"""Own only the local server started by this desktop session."""
from __future__ import annotations

import json
import socket
import threading
import time
from urllib.request import ProxyHandler, build_opener


def is_vrs(url: str) -> bool:
    try:
        with build_opener(ProxyHandler({})).open(url + "/openapi.json", timeout=1) as response:
            return json.load(response).get("info", {}).get("title") == "高考志愿推荐系统"
    except Exception:
        return False


class DesktopServer:
    def __init__(self, port: int = 8765):
        if not 1 <= port <= 65535:
            raise ValueError("端口必须为 1–65535")
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.reused = False
        self._socket = self._server = self._thread = None

    def start(self, timeout: float = 20) -> str:
        if self._thread or self.reused:
            return self.url
        if is_vrs(self.url):
            self.reused = True
            return self.url
        listener = socket.socket()
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", self.port))
            listener.listen(128)
        except OSError as exc:
            listener.close()
            raise RuntimeError(f"端口 {self.port} 不可用或被其他程序占用。请使用 --port 指定其他端口。") from exc
        self._socket = listener
        try:
            import uvicorn

            self._server = uvicorn.Server(uvicorn.Config(
                "app.main:app", host="127.0.0.1", port=self.port, reload=False, log_level="warning",
            ))
            self._thread = threading.Thread(target=self._server.run, kwargs={"sockets": [listener]}, daemon=True)
            self._thread.start()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if not self._thread.is_alive():
                    raise RuntimeError("本地后端启动失败，请查看控制台错误。")
                if self._server.started and is_vrs(self.url):
                    return self.url
                time.sleep(0.05)
            raise RuntimeError("等待本地后端超时，请检查控制台或更换端口。")
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)
        if self._socket:
            self._socket.close()
        self._socket = self._server = self._thread = None
