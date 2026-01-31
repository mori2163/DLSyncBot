"""
MusicDownloaderBot エントリーポイント
"""

import sys
from config import Config
from bot import get_bot


def main() -> int:
    """メイン関数"""
    # 設定検証
    errors = Config.validate()
    if errors:
        print("設定エラー:")
        for error in errors:
            print(f"  - {error}")
        print("\n.envファイルを確認してください。")
        return 1
    
    # ディレクトリ作成
    Config.ensure_directories()
    print(f"ダウンロード先: {Config.DOWNLOAD_PATH}")
    print(f"ライブラリ: {Config.LIBRARY_PATH}")
    
    # Bot起動
    bot = get_bot()
    print("Botを起動中...")
    
    try:
        bot.run(Config.DISCORD_TOKEN)
    except Exception as e:
        print(f"Bot起動エラー: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
