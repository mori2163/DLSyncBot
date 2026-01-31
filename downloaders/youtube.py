"""
YouTubeダウンローダー
yt-dlpを使用して音声をダウンロードする
"""

import json
import logging
import re
from pathlib import Path

from .base import BaseDownloader, DownloadResult
from config import Config

logger = logging.getLogger(__name__)


class YouTubeDownloader(BaseDownloader):
    """YouTube用ダウンローダー"""
    
    @property
    def service_name(self) -> str:
        return "YouTube"
    
    @property
    def folder_prefix(self) -> str:
        return Config.YOUTUBE_PREFIX
    
    async def download(self, url: str) -> DownloadResult:
        """
        YouTubeから音声をダウンロードする
        """
        # 出力テンプレート: アーティスト - タイトル/タイトル.拡張子
        # プレイリストの場合はプレイリスト名をフォルダ名に使用
        output_template = str(
            self.download_path / "%(playlist_title,channel)s - %(title)s" / "%(title)s.%(ext)s"
        )
        
        cmd = [
            "yt-dlp",
            "--js-runtimes", "node",
            "--extractor-args", "youtube:player_client=android,web",
            "--extract-audio",
            "--audio-format", "opus",
            "--audio-quality", "0",  # 最高品質
            "--embed-thumbnail",
            "--embed-metadata",
            "--output", output_template,
            "--no-playlist" if "list=" not in url else "--yes-playlist",
            url,
        ]
        
        returncode, stdout, stderr = await self.run_command(cmd)
        
        if returncode != 0:
            return DownloadResult(
                success=False,
                message="ダウンロード失敗",
                error=stderr or stdout,
            )
        
        # ダウンロードされたフォルダを特定
        # yt-dlpの出力からファイルパスを抽出
        downloaded_folder = self._find_downloaded_folder(stdout)
        
        if downloaded_folder and downloaded_folder.exists():
            # cover.jpgを生成
            await self._generate_cover(url, downloaded_folder)
            
            file_count = self.count_audio_files(downloaded_folder)
            dest = self.move_to_library(downloaded_folder, add_prefix=True)
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
    
    async def _generate_cover(self, url: str, folder: Path) -> None:
        """サムネイルをcover.jpgとして保存"""
        cover_path = folder / "cover.jpg"
        
        # 既にcover.jpgがあればスキップ
        if cover_path.exists():
            return
        
        try:
            # yt-dlpでサムネイルのみを取得
            cmd = [
                "yt-dlp",
                "--js-runtimes", "node",
                "--extractor-args", "youtube:player_client=android,web",
                "--skip-download",
                "--write-thumbnail",
                "--convert-thumbnails", "jpg",
                "--output", str(folder / "cover"),
                "--no-playlist",
                url,
            ]
            
            returncode, stdout, stderr = await self.run_command(cmd)
            
            if returncode == 0:
                # yt-dlpは cover.jpg.jpg のようなファイル名になることがある
                for file in folder.glob("cover*.jpg"):
                    if file.name != "cover.jpg":
                        file.rename(cover_path)
                        break
                # webp等が生成された場合のリネーム
                for file in folder.glob("cover*.webp"):
                    file.rename(cover_path)
                    break
                    
                logger.info(f"cover.jpg生成完了: {cover_path}")
            else:
                logger.warning(f"サムネイル取得失敗: {stderr}")
        except Exception as e:
            logger.warning(f"cover.jpg生成中にエラー: {e}")
    
    def _find_downloaded_folder(self, output: str) -> Path | None:
        """yt-dlpの出力からダウンロードされたフォルダを特定"""
        # [download] Destination: パス形式の行を探す
        pattern = r"\[download\] Destination: (.+)"
        matches = re.findall(pattern, output)
        
        if matches:
            # 最初のファイルの親フォルダを返す
            file_path = Path(matches[0])
            if file_path.parent.exists():
                return file_path.parent
        
        # フォルダ名パターンで探す
        for folder in self.download_path.iterdir():
            if folder.is_dir():
                return folder
        
        return None
