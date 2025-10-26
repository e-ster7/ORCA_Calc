# main_coordinator_and_scheduler.py
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
from notification_service import NotificationThrottle, send_notification # ★ send_notification をインポート
from file_watcher import XYZHandler, process_existing_xyz_files
from orca_executor import OrcaExecutor # 新しい実行器
from job_handler import JobCompletionHandler # 新しいハンドラ

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
        self.num_threads = int(self.config['orca']['num_threads'])
        
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
    
    # ★★★ ここからが変更点 ★★★
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
    # ★★★ 変更点ここまで ★★★


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

    # -----------------------------------------------------------
    # 2. 依存関係の初期化と注入
    # -----------------------------------------------------------
    
    # サービス層の初期化
    notification_throttle = NotificationThrottle()
    state_store = StateStore()
    
    # ハンドラ層の初期化 (HandlerはサービスとSchedulerに依存)
    # 依存関係は後で注入されるため、ここでは None で初期化
    handler = JobCompletionHandler(config, state_store, notification_throttle, scheduler=None)
    
    # 実行器層の初期化 (ExecutorはHandlerとConfigに依存)
    executor = OrcaExecutor(config, handler) 
    
    # スケジューラ層の初期化 (SchedulerはExecutorとStateStoreに依存)
    scheduler = JobScheduler(config, state_store, executor) 
    
    # 循環依存の解決: HandlerにSchedulerを注入する (DI)
    handler.set_scheduler(scheduler)

    # パスの検証と作成 (mainの初期ロジック)
    for path_key in ['input_dir', 'waiting_dir', 'product_dir']:
        path = Path(config['paths'][path_key])
        ensure_directory(path)

    # -----------------------------------------------------------
    # 3. 実行順序の制御 (メインロジック)
    # -----------------------------------------------------------

    # 起動時リカバリ (Task 2.1)
    logger.info("Checking for interrupted jobs...")
    recovered_jobs = state_store.get_jobs_by_status('RUNNING')
    
    if recovered_jobs:
        logger.warning(f"Found {len(recovered_jobs)} running jobs. Re-queuing them...")
        for job_id, job_info in recovered_jobs:
            scheduler.add_job(
                job_id, # job_id は orca_path (inp_file)
                job_info['molecule'],
                job_info['calc_type'],
                is_recovery=True # リカバリフラグを立てる
            )
    else:
        logger.info("No interrupted jobs found. Proceeding with normal startup.")
    
    # 既存INPファイルの処理 (JobSchedulerのadd_jobを使用)
    waiting_dir = Path(config['paths']['waiting_dir'])
    existing_inp_files = list(waiting_dir.glob('*.inp'))
    if existing_inp_files:
        logger.info(f"Found {len(existing_inp_files)} existing INP files in waiting directory")
        for inp_file in existing_inp_files:
            mol_name = inp_file.stem.replace('_opt', '').replace('_freq', '')
            calc_type = 'freq' if '_freq' in inp_file.stem else 'opt'
            scheduler.add_job(str(inp_file), mol_name, calc_type) # スケジューラメソッドを呼び出し
    
    # 既存XYZファイルの処理 (XYZHandlerのロジックを使用)
    process_existing_xyz_files(config, scheduler) # process_existing_xyz_files はJobSchedulerに依存する
    
    # ジョブスケジューラの開始
    scheduler.start()
    
    # ファイル監視の開始
    input_dir = config['paths']['input_dir']
    event_handler = XYZHandler(config, scheduler) # XYZHandlerもJobSchedulerに依存する
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
        observer.join()
        scheduler.join()
        logger.info("Pipeline stopped cleanly.")

if __name__ == '__main__':
    main()
