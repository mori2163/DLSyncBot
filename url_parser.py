"""
URL判別モジュール
入力されたURLがどのサービスのものかを判定する
"""

import re
from enum import Enum, auto


class ServiceType(Enum):
    """サービス種別"""
    QOBUZ = auto()
    YOUTUBE = auto()
    SPOTIFY = auto()
    UNKNOWN = auto()


class URLParser:
    """URL解析クラス"""
    
    # 各サービスのURLパターン
    PATTERNS = {
        ServiceType.QOBUZ: [
            r"https?://(?:www\.)?(?:play\.)?qobuz\.com/",
            r"https?://open\.qobuz\.com/",
        ],
        ServiceType.YOUTUBE: [
            r"https?://(?:www\.)?youtube\.com/watch\?v=",
            r"https?://(?:www\.)?youtube\.com/playlist\?list=",
            r"https?://youtu\.be/",
            r"https?://(?:www\.)?youtube\.com/shorts/",
            r"https?://music\.youtube\.com/",
        ],
        ServiceType.SPOTIFY: [
            r"https?://open\.spotify\.com/",
        ],
    }
    
    @classmethod
    def parse(cls, url: str) -> ServiceType:
        """
        URLからサービス種別を判定する
        
        Args:
            url: 判定対象のURL
            
        Returns:
            ServiceType: 判定されたサービス種別
        """
        url = url.strip()
        
        for service, patterns in cls.PATTERNS.items():
            for pattern in patterns:
                if re.match(pattern, url, re.IGNORECASE):
                    return service
        
        return ServiceType.UNKNOWN
    
    @classmethod
    def detect_service(cls, url: str) -> ServiceType:
        """parseのエイリアス"""
        return cls.parse(url)
    
    @classmethod
    def is_valid_url(cls, url: str) -> bool:
        """URLが有効かどうかを判定"""
        return cls.parse(url) != ServiceType.UNKNOWN
    
    @classmethod
    def get_service_name(cls, service: ServiceType) -> str:
        """サービス種別から表示名を取得"""
        names = {
            ServiceType.QOBUZ: "Qobuz",
            ServiceType.YOUTUBE: "YouTube",
            ServiceType.SPOTIFY: "Spotify",
            ServiceType.UNKNOWN: "不明",
        }
        return names.get(service, "不明")
