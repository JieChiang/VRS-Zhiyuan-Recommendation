"""Start the local backend and open the VRS Qt desktop window."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from app.desktop_runtime import DesktopServer


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765, help="本地服务端口（默认8765，与双击启动一致）")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("端口必须为 1–65535")
    storage_dir = Path(__file__).resolve().parent / "storage" / "desktop"
    temporary_dir = storage_dir / "tmp"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(temporary_dir)
    try:
        # Import here so missing Qt packages are reported before starting a server.
        from app.desktop_window import BrowserManager, create_application
    except ImportError as exc:
        print(f"桌面依赖不可用：{exc}。请在项目环境安装 requirements.txt。", file=sys.stderr)
        return 1
    server = DesktopServer(args.port)
    manager = None
    try:
        app = create_application()
        url = server.start()
        print(("复用已有服务：" if server.reused else "已启动本地服务：") + url, flush=True)
        manager = BrowserManager(app, url, storage_dir)
        manager.open_window(url)
        return app.exec()
    except Exception as exc:
        print(f"桌面启动失败：{exc}", file=sys.stderr)
        return 1
    finally:
        if manager:
            manager.dispose()
        server.stop()


if __name__ == "__main__":
    raise SystemExit(main())
