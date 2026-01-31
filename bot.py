"""
Discord Bot本体
スラッシュコマンドによるダウンロードリクエストを処理する
"""

import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import Config
from queue_manager import QueueManager, DownloadTask, TaskStatus
from url_parser import URLParser, ServiceType
from metadata_fetcher import MetadataFetcher, MediaMetadata
from archive_utils import create_zip_archive, format_file_size
from file_server import get_file_server


# サービス別の絵文字とカラー
SERVICE_ICONS = {
    ServiceType.QOBUZ: ("🎵", discord.Color.from_rgb(255, 102, 0)),    # Qobuzオレンジ
    ServiceType.YOUTUBE: ("▶️", discord.Color.from_rgb(255, 0, 0)),     # YouTube赤
    ServiceType.SPOTIFY: ("🎧", discord.Color.from_rgb(30, 215, 96)),   # Spotifyグリーン
}

# キュー追加メッセージの自動削除時間（秒）
QUEUE_MESSAGE_DELETE_DELAY = 10


class DownloadConfirmView(discord.ui.View):
    """ダウンロード確認用のボタンを含むView"""
    
    def __init__(
        self,
        metadata: MediaMetadata,
        bot_instance: "MusicDownloaderBot",
        timeout: float = 300.0,  # 5分でタイムアウト
    ):
        super().__init__(timeout=timeout)
        self.metadata = metadata
        self.bot_instance = bot_instance
        self.message: Optional[discord.Message] = None
    
    @discord.ui.button(
        label="ダウンロード",
        style=discord.ButtonStyle.success,
        emoji="⬇️",
    )
    async def download_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        """ダウンロードボタンが押されたときの処理"""
        # メッセージIDを取得して渡す（進捗更新用）
        message_id = self.message.id if self.message else None
        
        # キューに追加
        success, message, task = await self.bot_instance.queue_manager.add_task(
            url=self.metadata.url,
            requester_id=interaction.user.id,
            channel_id=interaction.channel_id or 0,
            message_id=message_id,
        )
        
        if success:
            icon, color = SERVICE_ICONS.get(
                self.metadata.service, ("🎵", discord.Color.blue())
            )
            
            # ephemeralメッセージでキュー追加を通知
            embed = discord.Embed(
                title=f"{icon} キューに追加しました",
                description=f"**{self.metadata.title}**\n{message}",
                color=color,
            )
            embed.set_footer(text=f"このメッセージは{QUEUE_MESSAGE_DELETE_DELAY}秒後に消えます")
            
            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
                delete_after=QUEUE_MESSAGE_DELETE_DELAY,
            )
            
            # 元のメッセージのボタンを無効化して状態を更新
            button.disabled = True
            button.label = "キューに追加済み"
            button.style = discord.ButtonStyle.secondary
            
            # キャンセルボタンも無効化
            for item in self.children:
                if isinstance(item, discord.ui.Button) and item.label == "キャンセル":
                    item.disabled = True
            
            # Embedを更新してダウンロード待機中であることを表示
            if self.message:
                original_embed = self.message.embeds[0] if self.message.embeds else None
                if original_embed:
                    original_embed.set_footer(text="⏳ ダウンロード待機中...")
                    await self.message.edit(embed=original_embed, view=self)
        else:
            embed = discord.Embed(
                title="❌ キュー追加失敗",
                description=message,
                color=discord.Color.red(),
            )
            await interaction.response.send_message(
                embed=embed,
                ephemeral=True,
                delete_after=QUEUE_MESSAGE_DELETE_DELAY,
            )
    
    @discord.ui.button(
        label="キャンセル",
        style=discord.ButtonStyle.secondary,
        emoji="✖️",
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ) -> None:
        """キャンセルボタンが押されたときの処理"""
        # 元のメッセージを削除
        if self.message:
            await self.message.delete()
        
        await interaction.response.send_message(
            "キャンセルしました",
            ephemeral=True,
            delete_after=5,
        )
    
    async def on_timeout(self) -> None:
        """タイムアウト時の処理"""
        if self.message:
            # ボタンを無効化
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
            
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass


class DownloadLinkView(discord.ui.View):
    """ダウンロードリンクボタンを含むView"""
    
    def __init__(self, download_url: str):
        super().__init__(timeout=None)  # タイムアウトなし
        
        # URLボタンを追加（外部リンク）
        self.add_item(
            discord.ui.Button(
                label="ダウンロード",
                style=discord.ButtonStyle.link,
                url=download_url,
                emoji="⬇️",
            )
        )


class MusicDownloaderBot(commands.Bot):
    """音楽ダウンロードBot"""
    
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        
        super().__init__(
            command_prefix="!",
            intents=intents,
        )
        
        self.queue_manager = QueueManager()
    
    async def setup_hook(self) -> None:
        """Bot起動時の初期化処理"""
        # コマンド登録
        self.tree.add_command(dl_command)
        self.tree.add_command(queue_command)
        
        # キューワーカーを開始
        self.queue_manager.set_progress_callback(self._on_task_progress)
        await self.queue_manager.start_worker()
        
        # コマンドを同期
        await self.tree.sync()
    
    async def on_ready(self) -> None:
        """Bot準備完了時"""
        print(f"ログイン完了: {self.user}")
        print(f"接続サーバー数: {len(self.guilds)}")
    
    async def _update_preview_message(
        self,
        task: DownloadTask,
        footer_text: str,
    ) -> None:
        """プレビューメッセージのフッターを更新"""
        if not task.message_id:
            return
        
        channel = self.get_channel(task.channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return
        
        try:
            message = await channel.fetch_message(task.message_id)
            if message.embeds:
                embed = message.embeds[0]
                embed.set_footer(text=footer_text)
                await message.edit(embed=embed, view=None)  # ボタンを削除
        except discord.NotFound:
            pass
        except discord.HTTPException:
            pass
    
    async def _on_task_progress(self, task: DownloadTask) -> None:
        """タスク進捗通知"""
        channel = self.get_channel(task.channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return
        
        user_mention = f"<@{task.requester_id}>"
        service_name = URLParser.get_service_name(task.service)
        icon, color = SERVICE_ICONS.get(task.service, ("🎵", discord.Color.blue()))
        
        if task.status == TaskStatus.RUNNING:
            # プレビューメッセージを更新
            await self._update_preview_message(
                task,
                f"🔄 ダウンロード中... (タスクID: {task.id[:8]})",
            )
            
            # 新しい通知メッセージは送信しない（プレビューメッセージで状態がわかるため）
        
        elif task.status == TaskStatus.COMPLETED:
            # プレビューメッセージを更新
            await self._update_preview_message(
                task,
                f"✅ ダウンロード完了! (タスクID: {task.id[:8]})",
            )
            
            # 完了通知を送信
            embed = discord.Embed(
                title=f"{icon} ダウンロード完了!",
                color=color,
                timestamp=datetime.now(),
            )
            
            # アルバム/フォルダ名を表示
            folder_name = None
            if task.result and task.result.folder_path:
                # 接頭辞を除去して表示
                folder_name = task.result.folder_path.name
                for prefix in [Config.YOUTUBE_PREFIX, Config.SPOTIFY_PREFIX]:
                    if folder_name.startswith(prefix):
                        folder_name = folder_name[len(prefix):]
                        break
                embed.add_field(
                    name="📁 アルバム",
                    value=f"`{folder_name}`",
                    inline=False,
                )
            
            # 詳細情報
            details = []
            if task.result and task.result.file_count > 0:
                details.append(f"🎵 **{task.result.file_count}** 曲")
            details.append(f"📀 **{service_name}**")
            
            if details:
                embed.add_field(
                    name="詳細",
                    value=" │ ".join(details),
                    inline=False,
                )
            
            embed.set_footer(text=f"タスクID: {task.id[:8]}")
            
            # ダウンロードファイルの準備
            file_attachment = None
            download_view = None
            zip_to_cleanup: Optional[Path] = None
            
            try:
                if task.result and task.result.folder_path and task.result.folder_path.exists():
                    # zipアーカイブを作成
                    zip_path, zip_size = await create_zip_archive(task.result.folder_path)
                    
                    if zip_path and zip_size > 0:
                        size_str = format_file_size(zip_size)
                        
                        # 一旦クリーンアップ対象にする
                        zip_to_cleanup = zip_path
                        
                        if zip_size < Config.DOWNLOAD_SIZE_THRESHOLD:
                            # 10MB以下: Discordに直接添付
                            try:
                                file_attachment = discord.File(
                                    zip_path,
                                    filename=f"{folder_name or 'download'}.zip",
                                )
                                embed.add_field(
                                    name="📦 ダウンロード",
                                    value=f"ファイルサイズ: {size_str}",
                                    inline=False,
                                )
                            except Exception as e:
                                embed.add_field(
                                    name="⚠️ 添付エラー",
                                    value=f"ファイルの添付準備に失敗しました: {e}",
                                    inline=False,
                                )
                        else:
                            # 10MB以上: ダウンロードリンクを生成
                            try:
                                file_server = get_file_server()
                                if Config.FILE_SERVER_BASE_URL:
                                    download_url, token = file_server.create_download_link(
                                        file_path=zip_path,
                                        file_name=f"{folder_name or 'download'}.zip",
                                    )
                                    
                                    # ファイルサーバーに正常に登録された場合は、今すぐ削除しない
                                    zip_to_cleanup = None
                                    
                                    embed.add_field(
                                        name="📦 ダウンロード",
                                        value=(
                                            f"ファイルサイズ: {size_str}\n"
                                            f"残り回数: **{token.remaining_downloads}回**\n"
                                            f"有効期限: {Config.DOWNLOAD_LINK_EXPIRE_HOURS}時間"
                                        ),
                                        inline=False,
                                    )
                                    
                                    # ダウンロードボタン付きView
                                    download_view = DownloadLinkView(download_url)
                                else:
                                    embed.add_field(
                                        name="⚠️ ダウンロードリンク",
                                        value=(
                                            f"ファイルサイズ: {size_str}\n"
                                            "サーバー設定がないためリンクを生成できません"
                                        ),
                                        inline=False,
                                    )
                            except Exception as e:
                                embed.add_field(
                                    name="⚠️ リンク生成エラー",
                                    value=f"ダウンロードリンクの生成に失敗しました: {e}",
                                    inline=False,
                                )
                
                # メッセージを送信
                send_kwargs = {
                    "content": user_mention,
                    "embed": embed,
                }
                if file_attachment:
                    send_kwargs["file"] = file_attachment
                if download_view:
                    send_kwargs["view"] = download_view
                
                await channel.send(**send_kwargs)
            except Exception as e:
                # 送信エラー時の処理。ログに残しつつ、フォールバック通知を試みる
                print(f"通知送信エラー: {e}")
                try:
                    # 簡潔なメッセージで再試行
                    await channel.send(f"{user_mention} 通知の送信に失敗しましたが、ダウンロードは完了しています。")
                except Exception:
                    # チャンネル送信が壊滅的な場合はDMを試みる
                    try:
                        user = self.get_user(task.requester_id) or await self.fetch_user(task.requester_id)
                        if user:
                            await user.send(f"通知の送信に失敗しましたが、ダウンロードは完了しました。タスクID: {task.id[:8]}")
                    except Exception as dm_e:
                        print(f"DM送信失敗: {dm_e}")
            finally:
                # 添付ファイルを閉じて一時ファイルを削除
                if file_attachment:
                    file_attachment.close()
                if zip_to_cleanup and zip_to_cleanup.exists():
                    zip_to_cleanup.unlink()
        
        elif task.status == TaskStatus.FAILED:
            # プレビューメッセージを更新
            await self._update_preview_message(
                task,
                f"❌ ダウンロード失敗 (タスクID: {task.id[:8]})",
            )
            
            # エラー通知を送信
            embed = discord.Embed(
                title="❌ ダウンロード失敗",
                description=task.result.message if task.result else "不明なエラー",
                color=discord.Color.red(),
                timestamp=datetime.now(),
            )
            embed.add_field(name="📀 サービス", value=service_name, inline=True)
            
            if task.result and task.result.error:
                # エラーメッセージが長すぎる場合は切り詰め
                error_text = task.result.error[:400]
                if len(task.result.error) > 400:
                    error_text += "..."
                embed.add_field(
                    name="⚠️ エラー詳細",
                    value=f"```\n{error_text}\n```",
                    inline=False,
                )
            embed.set_footer(text=f"タスクID: {task.id[:8]}")
            await channel.send(content=user_mention, embed=embed)


# Botインスタンス（コマンドから参照するため）
bot: Optional[MusicDownloaderBot] = None


def get_bot() -> MusicDownloaderBot:
    """Botインスタンスを取得"""
    global bot
    if bot is None:
        bot = MusicDownloaderBot()
    return bot


# スラッシュコマンド定義
@app_commands.command(name="dl", description="URLから音楽をダウンロードする")
@app_commands.describe(url="ダウンロード対象のURL（Qobuz、YouTube、Spotify）")
async def dl_command(interaction: discord.Interaction, url: str) -> None:
    """ダウンロードコマンド"""
    bot_instance = get_bot()
    
    # URL検証
    service = URLParser.detect_service(url)
    if service == ServiceType.UNKNOWN:
        embed = discord.Embed(
            title="❌ 非対応のURL",
            description="Qobuz、YouTube、Spotifyのリンクを指定してください。",
            color=discord.Color.red(),
        )
        embed.add_field(
            name="対応サービス",
            value="🎵 Qobuz\n▶️ YouTube\n🎧 Spotify",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # インタラクションを保留（3秒ルール回避）
    await interaction.response.defer()
    
    # メタデータ取得中のメッセージを表示
    icon, color = SERVICE_ICONS.get(service, ("🎵", discord.Color.blue()))
    service_name = URLParser.get_service_name(service)
    
    loading_embed = discord.Embed(
        title=f"{icon} メタデータ取得中...",
        description=f"**{service_name}** から情報を取得しています",
        color=color,
    )
    await interaction.edit_original_response(embed=loading_embed)
    
    # メタデータを取得
    metadata = await MetadataFetcher.fetch(url)
    
    if metadata is None:
        # メタデータ取得失敗時はフォールバック
        metadata = MediaMetadata(
            title=f"{service_name} コンテンツ",
            artist="不明",
            service=service,
            url=url,
        )
    
    # プレビュー用Embedを作成
    embed = discord.Embed(
        title=f"{icon} {metadata.title}",
        description=f"**{metadata.artist}**",
        color=color,
        timestamp=datetime.now(),
    )
    
    # サムネイルがあれば設定
    if metadata.thumbnail_url:
        embed.set_thumbnail(url=metadata.thumbnail_url)
    
    # 詳細情報を追加
    info_parts = [f"📀 **{service_name}**"]
    if metadata.duration:
        minutes, seconds = divmod(metadata.duration, 60)
        info_parts.append(f"⏱️ {minutes}:{seconds:02d}")
    if metadata.track_count and metadata.track_count > 1:
        info_parts.append(f"🎵 {metadata.track_count}曲")
    if metadata.album:
        info_parts.append(f"💿 {metadata.album}")
    
    embed.add_field(name="詳細", value=" │ ".join(info_parts), inline=False)
    embed.add_field(name="🔗 URL", value=f"[リンク]({url})", inline=False)
    embed.set_footer(text="ダウンロードボタンを押してキューに追加")
    
    # ボタン付きViewを作成
    view = DownloadConfirmView(metadata, bot_instance)
    
    # メッセージを更新
    message = await interaction.edit_original_response(embed=embed, view=view)
    view.message = message


@app_commands.command(name="queue", description="ダウンロードキューの状態を表示")
async def queue_command(interaction: discord.Interaction) -> None:
    """キュー状態表示コマンド"""
    bot_instance = get_bot()
    pending, current = bot_instance.queue_manager.get_queue_info()
    
    embed = discord.Embed(
        title="📋 ダウンロードキュー",
        color=discord.Color.blue(),
        timestamp=datetime.now(),
    )
    
    # 現在実行中
    if current:
        service_name = URLParser.get_service_name(current.service)
        icon, _ = SERVICE_ICONS.get(current.service, ("🎵", discord.Color.blue()))
        embed.add_field(
            name="▶️ 実行中",
            value=f"{icon} {service_name}\n`{current.url[:50]}...`" if len(current.url) > 50 else f"{icon} {service_name}\n`{current.url}`",
            inline=False,
        )
    else:
        embed.add_field(name="▶️ 実行中", value="なし", inline=False)
    
    # 待機中
    if pending:
        queue_text = ""
        for i, task in enumerate(pending[:5], 1):
            service_name = URLParser.get_service_name(task.service)
            icon, _ = SERVICE_ICONS.get(task.service, ("🎵", discord.Color.blue()))
            queue_text += f"{i}. {icon} {service_name}\n"
        if len(pending) > 5:
            queue_text += f"... 他 {len(pending) - 5} 件"
        embed.add_field(name=f"⏳ 待機中 ({len(pending)}件)", value=queue_text, inline=False)
    else:
        embed.add_field(name="⏳ 待機中", value="なし", inline=False)
    
    await interaction.response.send_message(embed=embed)
