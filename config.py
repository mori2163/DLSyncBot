"""
設定管理モジュール
環境変数から各種設定を読み込む
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


class Config:
    """アプリケーション設定"""
    
    # Discord Bot設定
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
    
    # Qobuz認証情報
    QOBUZ_EMAIL: str = os.getenv("QOBUZ_EMAIL", "")
    QOBUZ_PASSWORD: str = os.getenv("QOBUZ_PASSWORD", "")
    
    # ダウンロード先パス
    DOWNLOAD_PATH: Path = Path(os.getenv("DOWNLOAD_PATH", "./downloads"))
    LIBRARY_PATH: Path = Path(os.getenv("LIBRARY_PATH", "./library"))
    
    # ダウンロード設定
    MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
    QUEUE_MAX_SIZE: int = int(os.getenv("QUEUE_MAX_SIZE", "100"))
    
    # 音声形式設定
    YOUTUBE_FORMAT: str = "opus"  # opus固定
    SPOTIFY_FORMAT: str = "opus"  # opus固定
    
    # フォルダ接頭辞
    YOUTUBE_PREFIX: str = "[YT] "
    SPOTIFY_PREFIX: str = "[SP] "
    
    @classmethod
    def validate(cls) -> list[str]:
        """設定の検証を行い、エラーメッセージのリストを返す"""
        errors = []
        
        if not cls.DISCORD_TOKEN:
            errors.append("DISCORD_TOKENが設定されていない")
        
        if not cls.QOBUZ_EMAIL or not cls.QOBUZ_PASSWORD:
            errors.append("Qobuz認証情報が不完全（QOBUZ_EMAIL, QOBUZ_PASSWORD）")
        
        return errors
    
    @classmethod
    def ensure_directories(cls) -> None:
        """必要なディレクトリを作成"""
        cls.DOWNLOAD_PATH.mkdir(parents=True, exist_ok=True)
        cls.LIBRARY_PATH.mkdir(parents=True, exist_ok=True)
