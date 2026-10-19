"""Local double-click launcher, used by the project BAT file."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.request import Request, urlopen
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
APP_TITLE = "高考志愿推荐系统"


def is_vrs(url: str) -> bool:
    try:
        with urlopen(Request(url + "/openapi.json"), timeout=2) as response:
            return json.load(response).get("info", {}).get("title") == APP_TITLE
    except Exception:
        return False


def open_when_ready(url: str, stopped: threading.Event) -> None:
    deadline = time.monotonic() + 60
    while not stopped.is_set() and time.monotonic() < deadline:
        if is_vrs(url):
            if not webbrowser.open(url):
                print("浏览器未能自动打开，请手动访问：" + url, flush=True)
            return
        stopped.wait(0.5)
    if not stopped.is_set():
        print("页面尚未就绪，请查看控制台日志。服务启动后手动打开：" + url, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="仅启动服务，不自动打开浏览器")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口必须为 1–65535")
    url = f"http://127.0.0.1:{args.port}"
    with socket.socket() as probe:
        probe.settimeout(1)
        occupied = probe.connect_ex(("127.0.0.1", args.port)) == 0
    if occupied:
        if is_vrs(url):
            print("项目已在运行，复用现有服务：" + url, flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        print(f"端口 {args.port} 已被其他程序占用，未停止任何已有进程。请释放端口后重试。", flush=True)
        return 1

    import uvicorn

    stopped = threading.Event()
    if not args.no_browser:
        threading.Thread(target=open_when_ready, args=(url, stopped), daemon=True).start()
    print("正在启动本地项目：" + url, flush=True)
    try:
        # Keep the original project root, SQLite and external private-env loader.
        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, reload=False)
    finally:
        stopped.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
