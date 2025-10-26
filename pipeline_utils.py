# pipeline_utils.py
import os
import shutil
from pathlib import Path
from datetime import datetime

# グローバル定数 (元のコードの定義を維持)
LOG_DIR = Path('logs')
# ★★★ ここからが変更点 ★★★
# ログローテーションのため、タイムスタンプ付きのユニークなファイル名ではなく、
# 固定のログファイル名を使用します。
log_filename = LOG_DIR / 'orca_pipeline.log'
# ★★★ 変更点ここまで ★★★


def safe_write(path, content):
    """Safely writes content to a file, creating directories if necessary."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, 'w') as f:
            f.write(content)
        return True
    except IOError as e:
        # ロガーは他のモジュールに依存するため、ここでは簡略化
        print(f"ERROR: Could not write file {path}: {e}")
        return False


def get_unique_path(base_path):
    """Returns a unique, non-existent path by appending a number."""
    path = Path(base_path)
    if not path.exists():
        return path
    
    stem = path.stem
    suffix = path.suffix
    i = 1
    while True:
        new_path = path.with_name(f"{stem}_{i}{suffix}")
        if not new_path.exists():
            return new_path
        i += 1


def ensure_directory(path):
    """Ensures the directory exists."""
    Path(path).mkdir(parents=True, exist_ok=True)
