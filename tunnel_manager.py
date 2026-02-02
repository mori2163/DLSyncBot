"""
Cloudflare Tunnel管理モジュール
ローカルサービスをCloudflare経由で公開する
"""

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TunnelManager:
    """Cloudflare Tunnel管理クラス"""

    def __init__(
        self,
        local_port: int,
        tunnel_name: Optional[str] = None,
        config_path: Optional[Path] = None,
        cloudflared_path: Optional[str] = None,
    ):
        """
        Args:
            local_port: トンネルで公開するローカルポート
            tunnel_name: 既存トンネル名（named tunnel使用時）
            config_path: cloudflared設定ファイルのパス
            cloudflared_path: cloudflaredの実行ファイルパス
        """
        self.local_port = local_port
        self.tunnel_name = tunnel_name
        self.config_path = config_path
        self.cloudflared_path = cloudflared_path or self._find_cloudflared()

        self._process: Optional[asyncio.subprocess.Process] = None
        self._public_url: Optional[str] = None
        self._output_task: Optional[asyncio.Task] = None

    def _find_cloudflared(self) -> str:
        """cloudflaredの実行ファイルを探す"""
        # PATHから探す
        found = shutil.which("cloudflared")
        if found:
            return found

        # Windowsのデフォルトインストール場所
        default_paths = [
            Path.home() / ".cloudflared" / "cloudflared.exe",
            Path("C:/Program Files/cloudflared/cloudflared.exe"),
            Path("C:/Program Files (x86)/cloudflared/cloudflared.exe"),
        ]

        for path in default_paths:
            if path.exists():
                return str(path)

        return "cloudflared"  # フォールバック

    @property
    def is_running(self) -> bool:
        """トンネルが稼働中かどうか"""
        return self._process is not None and self._process.returncode is None

    @property
    def public_url(self) -> Optional[str]:
        """公開URL（Quick Tunnel使用時に自動取得）"""
        return self._public_url

    async def _read_output(self) -> None:
        """cloudflaredの出力を読み取り、公開URLを抽出"""
        if not self._process or not self._process.stderr:
            return

        url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break

                decoded = line.decode("utf-8", errors="replace").strip()
                if decoded:
                    logger.debug(f"[cloudflared] {decoded}")

                    # Quick TunnelのURLを抽出
                    match = url_pattern.search(decoded)
                    if match and not self._public_url:
                        self._public_url = match.group(0)
                        logger.info(f"Tunnel公開URL: {self._public_url}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"cloudflared出力の読み取りエラー: {e}")

    async def start_quick_tunnel(self) -> Optional[str]:
        """
        Quick Tunnel（一時的なトンネル）を開始
        認証不要で即座に使用可能だが、URLは毎回変わる

        Returns:
            公開URL（取得できない場合はNone）
        """
        if self.is_running:
            logger.warning("トンネルは既に稼働中です")
            return self._public_url

        cmd = [
            self.cloudflared_path,
            "tunnel",
            "--url",
            f"http://localhost:{self.local_port}",
        ]

        logger.info(f"Quick Tunnelを開始: {' '.join(cmd)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # 出力読み取りタスクを開始
            self._output_task = asyncio.create_task(self._read_output())

            # URLが取得できるまで最大30秒待機
            for _ in range(60):
                if self._public_url:
                    return self._public_url
                if self._process.returncode is not None:
                    logger.error("cloudflaredが予期せず終了しました")
                    try:
                        await self.stop()
                    except Exception as stop_error:
                        logger.error(f"トンネル停止中にエラーが発生しました: {stop_error}")
                    return None
                await asyncio.sleep(0.5)

            logger.warning("公開URLの取得がタイムアウトしました")
            try:
                await self.stop()
            except Exception as stop_error:
                logger.error(f"トンネル停止中にエラーが発生しました: {stop_error}")
            return None

        except FileNotFoundError:
            logger.error(
                f"cloudflaredが見つかりません: {self.cloudflared_path}\n"
                "インストール: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
            )
            return None
        except Exception as e:
            logger.error(f"トンネル開始エラー: {e}")
            return None

    async def start_named_tunnel(self) -> bool:
        """
        Named Tunnel（永続的なトンネル）を開始
        事前に `cloudflared tunnel login` と `cloudflared tunnel create` が必要

        Returns:
            成功したかどうか
        """
        if self.is_running:
            logger.warning("トンネルは既に稼働中です")
            return True

        if not self.tunnel_name and not self.config_path:
            logger.error("tunnel_nameまたはconfig_pathが必要です")
            return False

        cmd = [self.cloudflared_path, "tunnel"]

        if self.config_path:
            cmd.extend(["--config", str(self.config_path)])

        cmd.append("run")

        if self.tunnel_name:
            cmd.append(self.tunnel_name)

        logger.info(f"Named Tunnelを開始: {' '.join(cmd)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            self._output_task = asyncio.create_task(self._read_output())

            # プロセスが起動したか確認
            await asyncio.sleep(2)
            if self._process.returncode is not None:
                logger.error("cloudflaredが予期せず終了しました")
                if self._process.returncode is not None:
                    logger.error("cloudflaredが予期せず終了しました")
                    try:
                        await self.stop()
                    except Exception as stop_error:
                        logger.error(f"トンネル停止中にエラーが発生しました: {stop_error}")
                    return False
            logger.info("Named Tunnelを開始しました")
            return True

        except FileNotFoundError:
            logger.error(f"cloudflaredが見つかりません: {self.cloudflared_path}")
            return False
        except Exception as e:
            logger.error(f"トンネル開始エラー: {e}")
            return False
    async def stop(self) -> None:
        """トンネルを停止"""
        if self._output_task:
            self._output_task.cancel()
            try:
                await self._output_task
            except asyncio.CancelledError:
                pass
            self._output_task = None

        if self._process:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            self._process = None

        self._public_url = None
        logger.info("トンネルを停止しました")


# グローバルインスタンス
_tunnel_manager: Optional[TunnelManager] = None


def get_tunnel_manager(local_port: Optional[int] = None) -> TunnelManager:
    """TunnelManagerインスタンスを取得"""
    global _tunnel_manager
    if _tunnel_manager is None:
        from config import Config

        _tunnel_manager = TunnelManager(
            local_port=local_port or Config.FILE_SERVER_PORT,
            tunnel_name=Config.CLOUDFLARE_TUNNEL_NAME or None,
            config_path=Path(Config.CLOUDFLARE_CONFIG_PATH)
            if Config.CLOUDFLARE_CONFIG_PATH
            else None,
            cloudflared_path=Config.CLOUDFLARED_PATH or None,
        )
    elif local_port is not None and _tunnel_manager.local_port != local_port:
        logger.warning(
            "既存のTunnelManagerを再利用します。"
            f"渡されたlocal_port={local_port}は無視され、"
            f"既存のlocal_port={_tunnel_manager.local_port}が使用されます。"
        )
    return _tunnel_manager
