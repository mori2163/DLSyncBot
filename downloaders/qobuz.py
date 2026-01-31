"""
Qobuzダウンローダー
qobuz-dlを使用して高品質音源をダウンロードする
"""

import asyncio
import logging
from pathlib import Path

from qobuz_dl.core import QobuzDL

from .base import BaseDownloader, DownloadResult
from config import Config

logger = logging.getLogger(__name__)


class QobuzDownloader(BaseDownloader):
    """Qobuz用ダウンローダー"""
    
    def __init__(self, download_path: Path, library_path: Path):
        super().__init__(download_path, library_path)
        self.max_retries = Config.MAX_RETRIES
        self._qobuz: QobuzDL | None = None
        self._initialized = False
    
    def _initialize_client(self) -> None:
        """QobuzDLクライアントを初期化"""
        if self._initialized:
            return
        
        self._qobuz = QobuzDL(
            directory=str(self.download_path),
            quality=27,  # 最高音質 (24bit/192kHz)
            embed_art=True,
        )
        self._qobuz.get_tokens()
        self._qobuz.initialize_client(
            Config.QOBUZ_EMAIL,
            Config.QOBUZ_PASSWORD,
            self._qobuz.app_id,
            self._qobuz.secrets,
        )
        self._initialized = True
        logger.info("QobuzDLクライアントを初期化しました")
    
    @property
    def service_name(self) -> str:
        return "Qobuz"
    
    @property
    def folder_prefix(self) -> str:
        # Qobuzは高品質音源なので接頭辞なし
        return ""
    
    async def download(self, url: str) -> DownloadResult:
        """
        Qobuzから音楽をダウンロードする
        失敗時は成功するまでリトライを行う
        """
        # ダウンロード前のフォルダ一覧を取得
        existing_folders = set(self.download_path.iterdir()) if self.download_path.exists() else set()
        
        for attempt in range(1, self.max_retries + 1):
            result = await self._execute_download(url, attempt)
            
            if result.success:
                # 新しく作成されたフォルダを特定
                new_folders = set(self.download_path.iterdir()) - existing_folders
                
                if new_folders:
                    # 最新のフォルダをライブラリに移動
                    for folder in new_folders:
                        if folder.is_dir():
                            file_count = self.count_audio_files(folder)
                            dest = self.move_to_library(folder, add_prefix=False)
                            return DownloadResult(
                                success=True,
                                message=f"ダウンロード完了: {dest.name}",
                                folder_path=dest,
                                file_count=file_count,
                            )
                
                return DownloadResult(
                    success=True,
                    message="ダウンロード完了（フォルダ特定不可）",
                )
        
        return DownloadResult(
            success=False,
            message=f"ダウンロード失敗（{self.max_retries}回リトライ後）",
            error="最大リトライ回数を超過",
        )
    
    async def _execute_download(self, url: str, attempt: int) -> DownloadResult:
        """qobuz-dl Python APIを使用してダウンロード"""
        try:
            # 初回呼び出し時にクライアントを初期化
            self._initialize_client()
            
            # ブロッキング処理をスレッドプールで実行
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._qobuz.handle_url, url)
            
            return DownloadResult(
                success=True,
                message=f"試行 {attempt}: 成功",
            )
        except Exception as e:
            logger.warning(f"試行 {attempt}: ダウンロード失敗 - {e}")
            return DownloadResult(
                success=False,
                message=f"試行 {attempt}: 失敗",
                error=str(e),
            )
