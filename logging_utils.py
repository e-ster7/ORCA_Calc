# logging_utils.py
import logging
import sys
# ★★★ ここからが変更点 ★★★
# logging.FileHandler の代わりに TimedRotatingFileHandler をインポート
from logging.handlers import TimedRotatingFileHandler
# ★★★ 変更点ここまで ★★★

# 依存関係: pipeline_utilsから定数をインポート
from pipeline_utils import LOG_DIR, log_filename

# グローバルなロギング設定（モジュールインポート時に実行）
LOG_DIR.mkdir(exist_ok=True)

# ★★★ ここからが変更点 ★★★
# logging.FileHandler を TimedRotatingFileHandler に置き換えます。
# (仕様書3.1.2に基づく変更)
rotating_handler = TimedRotatingFileHandler(
    log_filename, 
    when='D',           # 'D' = 毎日 (Daily)
    interval=1,         # 1日ごと
    backupCount=7,      # 7世代分のバックアップを保持
    encoding='utf-8'    # エンコーディング指定
)
# ★★★ 変更点ここまで ★★★

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        # ★★★ 変更点 ★★★
        rotating_handler, # FileHandler の代わりにローテーションハンドラを使用
        logging.StreamHandler(sys.stdout)
    ]
)


def get_logger(name):
    """Get a logger with the specified name"""
    return logging.getLogger(name)


def set_log_level(level):
    """Set global log level"""
    logging.getLogger().setLevel(level)
