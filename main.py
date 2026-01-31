"""
MusicDownloaderBot エントリーポイント
"""

import asyncio
import logging
import sys
from config import Config
from bot import get_bot
from file_server import get_file_server

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


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
            logger.info(f"ファイルサーバー起動: port {Config.FILE_SERVER_PORT}")
            logger.info(f"外部URL: {Config.FILE_SERVER_BASE_URL}")
        except Exception as e:
            logger.error(f"ファイルサーバーの起動に失敗しました: {e}")
    else:
        logger.warning("FILE_SERVER_BASE_URLが未設定のため、ファイルサーバーは起動しません")
        logger.warning("10MB以上のファイルはダウンロードリンクを生成できません")
    
    try:
        await bot.start(Config.DISCORD_TOKEN)
    finally:
        # ファイルサーバーのクリーンアップ
        if server_started:
            try:
                await file_server.stop()
            except Exception as e:
                logger.error(f"ファイルサーバーの停止中にエラーが発生しました: {e}")
        
        # Botのクリーンアップ
        try:
            if not bot.is_closed():
                await bot.close()
        except Exception as e:
            logger.error(f"Botのクローズ中にエラーが発生しました: {e}")


def main() -> int:
    """メイン関数"""
    logger.info("=== MusicDownloaderBot 起動 ===")
    
    # 設定検証
    errors = Config.validate()
    if errors:
        logger.error("設定エラー:")
        for error in errors:
            logger.error(f"  - {error}")
        logger.error(".envファイルを確認してください。")
        return 1
    
    # ディレクトリ作成
    Config.ensure_directories()
    logger.info(f"ダウンロード先: {Config.DOWNLOAD_PATH}")
    logger.info(f"ライブラリ: {Config.LIBRARY_PATH}")
    
    # Bot起動
    logger.info("Botを起動中...")
    
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        logger.info("終了します...")
    except Exception as e:
        logger.exception(f"Bot起動エラー: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
