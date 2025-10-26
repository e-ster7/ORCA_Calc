# main_coordinator.py
import sys
import time
import threading
from pathlib import Path
from queue import Queue, Empty
from watchdog.observers import Observer

# --- 枝モジュールからのインポート ---
from config_utils import load_config
from logging_utils import get_logger, set_log_level
from pipeline_utils import ensure_directory, LOG_DIR # ユーティリティ
from state_store import StateStore
from notification_service import NotificationThrottle, send_notification
from file_watcher import XYZHandler, process_existing_xyz_files
from orca_executor import OrcaExecutor # 新しい実行器
from job_handler import JobCompletionHandler # 新しいハンドラ
from molden_service import MoldenService 


_scheduler_logger = get_logger('scheduler')

class ThreadWorker(threading.Thread):
    """Worker thread that executes jobs by calling the injected executor."""
    def __init__(self, job_queue, manager):
        super().__init__()
        self.job_queue = job_queue
        # JobSchedulerインスタンスを受け取り、executorへアクセスする
        self.manager = manager 
        self.daemon = True
        self.running = True

    def run(self):
        while self.running:
            try:
                # job_queue.get(timeout=1) は、(inp_file, mol_name, calc_type) を返す
                inp_file, mol_name, calc_type = self.job_queue.get(timeout=1)
                
                # 委託: 実行ロジックは注入されたexecutorに依頼する
                self.manager.executor.execute(inp_file, mol_name, calc_type)
                
                self.job_queue.task_done()
            except Empty:
                # タイムアウト（キューが空）の場合はループを継続
                continue
            except Exception as e:
                _scheduler_logger.error(f"Worker experienced unhandled error: {e}")

    def stop(self):
        """スレッドを安全に停止させるためのフラグ"""
        self.running = False


class JobScheduler:
    """旧JobManagerの根幹: ジョブの受付、キュー管理、スレッドの開始/停止のみを行う。"""
    
    def __init__(self, config, state_store, executor):
        # 依存関係の注入
        self.config = config
        self.state_store = state_store
        self.executor = executor # 実行器 (OrcaExecutor) が注入される
        
        self.logger = _scheduler_logger
        
        # ★★★ 修正点3: num_threads を max_parallel_jobs から取得 ★★★
        self.num_threads = int(self.config['orca']['max_parallel_jobs'])
        
        self.job_queue = Queue()
        self.workers = []
        self.is_running = False

    def start(self):
        if not self.is_running:
            self.is_running = True
            for i in range(self.num_threads):
                worker = ThreadWorker(self.job_queue, self)
                self.workers.append(worker)
                worker.start()
            self.logger.info(f"JobScheduler started with {self.num_threads} workers.")

    def shutdown(self):
        self.is_running = False
        for worker in self.workers:
            worker.stop()

    def join(self):
        for worker in self.workers:
            worker.join()
        self.logger.info("All JobScheduler workers stopped.")

    def add_job(self, inp_file, mol_name, calc_type, is_recovery=False):
        """
        Adds a new job to the queue.
        is_recovery=True の場合、重複チェックをスキップして強制的に再キューイングします。
        """
        
        if not is_recovery:
            new_job_info = {'molecule': mol_name, 'calc_type': calc_type}
            if self.state_store.has_pending_or_running(new_job_info):
                self.logger.warning(f"Job for {mol_name}/{calc_type} is already running or pending. Skipping.")
                return

        # add_jobはステータスを'PENDING'として上書き（または新規作成）します
        self.state_store.add_job(mol_name, calc_type, str(inp_file), status='PENDING')
        self.job_queue.put((inp_file, mol_name, calc_type))
        
        if is_recovery:
            self.logger.info(f"Recovered job: {mol_name} ({calc_type}). Re-queued.")
        else:
            self.logger.info(f"Added new job: {mol_name} ({calc_type}). Queue size: {self.job_queue.qsize()}")
    
    def reduce_workers(self, reason="Resource"):
        """
        メモリ不足などのリソースエラーに応じて、
        実行中のワーカー数を動的に減らします。
        """
        if self.num_threads > 1:
            self.num_threads -= 1
            
            # 停止するワーカーをリストから取り出す
            worker_to_stop = self.workers.pop()
            worker_to_stop.stop()
            
            log_message = (
                f"FATAL RESOURCE ERROR ({reason}) detected. "
                f"Dynamically reducing parallel workers to {self.num_threads}."
            )
            self.logger.critical(log_message)
            
            # この重大なイベントを管理者に通知する
            send_notification(
                self.config,
                "CRITICAL: Pipeline workers reduced",
                log_message
            )
        else:
            self.logger.warning(
                f"FATAL RESOURCE ERROR ({reason}) detected, "
                f"but cannot reduce workers further (already at 1)."
            )


def main():
    """全体の実行順序を制御し、依存関係を注入する役割を担う幹の部分"""
    
    # 1. 環境設定と初期化
    ensure_directory(LOG_DIR)
    set_log_level('INFO')
    logger = get_logger('pipeline')
    
    try:
        config = load_config()
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    # 2. 依存関係の初期化と注入
    
    # サービス層の初期化
    notification_throttle = NotificationThrottle()
    
    # ★★★ 修正点5: state_file のパスを state_dir から構築 ★★★
    state_dir = Path(config['paths'].get('state_dir', 'folders/state'))
    ensure_directory(state_dir)
    state_file_path = state_dir / 'state_store.json'
    state_store = StateStore(state_file=str(state_file_path))
    
    # ハンドラ層の初期化
    handler = JobCompletionHandler(config, state_store, notification_throttle, scheduler=None)
    
    # 実行器層の初期化
    executor = OrcaExecutor(config, handler) 
    
    # スケジューラ層の初期化
    scheduler = JobScheduler(config, state_store, executor) 
    
    # 循環依存の解決: HandlerにSchedulerを注入する (DI)
    handler.set_scheduler(scheduler)

    # ★★★ 修正点4: products_dir を product_dir として使用 ★★★
    # パスの検証と作成
    path_mappings = {
        'input_dir': 'input_dir',
        'waiting_dir': 'waiting_dir',
        'product_dir': 'products_dir'  # configのキー名とコード内での使用名をマッピング
    }
    
    for code_key, config_key in path_mappings.items():
        path = Path(config['paths'][config_key])
        ensure_directory(path)
        # コード内で使用するために、正しいキー名で再設定
        if code_key != config_key:
            config['paths'][code_key] = config['paths'][config_key]

    # 3. 実行順序の制御 (メインロジック)

    # 起動時リカバリ (Task 2.1)
    logger.info("Checking for interrupted jobs...")
    recovered_jobs = state_store.get_jobs_by_status('RUNNING')
    
    if recovered_jobs:
        logger.warning(f"Found {len(recovered_jobs)} running jobs. Re-queuing them...")
        for job_id, job_info in recovered_jobs:
            scheduler.add_job(
                job_id,
                job_info['molecule'],
                job_info['calc_type'],
                is_recovery=True
            )
    else:
        logger.info("No interrupted jobs found. Proceeding with normal startup.")
    
    # 既存INPファイルの処理
    waiting_dir = Path(config['paths']['waiting_dir'])
    existing_inp_files = list(waiting_dir.glob('*.inp'))
    if existing_inp_files:
        logger.info(f"Found {len(existing_inp_files)} existing INP files in waiting directory")
        for inp_file in existing_inp_files:
            mol_name = inp_file.stem.replace('_opt', '').replace('_freq', '')
            calc_type = 'freq' if '_freq' in inp_file.stem else 'opt'
            scheduler.add_job(str(inp_file), mol_name, calc_type)
    
    # 既存XYZファイルの処理
    process_existing_xyz_files(config, scheduler)
    
    # ジョブスケジューラの開始
    scheduler.start()
    
    # Moldenサービスの開始
    molden_watcher = MoldenService(config)
    molden_watcher.start()
    
    # ファイル監視の開始
    input_dir = config['paths']['input_dir']
    event_handler = XYZHandler(config, scheduler)
    observer = Observer()
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
        scheduler.shutdown()
        molden_watcher.stop()
        
        observer.join()
        scheduler.join()
        molden_watcher.join(timeout=5)
        
        logger.info("Pipeline stopped cleanly.")

if __name__ == '__main__':
    main()
