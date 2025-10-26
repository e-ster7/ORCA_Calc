# logging_utils.py
import logging
import sys
# 依存関係: pipeline_utilsから定数をインポート
from pipeline_utils import LOG_DIR, log_filename

# グローバルなロギング設定（モジュールインポート時に実行）
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler(sys.stdout)
    ]
)


def get_logger(name):
    """Get a logger with the specified name"""
    return logging.getLogger(name)


def set_log_level(level):
    """Set global log level"""
    logging.getLogger().setLevel(level)
