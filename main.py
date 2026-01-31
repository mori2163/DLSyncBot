"""
MusicDownloaderBot エントリーポイント
"""

import asyncio
import sys
from config import Config
from bot import get_bot
from file_server import get_file_server


async def start_bot() -> None:
    """Botとファイルサーバーを起動"""
    bot = get_bot()
    file_server = get_file_server()
    
    server_started = False
    # ファイルサーバーを起動
    if Config.FILE_SERVER_BASE_URL:
        try:
            await file_server.start()
            server_started = True
            print(f"ファイルサーバー起動: port {Config.FILE_SERVER_PORT}")
            print(f"外部URL: {Config.FILE_SERVER_BASE_URL}")
        except Exception as e:
            print(f"ファイルサーバーの起動に失敗しました: {e}")
    else:
        print("FILE_SERVER_BASE_URLが未設定のため、ファイルサーバーは起動しません")
        print("10MB以上のファイルはダウンロードリンクを生成できません")
    
    try:
        await bot.start(Config.DISCORD_TOKEN)
    finally:
        if server_started:
            await file_server.stop()
        
        # Botをクローズ（startを使用している場合は明示的にクローズが必要）
        if not bot.is_closed():
            await bot.close()


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
    print("Botを起動中...")
    
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        print("\n終了します...")
    except Exception as e:
        print(f"Bot起動エラー: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
