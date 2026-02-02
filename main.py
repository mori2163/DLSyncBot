"""
MusicDownloaderBot エントリーポイント
"""

import asyncio
import logging
import sys
from config import Config
from bot import get_bot
from file_server import get_file_server
from tunnel_manager import get_tunnel_manager

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
    tunnel_manager = get_tunnel_manager()
    
    server_started = False
    tunnel_started = False
    base_url = Config.FILE_SERVER_BASE_URL
    
    # Cloudflare Tunnelが有効な場合
    if Config.CLOUDFLARE_TUNNEL_ENABLED:
        # ファイルサーバーを先に起動
        try:
            await file_server.start()
            server_started = True
            logger.info(f"ファイルサーバー起動: port {Config.FILE_SERVER_PORT}")
        except Exception as e:
            logger.error(f"ファイルサーバーの起動に失敗しました: {e}")
        
        if server_started:
            # トンネルを開始
            try:
                if Config.CLOUDFLARE_TUNNEL_MODE == "named":
                    success = await tunnel_manager.start_named_tunnel()
                    if success:
                        tunnel_started = True
                        logger.info("Named Tunnelを開始しました")
                    else:
                        logger.error(
                            "Named Tunnelの開始に失敗しました: "
                            f"success={success}"
                        )
                        await file_server.stop()
                        server_started = False
                else:
                    public_url = await tunnel_manager.start_quick_tunnel()
                    if public_url:
                        tunnel_started = True
                        base_url = public_url
                        Config.FILE_SERVER_BASE_URL = base_url

                        logger.info(f"Quick Tunnel公開URL: {public_url}")
                    else:
                        logger.error(
                            "Quick Tunnelの開始に失敗しました: "
                            f"public_url={public_url}"
                        )
                        await file_server.stop()
                        server_started = False
            except Exception as e:
                logger.error(f"トンネルの開始に失敗しました: {e}")
                if server_started:
                    try:
                        await file_server.stop()
                    except Exception as stop_error:
                        logger.error(f"ファイルサーバー停止中にエラー: {stop_error}")
                    server_started = False
    
    # トンネルなしの場合（従来の動作）
    elif Config.FILE_SERVER_BASE_URL:
        try:
            await file_server.start()
            server_started = True
            logger.info(f"ファイルサーバー起動: port {Config.FILE_SERVER_PORT}")
            logger.info(f"外部URL: {Config.FILE_SERVER_BASE_URL}")
        except Exception as e:
            logger.error(f"ファイルサーバーの起動に失敗しました: {e}")
    else:
        logger.warning("FILE_SERVER_BASE_URLが未設定かつトンネルも無効のため、ファイルサーバーは起動しません")
        logger.warning("10MB以上のファイルはダウンロードリンクを生成できません")
    
    try:
        await bot.start(Config.DISCORD_TOKEN)
    finally:
        # トンネルのクリーンアップ
        if tunnel_started:
            try:
                await tunnel_manager.stop()
            except Exception as e:
                logger.error(f"トンネルの停止中にエラーが発生しました: {e}")
        
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
