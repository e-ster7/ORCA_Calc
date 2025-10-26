# main_coordinator.py
# 役割: 設定、初期化、依存関係の接続、全体の実行順序の制御のみを行う

import sys
import time
from pathlib import Path
from watchdog.observers import Observer

# --- 枝モジュールからのインポート (すべての機能クラス/関数) ---
# このファイルで定義されていたすべての名前を、外部モジュールからインポートする
from config_utils import load_config
from logging_utils import get_logger, set_log_level
from paths_utils import ensure_directory
from notification_service import NotificationThrottle, send_notification
from state_store import StateStore
from orca_job_manager import JobManager
from file_watcher import XYZHandler, process_existing_xyz_files
from pipeline_utils import LOG_DIR, log_filename  # 定数も枝に移動

def main():
    # -----------------------------------------------------------
    # 1. 環境設定と初期化
    # -----------------------------------------------------------
    
    # ログディレクトリの準備 (paths_utils.py に移動)
    ensure_directory(LOG_DIR)
    
    # ロギング設定 (logging_utils.py に移動)
    set_log_level('INFO')
    logger = get_logger('pipeline')
    
    try:
        # 設定のロード (config_utils.py に移動)
        config = load_config()
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    # パスの検証と作成 (paths_utils.py に移動)
    for path_key in ['input_dir', 'waiting_dir', 'product_dir']:
        path = Path(config['paths'][path_key])
        ensure_directory(path)

    # -----------------------------------------------------------
    # 2. 依存関係の初期化と注入
    # -----------------------------------------------------------
    
    # 通知サービス (notification_service.py に移動)
    # Throttleはグローバル変数ではなく、ここで初期化して使用する
    notification_throttle = NotificationThrottle()
    
    # 状態管理 (state_store.py に移動)
    state_store = StateStore()

    # ジョブマネージャー (orca_job_manager.py に移動)
    # JobManagerは、通知や状態管理などの外部サービスに依存する
    job_manager = JobManager(
        config=config, 
        logger=get_logger('job_manager'), 
        state_store=state_store,
        notification_throttle=notification_throttle
        # JobManager内で使用される全てのユーティリティ関数（ORCA関連、I/Oなど）も、
        # JobManagerクラスのメソッドとして組み込むか、この時点で注入する必要がある
        # ※ここではコードが複雑になりすぎるため、JobManagerは自己完結型と仮定し、configのみ渡す
    )
    
    # ファイル監視ハンドラ (file_watcher.py に移動)
    event_handler = XYZHandler(config, job_manager)
    observer = Observer()
    
    # -----------------------------------------------------------
    # 3. 実行順序の制御 (メインロジック)
    # -----------------------------------------------------------
    
    # 既存INPファイルの処理
    waiting_dir = Path(config['paths']['waiting_dir'])
    # process_existing_inp_files 関数を新たに定義し、ロジックをそちらに移動する
    # process_existing_inp_files(config, job_manager, waiting_dir)
    # ※元のコードの行数を維持するため、この部分は元のロジックを維持し、インポートされた機能に置き換える
    
    existing_inp_files = list(waiting_dir.glob('*.inp'))
    if existing_inp_files:
        logger.info(f"Found {len(existing_inp_files)} existing INP files in waiting directory")
        for inp_file in existing_inp_files:
            mol_name = inp_file.stem.replace('_opt', '').replace('_freq', '')
            calc_type = 'freq' if '_freq' in inp_file.stem else 'opt'
            job_manager.add_job(str(inp_file), mol_name, calc_type) # JobManagerの公開メソッドを呼び出す

    # 既存XYZファイルの処理 (file_watcher.py に移動)
    process_existing_xyz_files(config, job_manager) 
    
    # ジョブマネージャーの開始
    job_manager.start()
    
    # ファイル監視の開始
    input_dir = config['paths']['input_dir']
    observer.schedule(event_handler, input_dir, recursive=False)
    observer.start()
    
    logger.info(f"Watching for XYZ files in: {input_dir}")
    logger.info("Press Ctrl+C to stop the pipeline")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
        observer.stop()
        job_manager.shutdown()
        observer.join()
        job_manager.join()
        logger.info("Pipeline stopped cleanly.")

if __name__ == '__main__':
    main()
