"""
アーカイブユーティリティ
フォルダのzip圧縮機能を提供する
"""

import asyncio
import logging
import shutil
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


async def create_zip_archive(
    source_folder: Path,
    output_path: Optional[Path] = None,
) -> tuple[Optional[Path], int]:
    """
    フォルダをzip圧縮する
    
    Args:
        source_folder: 圧縮対象のフォルダ
        output_path: 出力先パス（Noneの場合は同じディレクトリに作成）
        
    Returns:
        tuple: (zipファイルパス, ファイルサイズ) 失敗時は (None, 0)
    """
    if not source_folder.exists() or not source_folder.is_dir():
        logger.error(f"圧縮対象フォルダが存在しません: {source_folder}")
        return None, 0
    
    if output_path is None:
        output_path = source_folder.parent / f"{source_folder.name}.zip"
    
    def _create_zip() -> tuple[Optional[Path], int]:
        try:
            # 既存のzipファイルがあれば削除
            if output_path.exists():
                output_path.unlink()
            
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file_path in source_folder.rglob("*"):
                    if file_path.is_file():
                        arcname = file_path.relative_to(source_folder.parent)
                        zf.write(file_path, arcname)
            
            file_size = output_path.stat().st_size
            logger.info(f"zipアーカイブを作成しました: {output_path} ({file_size} bytes)")
            return output_path, file_size
        except Exception as e:
            logger.error(f"zip圧縮に失敗しました: {e}")
            if output_path.exists():
                output_path.unlink()
            return None, 0
    
    # ブロッキング処理を別スレッドで実行
    return await asyncio.to_thread(_create_zip)


def get_folder_size(folder: Path) -> int:
    """
    フォルダの合計サイズを取得する
    
    Args:
        folder: 対象フォルダ
        
    Returns:
        int: 合計サイズ（バイト）
    """
    total_size = 0
    try:
        for file_path in folder.rglob("*"):
            if file_path.is_file():
                total_size += file_path.stat().st_size
    except Exception as e:
        logger.error(f"フォルダサイズの取得に失敗しました: {e}")
    return total_size


def format_file_size(size_bytes: int) -> str:
    """
    ファイルサイズを人間が読みやすい形式にフォーマットする
    
    Args:
        size_bytes: バイト単位のサイズ
        
    Returns:
        str: フォーマットされたサイズ文字列
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
