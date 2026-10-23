"""Qt shell for the existing Web UI, with shared local state and downloads."""
from __future__ import annotations

from pathlib import Path
import webbrowser
from urllib.parse import urlsplit

from PyQt6.QtCore import QCoreApplication, QEvent, Qt, QUrl
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QFileDialog, QMainWindow, QToolBar
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView


def same_origin(url: str, base_url: str) -> bool:
    try:
        target, base = urlsplit(url), urlsplit(base_url)
        port = lambda parsed: parsed.port or (443 if parsed.scheme == "https" else 80)
        return (target.scheme, target.hostname, port(target)) == (base.scheme, base.hostname, port(base))
    except ValueError:
        return False


def create_application() -> QApplication:
    # Qt WebEngine aborts the native process if QApplication receives an empty argv.
    app = QApplication(["VRS-desktop"])
    app.setApplicationName("VRS")
    app.setOrganizationName("VRS")
    return app


class LocalPage(QWebEnginePage):
    def __init__(self, manager, parent):
        super().__init__(manager.profile, parent)
        self.manager = manager

    def acceptNavigationRequest(self, url, navigation_type, is_main_frame):
        if not is_main_frame or url.toString() == "about:blank" or same_origin(url.toString(), self.manager.base_url):
            return True
        self.manager.open_external(url.toString())
        return False


class DesktopWindow(QMainWindow):
    def __init__(self, manager):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        if manager.hidden:
            self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.setWindowTitle("高考志愿推荐系统 - 桌面端")
        self.resize(1400, 900)
        self.web = QWebEngineView(self)
        self.web.setPage(LocalPage(manager, self.web))
        self.setCentralWidget(self.web)
        toolbar = QToolBar("页面操作", self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        refresh = QAction("刷新", self)
        refresh.setShortcut("F5")
        refresh.triggered.connect(self.web.reload)
        toolbar.addAction(refresh)
        open_browser = QAction("在浏览器中打开", self)
        open_browser.triggered.connect(lambda: manager.open_external(self.web.url().toString()))
        toolbar.addAction(open_browser)
        self.web.loadStarted.connect(lambda: self.statusBar().showMessage("正在加载…"))
        self.web.loadFinished.connect(lambda ok: self.statusBar().showMessage(
            "就绪" if ok else "页面加载失败，请确认本地服务正常后按 F5 刷新。"))
        self.web.page().renderProcessTerminated.connect(
            lambda *_: self.statusBar().showMessage("网页渲染进程已退出，请按 F5 刷新重试。"))
        self.web.page().newWindowRequested.connect(manager.open_popup)


class BrowserManager:
    def __init__(self, app, base_url: str, storage_dir: Path, *, hidden=False, choose_download=None, external_opener=webbrowser.open):
        self.base_url = base_url
        self.storage_dir = storage_dir
        self.hidden = hidden
        self.external_opener = external_opener
        self.choose_download = choose_download or self._choose_download
        self.windows = {}
        self.downloads = {}
        self.profile = QWebEngineProfile("VRS", app)
        self.profile.setPersistentStoragePath(str(storage_dir / "profile"))
        self.profile.setCachePath(str(storage_dir / "cache"))
        self.profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self.profile.downloadRequested.connect(self.save_download)

    def open_external(self, url: str):
        if urlsplit(url).scheme in {"http", "https"}:
            self.external_opener(url)

    def _window(self, url: str):
        key = urlsplit(url).path or "/"
        window = self.windows.get(key)
        if window is None:
            window = DesktopWindow(self)
            self.windows[key] = window
            window.destroyed.connect(lambda: self.windows.pop(key, None))
        return window

    def _show(self, window):
        window.show()
        if not self.hidden:
            window.raise_()
            window.activateWindow()

    def open_window(self, url: str):
        if not same_origin(url, self.base_url):
            self.open_external(url)
            return None
        window = self._window(url)
        window.web.load(QUrl(url))
        self._show(window)
        return window

    def open_popup(self, request):
        url = request.requestedUrl().toString()
        if not same_origin(url, self.base_url):
            self.open_external(url)
            return
        window = self._window(url)
        request.openIn(window.web.page())
        self._show(window)

    def _choose_download(self, suggested: Path) -> str:
        return QFileDialog.getSaveFileName(QApplication.activeWindow(), "保存下载文件", str(suggested), "所有文件 (*)")[0]

    def save_download(self, request):
        # Qt cancels downloads unless the application explicitly accepts them.
        name = Path(request.suggestedFileName().replace("\\", "/")).name or "VRS-download"
        directory = self.storage_dir / "downloads"
        directory.mkdir(parents=True, exist_ok=True)
        destination = self.choose_download(directory / name)
        if not destination:
            request.cancel()
            return
        path = Path(destination)
        request.setDownloadDirectory(str(path.parent))
        request.setDownloadFileName(path.name)
        key = request.id()
        self.downloads[key] = request

        def finished():
            if not request.isFinished():
                return
            if request.state() == request.DownloadState.DownloadCompleted:
                message = f"下载完成：{path}"
            else:
                message = "下载未完成：" + request.interruptReasonString()
            for window in self.windows.values():
                window.statusBar().showMessage(message)
            self.downloads.pop(key, None)

        request.isFinishedChanged.connect(finished)
        request.accept()

    def close(self):
        for request in list(self.downloads.values()):
            request.cancel()
        for window in list(self.windows.values()):
            window.close()

    def dispose(self):
        self.close()
        # Delete all pages before the profile to flush localStorage cleanly.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.profile.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
