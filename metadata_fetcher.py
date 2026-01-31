"""
メタデータ取得モジュール
各サービスからタイトル、アーティスト、サムネイルなどの情報を取得する
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests
from qobuz_dl.core import QobuzDL
from qobuz_dl.exceptions import (
    AuthenticationError,
    IneligibleError,
    InvalidAppIdError,
    InvalidAppSecretError,
)
from qobuz_dl.utils import get_url_info

from config import Config
from url_parser import ServiceType, URLParser

logger = logging.getLogger(__name__)


@dataclass
class MediaMetadata:
    """メディアのメタデータ"""
    title: str
    artist: str
    service: ServiceType
    thumbnail_url: Optional[str] = None
    duration: Optional[int] = None  # 秒
    album: Optional[str] = None
    track_count: Optional[int] = None  # プレイリスト/アルバムの曲数
    url: str = ""


class MetadataFetcher:
    """メタデータ取得クラス"""

    _qobuz_client = None
    _qobuz_lock = None
    
    @classmethod
    async def fetch(cls, url: str) -> Optional[MediaMetadata]:
        """
        URLからメタデータを取得する
        
        Args:
            url: 取得対象のURL
            
        Returns:
            MediaMetadata: 取得したメタデータ、失敗時はNone
        """
        service = URLParser.detect_service(url)
        
        if service == ServiceType.YOUTUBE:
            return await cls._fetch_youtube(url)
        elif service == ServiceType.SPOTIFY:
            return await cls._fetch_spotify(url)
        elif service == ServiceType.QOBUZ:
            return await cls._fetch_qobuz(url)
        else:
            return None
    
    @classmethod
    async def _run_command(
        cls,
        cmd: list[str],
        timeout: int = 30,
    ) -> tuple[int, str, str]:
        """外部コマンドを非同期で実行"""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout,
            )
            return (
                process.returncode or 0,
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
            )
        except asyncio.TimeoutError:
            return -1, "", "タイムアウト"
        except Exception as e:
            return -1, "", str(e)
    
    @classmethod
    async def _fetch_youtube(cls, url: str) -> Optional[MediaMetadata]:
        """YouTubeからメタデータを取得"""
        cmd = [
            "yt-dlp",
            "--js-runtimes", "node",
            "--extractor-args", "youtube:player_client=android,web",
            "--dump-json",
            "--no-download",
            "--no-playlist",
            url,
        ]
        
        returncode, stdout, stderr = await cls._run_command(cmd, timeout=30)
        
        if returncode != 0:
            logger.error(f"YouTube metadata fetch failed: {stderr}")
            return None
        
        try:
            data = json.loads(stdout)
            
            # プレイリストかどうか確認
            is_playlist = "list=" in url and "entries" in data
            
            return MediaMetadata(
                title=data.get("title", "不明"),
                artist=data.get("channel", data.get("uploader", "不明")),
                service=ServiceType.YOUTUBE,
                thumbnail_url=data.get("thumbnail"),
                duration=data.get("duration"),
                album=data.get("album"),
                track_count=data.get("playlist_count") if is_playlist else 1,
                url=url,
            )
        except json.JSONDecodeError as e:
            logger.error(f"YouTube JSON parse error: {e}")
            return None
    
    @classmethod
    async def _fetch_spotify(cls, url: str) -> Optional[MediaMetadata]:
        """Spotifyからメタデータを取得"""
        cmd = [
            "spotdl",
            "url",
            url,
        ]
        
        returncode, stdout, stderr = await cls._run_command(cmd, timeout=30)
        
        if returncode != 0:
            logger.error(f"Spotify metadata fetch failed: {stderr}")
            # フォールバック: URLからタイプを推測
            return cls._parse_spotify_url(url)
        
        try:
            # spotdl urlの出力をパース
            # 形式: "Artist - Title" または JSON
            lines = stdout.strip().split("\n")
            
            # JSONとして解析を試みる
            try:
                data = json.loads(stdout)
                if isinstance(data, list) and len(data) > 0:
                    first = data[0]
                    return MediaMetadata(
                        title=first.get("name", "不明"),
                        artist=first.get("artist", "不明"),
                        service=ServiceType.SPOTIFY,
                        thumbnail_url=first.get("cover_url"),
                        duration=first.get("duration"),
                        album=first.get("album_name"),
                        track_count=len(data),
                        url=url,
                    )
            except json.JSONDecodeError:
                pass
            
            # テキスト形式をパース
            if lines:
                # "Found X songs" パターン
                found_match = re.search(r"Found (\d+) songs?", stdout)
                track_count = int(found_match.group(1)) if found_match else 1
                
                # 最後の行が曲名であることが多い
                for line in lines:
                    if " - " in line and not line.startswith("Found"):
                        parts = line.split(" - ", 1)
                        return MediaMetadata(
                            title=parts[1] if len(parts) > 1 else parts[0],
                            artist=parts[0],
                            service=ServiceType.SPOTIFY,
                            track_count=track_count,
                            url=url,
                        )
            
            return cls._parse_spotify_url(url)
            
        except Exception as e:
            logger.error(f"Spotify parse error: {e}")
            return cls._parse_spotify_url(url)
    
    @classmethod
    def _parse_spotify_url(cls, url: str) -> Optional[MediaMetadata]:
        """SpotifyのURLからタイプを推測"""
        # URLパターン: open.spotify.com/track/xxx, /album/xxx, /playlist/xxx
        if "/track/" in url:
            content_type = "トラック"
        elif "/album/" in url:
            content_type = "アルバム"
        elif "/playlist/" in url:
            content_type = "プレイリスト"
        else:
            content_type = "不明"
        
        return MediaMetadata(
            title=f"Spotify {content_type}",
            artist="取得中...",
            service=ServiceType.SPOTIFY,
            url=url,
        )
    
    @classmethod
    async def _fetch_qobuz(cls, url: str) -> Optional[MediaMetadata]:
        """Qobuzからメタデータを取得"""
        try:
            url_type, item_id = get_url_info(url)
        except (AttributeError, TypeError):
            return cls._parse_qobuz_url(url)

        client = await cls._get_qobuz_client()
        if client is None:
            return cls._parse_qobuz_url(url)

        try:
            if url_type == "album":
                data = await asyncio.to_thread(client.get_album_meta, item_id)
                image_url = cls._extract_qobuz_image(data.get("image"))
                artist = data.get("artist", {}).get("name", "不明")
                track_count = data.get("tracks_count") or len(
                    data.get("tracks", {}).get("items", [])
                )
                return MediaMetadata(
                    title=data.get("title", "不明"),
                    artist=artist,
                    service=ServiceType.QOBUZ,
                    thumbnail_url=image_url,
                    duration=data.get("duration"),
                    album=data.get("title"),
                    track_count=track_count or None,
                    url=url,
                )
            if url_type == "track":
                data = await asyncio.to_thread(client.get_track_meta, item_id)
                album = data.get("album", {})
                image_url = cls._extract_qobuz_image(album.get("image"))
                artist = (
                    data.get("performer", {}).get("name")
                    or data.get("artist", {}).get("name")
                    or album.get("artist", {}).get("name")
                    or "不明"
                )
                return MediaMetadata(
                    title=data.get("title", "不明"),
                    artist=artist,
                    service=ServiceType.QOBUZ,
                    thumbnail_url=image_url,
                    duration=data.get("duration"),
                    album=album.get("title"),
                    track_count=1,
                    url=url,
                )
            if url_type == "playlist":
                data = await asyncio.to_thread(lambda: next(client.get_plist_meta(item_id)))
                image_url = cls._extract_qobuz_image(
                    data.get("image") or data.get("picture")
                )
                return MediaMetadata(
                    title=data.get("name", "不明"),
                    artist=data.get("owner", {}).get("name", "不明"),
                    service=ServiceType.QOBUZ,
                    thumbnail_url=image_url,
                    track_count=data.get("tracks_count"),
                    url=url,
                )
            if url_type == "artist":
                data = await asyncio.to_thread(lambda: next(client.get_artist_meta(item_id)))
                image_url = cls._extract_qobuz_image(
                    data.get("image") or data.get("picture")
                )
                return MediaMetadata(
                    title=data.get("name", "不明"),
                    artist=data.get("name", "不明"),
                    service=ServiceType.QOBUZ,
                    thumbnail_url=image_url,
                    track_count=data.get("albums_count"),
                    url=url,
                )
            if url_type == "label":
                data = await asyncio.to_thread(lambda: next(client.get_label_meta(item_id)))
                image_url = cls._extract_qobuz_image(
                    data.get("image") or data.get("picture")
                )
                return MediaMetadata(
                    title=data.get("name", "不明"),
                    artist=data.get("name", "不明"),
                    service=ServiceType.QOBUZ,
                    thumbnail_url=image_url,
                    track_count=data.get("albums_count"),
                    url=url,
                )
        except (
            AuthenticationError,
            IneligibleError,
            InvalidAppIdError,
            InvalidAppSecretError,
            requests.exceptions.RequestException,
            StopIteration,
        ) as e:
            logger.error(f"Qobuz metadata fetch failed: {e}")

        return cls._parse_qobuz_url(url)

    @classmethod
    async def _get_qobuz_client(cls):
        """Qobuz APIクライアントを初期化して返す"""
        if not Config.QOBUZ_EMAIL or not Config.QOBUZ_PASSWORD:
            return None

        if cls._qobuz_client:
            return cls._qobuz_client

        if cls._qobuz_lock is None:
            cls._qobuz_lock = asyncio.Lock()

        async with cls._qobuz_lock:
            if cls._qobuz_client:
                return cls._qobuz_client

            def init_client():
                qobuz = QobuzDL(
                    directory=str(Config.DOWNLOAD_PATH),
                    quality=27,
                    embed_art=True,
                )
                qobuz.get_tokens()
                qobuz.initialize_client(
                    Config.QOBUZ_EMAIL,
                    Config.QOBUZ_PASSWORD,
                    qobuz.app_id,
                    qobuz.secrets,
                )
                return qobuz.client

            try:
                cls._qobuz_client = await asyncio.to_thread(init_client)
                return cls._qobuz_client
            except (
                AuthenticationError,
                IneligibleError,
                InvalidAppIdError,
                InvalidAppSecretError,
                requests.exceptions.RequestException,
            ) as e:
                logger.error(f"Qobuz auth failed: {e}")
                return None

    @classmethod
    def _extract_qobuz_image(cls, image_data: Optional[dict]) -> Optional[str]:
        if not isinstance(image_data, dict):
            return None
        for key in ("mega", "extralarge", "large", "medium", "small", "thumbnail"):
            url = image_data.get(key)
            if url:
                return url
        return None

    @classmethod
    def _parse_qobuz_url(cls, url: str) -> Optional[MediaMetadata]:
        """QobuzのURLからタイプを推測"""
        if "/album/" in url:
            content_type = "アルバム"
        elif "/track/" in url:
            content_type = "トラック"
        elif "/playlist/" in url:
            content_type = "プレイリスト"
        elif "/artist/" in url:
            content_type = "アーティスト"
        else:
            content_type = "不明"

        match = re.search(r"/(\d+)(?:\?|$|/)", url)
        item_id = match.group(1) if match else "不明"

        return MediaMetadata(
            title=f"Qobuz {content_type}",
            artist=f"ID: {item_id}",
            service=ServiceType.QOBUZ,
            url=url,
        )
