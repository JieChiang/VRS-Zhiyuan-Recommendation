from __future__ import annotations

import sys
import webbrowser
from urllib.parse import urlsplit
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView


def main() -> None:
    url = "http://127.0.0.1:8000"
    try:
        class BrowserManager:
            def __init__(self) -> None:
                self._windows: dict[str, QWebEngineView] = {}

            @staticmethod
            def _window_key(page_url: str) -> str:
                parsed = urlsplit(page_url)
                path = parsed.path or "/"
                if path == "/":
                    return "main"
                return path

            def _on_window_closed(self, key: str, view: QWebEngineView) -> None:
                if self._windows.get(key) is view:
                    self._windows.pop(key, None)

            def _new_view(self, title: str = "高考志愿推荐系统 - 桌面端") -> QWebEngineView:
                view = QWebEngineView()
                view.setWindowTitle(title)
                view.resize(1400, 900)
                return view

            def show_main(self, page_url: str) -> None:
                key = self._window_key(page_url)
                view = self._new_view()
                view.load(QUrl(page_url))
                view.show()
                view.raise_()
                view.activateWindow()
                self._windows[key] = view
                self._install_popup_handler(view)
                view.destroyed.connect(lambda _=None, k=key, v=view: self._on_window_closed(k, v))

            def _get_or_create_window(self, page_url: str, title: str) -> QWebEngineView:
                key = self._window_key(page_url)
                view = self._windows.get(key)
                if view is None:
                    view = self._new_view(title)
                    self._windows[key] = view
                    self._install_popup_handler(view)
                    view.destroyed.connect(
                        lambda _=None, k=key, v=view: self._on_window_closed(k, v)
                    )
                return view

            def _install_popup_handler(self, view: QWebEngineView) -> None:
                page = view.page()
                if not hasattr(page, "newWindowRequested"):
                    return

                def handle_new_window(request) -> None:
                    target_url = request.requestedUrl().toString()
                    if not target_url:
                        target_url = url

                    target_view = self._get_or_create_window(
                        target_url,
                        "高考志愿推荐系统 - 桌面端",
                    )
                    target_view.show()
                    target_view.raise_()
                    target_view.activateWindow()
                    request.openIn(target_view.page())

                page.newWindowRequested.connect(handle_new_window)

        app = QApplication(sys.argv)
        manager = BrowserManager()
        manager.show_main(url)
        sys.exit(app.exec())
    except Exception:
        webbrowser.open(url)
        print("PyQt6不可用，已使用系统浏览器打开:", url)


if __name__ == "__main__":
    main()
