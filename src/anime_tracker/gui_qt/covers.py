from __future__ import annotations

import hashlib
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest


class CoverImageCache(QObject):
    loaded = Signal(str, object)
    failed = Signal(str)

    def __init__(self, cache_dir: str | Path, parent=None) -> None:
        super().__init__(parent); self.cache_dir=Path(cache_dir); self.cache_dir.mkdir(parents=True,exist_ok=True); self.network=QNetworkAccessManager(self); self.memory={}; self.pending={}

    def placeholder(self, width=100, height=140) -> QPixmap:
        pixmap=QPixmap(width,height); pixmap.fill("#343a46"); return pixmap

    def request(self, url: str) -> QPixmap:
        if not url:return self.placeholder()
        if url in self.memory:return self.memory[url]
        path=self._path(url)
        if path.exists():
            pixmap=QPixmap(str(path))
            if not pixmap.isNull():self.memory[url]=pixmap; return pixmap
        if url not in self.pending:
            reply=self.network.get(QNetworkRequest(QUrl(url))); self.pending[url]=reply; reply.finished.connect(lambda url=url,reply=reply:self._finished(url,reply))
        return self.placeholder()

    def _finished(self,url,reply):
        self.pending.pop(url,None)
        if reply.error()!=QNetworkReply.NoError:self.failed.emit(url); reply.deleteLater(); return
        data=bytes(reply.readAll()); pixmap=QPixmap()
        if pixmap.loadFromData(data):self._path(url).write_bytes(data); self.memory[url]=pixmap; self.loaded.emit(url,pixmap)
        else:self.failed.emit(url)
        reply.deleteLater()

    def _path(self,url):return self.cache_dir/(hashlib.sha256(url.encode("utf-8")).hexdigest()+".img")
