"""
ファイル配信サーバー
一時的なダウンロードリンクを提供する
"""

import asyncio
import logging
import secrets
import urllib.parse
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable, Optional

from aiohttp import web

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class DownloadToken:
    """ダウンロードトークン情報"""
    token: str
    file_path: Path
    file_name: str
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: datetime = field(default=None)
    max_downloads: int = 3
    download_count: int = 0
    channel_id: Optional[int] = None
    message_id: Optional[int] = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    
    def __post_init__(self):
        if self.expires_at is None:
            self.expires_at = datetime.now() + timedelta(
                hours=Config.DOWNLOAD_LINK_EXPIRE_HOURS
            )
    
    @property
    def is_expired(self) -> bool:
        """有効期限切れかどうか"""
        return datetime.now() > self.expires_at
    
    @property
    def is_exhausted(self) -> bool:
        """ダウンロード回数上限に達したかどうか"""
        return self.download_count >= self.max_downloads
    
    @property
    def is_valid(self) -> bool:
        """トークンが有効かどうか"""
        return not self.is_expired and not self.is_exhausted
    
    @property
    def remaining_downloads(self) -> int:
        """残りダウンロード回数"""
        return max(0, self.max_downloads - self.download_count)


class FileServer:
    """ファイル配信サーバー"""
    
    def __init__(self, port: int = None):
        self.port = port or Config.FILE_SERVER_PORT
        self._tokens: dict[str, DownloadToken] = {}
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._download_callback: Optional[Callable[[DownloadToken], Awaitable[None]]] = None
        self._background_tasks: set[asyncio.Future] = set()

    def set_download_callback(
        self,
        callback: Optional[Callable[[DownloadToken], Awaitable[None]]],
    ) -> None:
        """ダウンロード後の処理コールバックを設定"""
        self._download_callback = callback

    def _schedule_download_callback(self, token: DownloadToken) -> None:
        """ダウンロード後のコールバックを実行"""
        if not self._download_callback:
            return

        task = asyncio.ensure_future(self._download_callback(token))
        self._background_tasks.add(task)

        def _log_error(done_task: asyncio.Future) -> None:
            self._background_tasks.discard(done_task)
            if done_task.cancelled():
                return
            error = done_task.exception()
            if error:
                logger.error(f"ダウンロード後処理でエラー: {error}")

        task.add_done_callback(_log_error)
    
    def create_download_link(
        self,
        file_path: Path,
        file_name: Optional[str] = None,
        max_downloads: Optional[int] = None,
    ) -> tuple[str, DownloadToken]:
        """
        ダウンロードリンクを生成する
        
        Args:
            file_path: ダウンロード対象のファイルパス
            file_name: ダウンロード時のファイル名（Noneの場合は元のファイル名）
            max_downloads: 最大ダウンロード回数（Noneの場合は設定値を使用）
            
        Returns:
            tuple: (ダウンロードURL, トークン情報)
        """
        token_id = str(uuid.uuid4())
        
        token = DownloadToken(
            token=token_id,
            file_path=file_path,
            file_name=file_name or file_path.name,
            max_downloads=max_downloads or Config.DOWNLOAD_LINK_MAX_COUNT,
        )
        
        self._tokens[token_id] = token
        
        base_url = Config.FILE_SERVER_BASE_URL.rstrip("/")
        if not base_url:
            base_url = f"http://localhost:{self.port}"
        
        download_url = f"{base_url}/download/{token_id}"
        
        logger.info(
            f"ダウンロードリンクを生成しました: {download_url} "
            f"(有効期限: {token.expires_at}, 最大回数: {token.max_downloads})"
        )
        
        return download_url, token
    
    def get_token_info(self, token_id: str) -> Optional[DownloadToken]:
        """トークン情報を取得"""
        return self._tokens.get(token_id)
    
    def invalidate_token(self, token_id: str) -> bool:
        """トークンを無効化してファイルを削除"""
        token = self._tokens.pop(token_id, None)
        if token:
            try:
                if token.file_path.exists():
                    token.file_path.unlink()
                    logger.info(f"一時ファイルを削除しました: {token.file_path}")
            except Exception as e:
                logger.error(f"ファイル削除に失敗しました: {e}")
            return True
        return False

    def _is_upload_authorized(self, request: web.Request) -> bool:
        """アップロードの認可を確認"""
        raw_required_token = Config.UPLOAD_TOKEN
        if not isinstance(raw_required_token, str):
            # トークンが未設定または文字列以外の場合は認可不要とみなす
            return True

        required_token = raw_required_token.strip()
        if not required_token:
            return True

        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

        if not token:
            token = request.headers.get("X-Upload-Token", "").strip()

        if not token:
            token = request.query.get("token", "").strip()

        return secrets.compare_digest(token, required_token)
    
    async def _handle_download(self, request: web.Request) -> web.StreamResponse:
        """ダウンロードリクエストを処理"""
        token_id = request.match_info.get("token")
        
        if not token_id:
            return web.Response(status=400, text="Token is required")
        
        token = self._tokens.get(token_id)
        
        if not token:
            return web.Response(status=404, text="Download link not found")
        
        async with token.lock:
            if token.is_expired:
                self.invalidate_token(token_id)
                return web.Response(status=410, text="Download link has expired")
            if token.is_exhausted:
                self.invalidate_token(token_id)
                return web.Response(status=410, text="Download limit reached")
            if not token.file_path.exists():
                self.invalidate_token(token_id)
                return web.Response(status=404, text="File not found")

            # ダウンロード回数をインクリメント
            token.download_count += 1
            remaining = token.remaining_downloads

            self._schedule_download_callback(token)

        logger.info(
            f"ダウンロード: {token.file_name} "
            f"(回数: {token.download_count}/{token.max_downloads})"
        )
        
        # 最後のダウンロードの場合、後でクリーンアップ
        if remaining == 0:
            asyncio.create_task(self._delayed_cleanup(token_id, delay=60))

        # 非ASCII文字を含むファイル名に対応 (RFC 5987)
        # 従来の引数用 (ASCIIのみに制限し、クォートとバックスラッシュをエスケープ)
        ascii_filename = token.file_name.encode("ascii", "ignore").decode("ascii") or "file"
        ascii_filename = ascii_filename.replace("\\", "\\\\").replace('"', '\\"')
        
        # RFC 5987 準拠の引数用 (UTF-8)
        encoded_filename = urllib.parse.quote(token.file_name, safe='')
        
        # ファイルを返す
        return web.FileResponse(
            path=token.file_path,
            headers={
                "Content-Disposition": f'attachment; filename="{ascii_filename}"; filename*=UTF-8\'\'{encoded_filename}',
                "X-Downloads-Remaining": str(remaining),
            },
        )

    async def _handle_upload(self, request: web.Request) -> web.Response:
        """アップロードリクエストを処理"""
        if not self._is_upload_authorized(request):
            return web.Response(status=401, text="Unauthorized")

        if not request.content_type.startswith("multipart/"):
            return web.Response(status=415, text="multipart/form-data required")

        if (
            request.content_length is not None
            and request.content_length > Config.UPLOAD_MAX_SIZE
        ):
            raise web.HTTPRequestEntityTooLarge(
                max_size=Config.UPLOAD_MAX_SIZE,
                actual_size=request.content_length,
            )

        reader = await request.multipart()
        field = None
        while True:
            part = await reader.next()
            if part is None:
                break
            if part.name == "file":
                field = part
                break

        if field is None or not field.filename:
            return web.Response(status=400, text="File is required")

        original_name = Path(field.filename).name or "upload"
        if (
            not original_name
            or original_name in (".", "..")
            or any(sep in original_name for sep in ("/", "\\"))
            or "\x00" in original_name
            or ":" in original_name
        ):
            return web.Response(status=400, text="Invalid file name")
        stored_name = f"{uuid.uuid4()}_{original_name}"
        Config.UPLOAD_PATH.mkdir(parents=True, exist_ok=True)
        target_path = Config.UPLOAD_PATH / stored_name

        size = 0
        success = False
        try:
            with target_path.open("wb") as file_handle:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > Config.UPLOAD_MAX_SIZE:
                        raise web.HTTPRequestEntityTooLarge(
                            max_size=Config.UPLOAD_MAX_SIZE,
                            actual_size=size,
                        )
                    file_handle.write(chunk)
            success = True
        finally:
            if not success and target_path.exists():
                target_path.unlink()

        logger.info(f"アップロード完了: {original_name} -> {target_path} ({size} bytes)")

        return web.json_response(
            {
                "uploaded": True,
                "file_name": original_name,
                "stored_name": stored_name,
                "size": size,
            }
        )
    
    async def _handle_info(self, request: web.Request) -> web.Response:
        """トークン情報を返す"""
        token_id = request.match_info.get("token")
        
        if not token_id:
            return web.Response(status=400, text="Token is required")
        
        token = self._tokens.get(token_id)
        
        if not token:
            return web.json_response({"valid": False, "reason": "not_found"})
        
        if not token.is_valid:
            reason = "expired" if token.is_expired else "exhausted"
            return web.json_response({"valid": False, "reason": reason})
        
        return web.json_response({
            "valid": True,
            "file_name": token.file_name,
            "remaining_downloads": token.remaining_downloads,
            "expires_at": token.expires_at.isoformat(),
        })
    
    async def _delayed_cleanup(self, token_id: str, delay: int = 60) -> None:
        """遅延してトークンをクリーンアップ"""
        await asyncio.sleep(delay)
        self.invalidate_token(token_id)
    
    async def _cleanup_expired_tokens(self) -> None:
        """期限切れトークンを定期的にクリーンアップ"""
        while True:
            try:
                await asyncio.sleep(3600)  # 1時間ごと
                
                expired_tokens = [
                    token_id
                    for token_id, token in self._tokens.items()
                    if not token.is_valid
                ]
                
                for token_id in expired_tokens:
                    self.invalidate_token(token_id)
                
                if expired_tokens:
                    logger.info(f"{len(expired_tokens)}件の期限切れトークンを削除しました")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"クリーンアップ中にエラーが発生しました: {e}")
    
    @property
    def is_running(self) -> bool:
        """サーバーが稼働中かどうか"""
        return self._runner is not None

    async def start(self) -> None:
        """サーバーを起動"""
        if self.is_running:
            logger.warning("ファイルサーバーは既に起動しています")
            return
        
        self._app = web.Application(client_max_size=Config.UPLOAD_MAX_SIZE)
        self._app.router.add_get("/download/{token}", self._handle_download)
        self._app.router.add_get("/info/{token}", self._handle_info)
        self._app.router.add_post("/upload", self._handle_upload)
        
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        
        self._site = web.TCPSite(self._runner, "0.0.0.0", self.port)
        await self._site.start()
        
        # クリーンアップタスクを開始
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_tokens())
        
        logger.info(f"ファイルサーバーを起動しました (port: {self.port})")
    
    async def stop(self) -> None:
        """サーバーを停止"""
        if not self.is_running:
            return

        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        
        if self._runner:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            self._app = None
        
        # 残っているトークンのファイルを削除
        for token_id in list(self._tokens.keys()):
            self.invalidate_token(token_id)
        
        logger.info("ファイルサーバーを停止しました")


# グローバルインスタンス
_file_server: Optional[FileServer] = None


def get_file_server() -> FileServer:
    """ファイルサーバーインスタンスを取得"""
    global _file_server
    if _file_server is None:
        _file_server = FileServer()
    return _file_server
