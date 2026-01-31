"""
Spotifyダウンローダー
spotdlを使用して音楽をダウンロードする
"""

from pathlib import Path

from .base import BaseDownloader, DownloadResult
from config import Config


class SpotifyDownloader(BaseDownloader):
    """Spotify用ダウンローダー"""
    
    @property
    def service_name(self) -> str:
        return "Spotify"
    
    @property
    def folder_prefix(self) -> str:
        return Config.SPOTIFY_PREFIX
    
    async def download(self, url: str) -> DownloadResult:
        """
        Spotifyから音楽をダウンロードする
        """
        # ダウンロード前のフォルダ一覧を取得
        existing_folders = set(self.download_path.iterdir()) if self.download_path.exists() else set()
        
        # 出力テンプレート: {artist} - {album}/{title}.{output-ext}
        output_template = "{artist} - {album}/{title}.{output-ext}"
        
        cmd = [
            "spotdl",
            "download",
            url,
            "--output", str(self.download_path / output_template),
            "--format", "opus",
            "--bitrate", "320k",
            "--headless",  # インタラクティブモードを無効化
            "--print-errors",
        ]
        
        returncode, stdout, stderr = await self.run_command(cmd)
        
        if returncode != 0:
            return DownloadResult(
                success=False,
                message="ダウンロード失敗",
                error=stderr or stdout,
            )
        
        # 新しく作成されたフォルダを特定
        new_folders = set(self.download_path.iterdir()) - existing_folders
        
        if new_folders:
            results = []
            total_files = 0
            
            for folder in new_folders:
                if folder.is_dir():
                    file_count = self.count_audio_files(folder)
                    total_files += file_count
                    dest = self.move_to_library(folder, add_prefix=True)
                    results.append(dest.name)
            
            if results:
                return DownloadResult(
                    success=True,
                    message=f"ダウンロード完了: {', '.join(results)}",
                    folder_path=self.library_path / results[0] if results else None,
                    file_count=total_files,
                )
        
        return DownloadResult(
            success=True,
            message="ダウンロード完了（フォルダ特定不可）",
        )
