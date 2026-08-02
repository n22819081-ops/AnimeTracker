from __future__ import annotations

import hashlib
import os
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QStyledItemDelegate


class CoverImageCache(QObject):
    loaded = Signal(str, object)
    failed = Signal(str)

    def __init__(self, cache_dir: str | Path, parent=None) -> None:
        super().__init__(parent); self.cache_dir=Path(cache_dir); self.cache_dir.mkdir(parents=True,exist_ok=True); self.network=QNetworkAccessManager(self); self.memory={}; self.pending={}

    def placeholder(self, width=100, height=140) -> QPixmap:
        pixmap=QPixmap(width,height); pixmap.fill("#343a46")
        painter=QPainter(pixmap); painter.setPen(QPen(QColor("#788391"),2)); margin=max(8,width//7)
        painter.drawRect(margin,margin,width-margin*2,height-margin*2)
        painter.drawLine(margin,height-margin,width//2,height//2); painter.drawLine(width//2,height//2,width-margin,height-margin)
        painter.end(); return pixmap

    def request(self, url: str) -> QPixmap:
        if not url:return self.placeholder()
        if url in self.memory:return self.memory[url]
        path=self._path(url)
        if path.exists():
            pixmap=QPixmap(str(path))
            if not pixmap.isNull():self.memory[url]=pixmap; return pixmap
        if os.environ.get("QT_QPA_PLATFORM","").casefold()=="offscreen":return self.placeholder()
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


class CoverDelegate(QStyledItemDelegate):
    """Paints fixed-size cached thumbnails and starts non-blocking fetches on demand."""
    def __init__(self,cache_dir,parent=None,width=52,height=73):
        super().__init__(parent);self.cache=CoverImageCache(cache_dir,self);self.width=width;self.height=height
        self.cache.loaded.connect(lambda *_: self.parent().viewport().update() if self.parent() else None)

    def paint(self,painter,option,index):
        row=index.data(Qt.UserRole);pixmap=self.cache.request(row.cover_url if row else "")
        target=QRect(option.rect.x()+(option.rect.width()-self.width)//2,option.rect.y()+(option.rect.height()-self.height)//2,self.width,self.height)
        painter.save();painter.setClipRect(option.rect);painter.drawPixmap(target,pixmap.scaled(self.width,self.height,Qt.KeepAspectRatio,Qt.SmoothTransformation));painter.restore()

    def sizeHint(self,option,index):return QSize(self.width+12,self.height+8)
