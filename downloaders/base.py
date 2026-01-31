"""
ダウンローダー基底クラス
"""

import asyncio
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from command_utils import resolve_command
from config import Config


@dataclass
class DownloadResult:
    """ダウンロード結果"""
    success: bool
    message: str
    folder_path: Optional[Path] = None
    file_count: int = 0
    error: Optional[str] = None


class BaseDownloader(ABC):
    """ダウンローダーの基底クラス"""
    
    def __init__(self, download_path: Path, library_path: Path):
        """
        Args:
            download_path: 一時ダウンロード先
            library_path: 最終配置先（Navidromeライブラリ）
        """
        self.download_path = download_path
        self.library_path = library_path
    
    @abstractmethod
    async def download(self, url: str) -> DownloadResult:
        """
        URLからコンテンツをダウンロードする
        
        Args:
            url: ダウンロード対象のURL
            
        Returns:
            DownloadResult: ダウンロード結果
        """
        pass
    
    @property
    @abstractmethod
    def service_name(self) -> str:
        """サービス名を返す"""
        pass
    
    @property
    def folder_prefix(self) -> str:
        """フォルダ名の接頭辞（必要に応じてオーバーライド）"""
        return ""
    
    async def run_command(
        self,
        cmd: list[str],
        cwd: Optional[Path] = None,
        timeout: Optional[int] = 1800,  # デフォルト30分
    ) -> tuple[int, str, str]:
        """
        外部コマンドを非同期で実行する
        
        Args:
            cmd: 実行するコマンドとその引数
            cwd: 作業ディレクトリ
            timeout: タイムアウト秒数（Noneで無制限）
            
        Returns:
            tuple: (リターンコード, 標準出力, 標準エラー出力)
        """
        resolved_cmd, error = resolve_command(cmd)
        if error:
            return -1, "", error

        # 実行時環境変数の構築
        env = os.environ.copy()
        if Config.FFMPEG_PATH:
            ffmpeg_path = Path(Config.FFMPEG_PATH)
            # ディレクトリパスの場合はそのまま、実行ファイルパスの場合は親ディレクトリをPATHに追加
            ffmpeg_dir = str(ffmpeg_path.parent) if ffmpeg_path.is_file() else str(ffmpeg_path)
            
            path_sep = ";" if os.name == "nt" else ":"
            env["PATH"] = f"{ffmpeg_dir}{path_sep}{env.get('PATH', '')}"

        process = await asyncio.create_subprocess_exec(
            *resolved_cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
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
            process.kill()
            await process.wait()
            return (
                -1,
                "",
                f"コマンドがタイムアウトしました（{timeout}秒）",
            )
    
    def move_to_library(self, source: Path, add_prefix: bool = True) -> Path:
        """
        ダウンロードしたフォルダをライブラリに移動する
        
        Args:
            source: 移動元のパス
            add_prefix: 接頭辞を付けるかどうか
            
        Returns:
            Path: 移動後のパス
        """
        folder_name = source.name
        if add_prefix and self.folder_prefix:
            folder_name = f"{self.folder_prefix}{folder_name}"
        
        destination = self.library_path / folder_name
        
        # 既存フォルダがある場合は上書き
        if destination.exists():
            shutil.rmtree(destination)
        
        shutil.move(str(source), str(destination))
        return destination
    
    def count_audio_files(self, folder: Path) -> int:
        """フォルダ内の音声ファイル数をカウント"""
        audio_extensions = {".flac", ".mp3", ".opus", ".ogg", ".m4a", ".wav"}
        count = 0
        for file in folder.rglob("*"):
            if file.suffix.lower() in audio_extensions:
                count += 1
        return count
