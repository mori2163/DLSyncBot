"""
ダウンローダーモジュール
"""

from .base import BaseDownloader, DownloadResult
from .qobuz import QobuzDownloader
from .youtube import YouTubeDownloader
from .spotify import SpotifyDownloader

__all__ = [
    "BaseDownloader",
    "DownloadResult",
    "QobuzDownloader",
    "YouTubeDownloader",
    "SpotifyDownloader",
]
