# DLSyncBot

Discord Botを通じて **Qobuz**、**YouTube**、**Spotify** から音楽をダウンロードし、メタデータとジャケット画像を付与した上で、**Navidrome** で配信可能な状態にする多機能ダウンロードBot。

## 概要

このBotは以下の機能を提供します：

-  **複数サービス対応**: Qobuz (FLAC)、YouTube、Spotify のダウンロードに対応（Spotifyはyoutubeからの音源取得を利用）
-  **キュー管理**: 複数リクエストを順番に処理
-  **メタデータ自動埋め込み**: ID3タグ、ジャケット画像の自動管理
-  **Navidrome連携**: ダウンロード後、自動的にライブラリフォルダに配置
-  **堅牢なエラー処理**: Qobuzダウンロード失敗時は自動リトライ
-  **進捗通知**: Discord上でダウンロード状況をリアルタイム通知

## 主な特徴

### 音源の差別化
- **Qobuz**: 高品質音源（FLAC）として、フォルダ名接頭辞なし
- **YouTube**: `[YT]` 接頭辞付きで識別
- **Spotify**: `[SP]` 接頭辞付きで識別

### エラー対策
- **Qobuzの堅牢性**: ダウンロード失敗時は最大3回まで自動リトライ
- **非同期処理**: Botの応答性を損なわないバックグラウンド処理
- **詳細なエラー通知**: 失敗時はエラー内容をDiscordに報告

## 必要要件

- Python 3.11 以上
- Discord Bot トークン
- Qobuz アカウント（Qobuzを使用する場合）
- 外部ツール：
  - `ffmpeg`（音源の変換、結合、メタデータ埋め込みに使用）
  - `Node.js`（YouTubeの取得で `yt-dlp --js-runtimes node` を使うため必要）
  - ※ `qobuz-dl`, `yt-dlp`, `spotdl` は Python の依存関係として自動インストールされます

## インストール

### 1. リポジトリをクローン

```bash
git clone <repository-url>
cd MusicDownloaderBot
```

### 2. 環境構築（uv を使用）

[uv](https://docs.astral.sh/uv/) は高速なPythonパッケージマネージャーです。以下でインストールできます：

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

仮想環境を作成して依存関係をインストール：

```bash
# 仮想環境作成と依存関係インストール
uv sync

# または明示的にPythonバージョンを指定
uv sync --python 3.11
```

### 3. 環境変数の設定

`.env.example` をコピーして `.env` を作成：

```bash
cp .env.example .env
```

`.env` ファイルを編集して、以下の情報を設定：

```env
# Discord Bot トークン（必須）
DISCORD_TOKEN=your_discord_bot_token_here

# Qobuz認証情報
QOBUZ_EMAIL=your_email@example.com
QOBUZ_PASSWORD=your_password_here

# ライブラリパス（Navidromeの監視フォルダを指定）
LIBRARY_PATH=C:/path/to/your/navidrome/music/library

# ダウンロード先（一時保存場所、デフォルト: ./downloads）
DOWNLOAD_PATH=./downloads

# その他の設定
MAX_RETRIES=3
QUEUE_MAX_SIZE=100
```

### Discord Bot トークンの取得方法

1. [Discord Developer Portal](https://discord.com/developers/applications) にアクセス
2. 「New Application」から新しいアプリケーションを作成
3. 「Bot」タブから「Add Bot」をクリック
4. 「TOKEN」セクションから「Copy」でトークンをコピー
5. `.env` ファイルの `DISCORD_TOKEN` に貼り付け

## 使用方法

### Bot の起動

```bash
# uvの仮想環境内で実行
uv run python main.py
```

または：

```bash
# 仮想環境をアクティベート
source .venv/bin/activate  # Linux/macOS
# または
.venv\Scripts\activate  # Windows

python main.py
```

### 常駐実行（PM2 を使用する場合）

サーバーなどで永続的に実行したい場合は、[PM2](https://pm2.keymetrics.io/) を使用できます。

```bash
# 起動
pm2 start ecosystem.config.js

# ステータス確認
pm2 status

# ログ確認
pm2 logs music-downloader-bot
```

### Discord コマンド

Bot が起動したら、Discordサーバーで以下のコマンドが使用可能：

#### `/dl <url>`
URLから音楽をダウンロード

**使用例:**
```
/dl https://open.qobuz.com/album/123456
/dl https://www.youtube.com/watch?v=dQw4w9WgXcQ
/dl https://open.spotify.com/track/123456
```

**対応URL:**
- Qobuz: `https://open.qobuz.com/` または `https://play.qobuz.com/`
- YouTube: `https://www.youtube.com/watch?v=...` または `https://youtu.be/...`
- Spotify: `https://open.spotify.com/` (トラック、アルバム、プレイリスト対応)

#### `/queue`
現在のキュー状態を表示

**表示内容:**
- 実行中のタスク
- 待機中のタスク数

## ファイル構成

```
MusicDownloaderBot/
├── main.py              # エントリーポイント
├── bot.py               # Discord Bot本体
├── config.py            # 設定管理
├── url_parser.py        # URL判別ロジック
├── queue_manager.py     # ダウンロードキュー管理
├── metadata_fetcher.py  # メタデータ取得・加工ロジック
├── downloaders/
│   ├── __init__.py
│   ├── base.py          # ダウンローダー基底クラス
│   ├── qobuz.py         # Qobuzダウンローダー
│   ├── youtube.py       # YouTubeダウンローダー
│   └── spotify.py       # Spotifyダウンローダー
├── ecosystem.config.js  # PM2用プロセス管理設定
├── pyproject.toml       # プロジェクト設定（uv対応）
├── requirements.txt     # 依存ライブラリ一覧
├── README.md            # このファイル
└── .env.example         # 環境変数テンプレート
```

## 動作フロー

1. **リクエスト受付**: ユーザーが `/dl <url>` でURLを送信
2. **URL判別**: Qobuz/YouTube/Spotify を自動識別
3. **キュー登録**: 複数リクエストは順番に処理
4. **ダウンロード実行**:
   - **Qobuz**: FLAC最高音質、失敗時3回リトライ
   - **YouTube**: Opus形式、最高品質
   - **Spotify**: Opus形式（SpotifyはYouTubeからの音源取得を利用）
5. **メタデータ処理**: ジャケット画像やID3タグを自動埋め込み
6. **ライブラリ配置**: Navidromeの監視フォルダに自動移動
7. **通知**: 完了/失敗をDiscordに通知

## 設定項目の詳細

| 項目 | デフォルト | 説明 |
|------|----------|------|
| `DISCORD_TOKEN` | - | Discord Bot トークン（必須） |
| `QOBUZ_EMAIL` | - | Qobuz ログインメール |
| `QOBUZ_PASSWORD` | - | Qobuz パスワード |
| `DOWNLOAD_PATH` | `./downloads` | 一時ダウンロードフォルダ |
| `LIBRARY_PATH` | `./library` | 最終配置先（Navidromeライブラリ） |
| `MAX_RETRIES` | `3` | Qobuzダウンロードの最大リトライ回数 |
| `QUEUE_MAX_SIZE` | `100` | キュー内の最大タスク数 |

## トラブルシューティング

### Bot が起動しない

**エラー: `DISCORD_TOKEN が設定されていない`**
- `.env` ファイルが存在し、`DISCORD_TOKEN` が正しく設定されているか確認してください

**エラー: `Qobuz認証情報が不完全`**
- Qobuzを使用する場合、`QOBUZ_EMAIL` と `QOBUZ_PASSWORD` を設定してください

### ダウンロードが失敗する

**YouTube:**
- `yt-dlp` が最新版にアップデートされているか確認: `uv pip install --upgrade yt-dlp`
- URLが正しいか確認
- `node` がインストール済みで PATH が通っているか確認: `node --version`

**Spotify:**
- `spotdl` が最新版か確認: `uv pip install --upgrade spotdl`
- Spotifyアカウント情報が正しいか確認

**Qobuz:**
- アカウント情報（メール/パスワード）が正しいか確認
- 曲が配信停止されていないか確認

### ファイルがLibraryに移動されない

- `LIBRARY_PATH` が正しく設定されているか確認
- フォルダのアクセス権限があるか確認
- ディスク容量が充分か確認

## 開発

### 開発用の依存関係をインストール

```bash
uv sync --all-extras
```

### コード整形・Lint

```bash
# Black で整形
uv run black .

# isort で import をソート
uv run isort .

# flake8 で Lint
uv run flake8 .
```

## ライセンス

MIT License

## 免責事項

本ツールは学習および研究目的で作成されています。

- **利用規約の遵守**: 各配信サービス（Qobuz, YouTube, Spotify等）の利用規約に従って使用してください。本ツールの使用によって生じたアカウントの停止、制限等について、制作者は一切の責任を負いません。
- **著作権について**: 本ツールを使用してダウンロードしたコンテンツは、個人利用の範囲に留めてください。著作権法に抵触するような利用（無断転載、再配布等）は固く禁じられています。
- **Navidrome**: Navidromeは[AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.html)ライセンスです。

## サポート

問題が発生した場合は、以下を確認してください：

1. `.env` ファイルに正しい情報（トークン、パスワード等）が設定されているか
2. `ffmpeg` がシステムにインストールされ、パスが通っているか
3. ネットワーク接続に問題がないか
4. DiscordサーバーでBotに適切な権限（スラッシュコマンドの利用等）が与えられているか
5. Qobuzをご利用の場合は、アカウントが有効なサブスクリプションを持っているか

