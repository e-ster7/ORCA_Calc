# orca_job_manager.py
import os
import sys
import time
import subprocess
import threading
import shutil
import traceback
from pathlib import Path
from queue import Queue, Empty
from concurrent.futures import ThreadPoolExecutor

# --- 依存関係の明示的なインポート ---
from logging_utils import get_logger
from pipeline_utils import ensure_directory, safe_write # I/Oユーティリティ
from notification_service import send_notification # 通知サービス
# ORCAユーティリティ
from orca_utils import (
    generate_orca_input, 
    check_orca_output, 
    extract_final_structure, 
    generate_energy_plot, 
    generate_comparison_plot
)
# StateStore, NotificationThrottleは外部から注入される（DI）

_manager_logger = get_logger('job_manager')

class ThreadWorker(threading.Thread):
    """Worker thread that executes ORCA jobs from the queue."""
    # ... (元のコードのロジックを再現)
    def __init__(self, job_queue, manager):
        super().__init__()
        self.job_queue = job_queue
        self.manager = manager
        self.daemon = True
        self.running = True

    def run(self):
        while self.running:
            try:
                inp_file, mol_name, calc_type = self.job_queue.get(timeout=1)
                self.manager._execute_job(inp_file, mol_name, calc_type)
                self.job_queue.task_done()
            except Empty:
                continue
            except Exception as e:
                _manager_logger.error(f"Worker experienced unhandled error: {e}")

    def stop(self):
        self.running = False


class JobManager:
    """Manages the job queue, execution, and state."""
    
    def __init__(self, config, state_store, notification_throttle):
        # 依存関係の注入 (Dependency Injection)
        self.config = config
        self.state_store = state_store
        self.notification_throttle = notification_throttle
        
        self.logger = _manager_logger
        self.orca_executable = self.config['orca']['orca_executable']
        self.num_threads = int(self.config['orca']['num_threads'])
        
        self.job_queue = Queue()
        self.workers = []
        self.is_running = False

    def start(self):
        # ... (元のコードのロジックを再現)
        if not self.is_running:
            self.is_running = True
            for i in range(self.num_threads):
                worker = ThreadWorker(self.job_queue, self)
                self.workers.append(worker)
                worker.start()
            self.logger.info(f"JobManager started with {self.num_threads} workers.")

    def shutdown(self):
        self.is_running = False
        for worker in self.workers:
            worker.stop()

    def join(self):
        for worker in self.workers:
            worker.join()
        self.logger.info("All JobManager workers stopped.")

    def add_job(self, inp_file, mol_name, calc_type):
        """Adds a new job to the queue."""
        new_job_info = {'molecule': mol_name, 'calc_type': calc_type}
        if self.state_store.has_pending_or_running(new_job_info):
            self.logger.warning(f"Job for {mol_name}/{calc_type} is already running or pending. Skipping.")
            return

        self.state_store.add_job(mol_name, calc_type, str(inp_file))
        self.job_queue.put((inp_file, mol_name, calc_type))
        self.logger.info(f"Added new job: {mol_name} ({calc_type}). Queue size: {self.job_queue.qsize()}")

    def _execute_job(self, inp_file, mol_name, calc_type):
        """Internal method to execute a single ORCA job."""
        # ... (元のコードのロジックを再現)
        inp_path = Path(inp_file)
        work_dir = Path(self.config['paths']['working_dir']) / inp_path.stem
        product_dir = Path(self.config['paths']['product_dir'])
        
        ensure_directory(work_dir) # pipeline_utils
        shutil.copy(inp_path, work_dir)
        
        orca_path = work_dir / inp_path.name
        output_path = work_dir / f"{inp_path.stem}.out"
        
        try:
            self.state_store.update_status(str(inp_path), 'RUNNING')
            
            with open(output_path, 'w') as out_f:
                subprocess.run(
                    [self.orca_executable, str(orca_path)],
                    cwd=work_dir,
                    stdout=out_f,
                    stderr=subprocess.STDOUT,
                    check=False
                )
            
            success, message = check_orca_output(output_path) # orca_utils
            
            if success:
                self.state_store.update_status(str(inp_path), 'COMPLETED')
                self._handle_success(orca_path, mol_name, calc_type, work_dir, product_dir)
            else:
                self.state_store.update_status(str(inp_path), f'FAILED: {message}')
                self._handle_failure(orca_path, mol_name, message)
                
        except Exception as e:
            self.logger.error(f"Execution error for {mol_name} ({calc_type}): {e}")
            self.state_store.update_status(str(inp_path), 'FAILED: Execution Error')
        finally:
            inp_path.unlink(missing_ok=True) 


    def _handle_success(self, orca_path, mol_name, calc_type, work_dir, product_dir):
        """Handles successful ORCA job completion."""
        # ... (元のコードのロジックを再現)
        self.logger.info(f"Job completed successfully: {mol_name} ({calc_type})")

        output_path = orca_path.with_suffix('.out')
        final_output_path = product_dir / output_path.name
        shutil.copy(output_path, final_output_path)
        
        generate_energy_plot(final_output_path, product_dir) # orca_utils

        if calc_type == 'opt':
            self._chain_frequency_calculation(mol_name, work_dir, product_dir)
        
        send_notification( # 注入されたサービスを呼び出し
            self.config, 
            f"Job Success: {mol_name} ({calc_type})", 
            f"ORCA job for {mol_name} ({calc_type}) finished successfully.",
            throttle_instance=self.notification_throttle
        )


    def _handle_failure(self, orca_path, mol_name, message):
        """Handles ORCA job failure."""
        # ... (元のコードのロジックを再現)
        self.logger.error(f"Job failed: {mol_name}. Reason: {message}")
        
        send_notification( # 注入されたサービスを呼び出し
            self.config, 
            f"Job Failure: {mol_name}", 
            f"ORCA job for {mol_name} failed. Reason: {message}",
            throttle_instance=self.notification_throttle
        )

        
    def _chain_frequency_calculation(self, mol_name, work_dir, product_dir):
        """Chains an optimization job to a frequency job."""
        # ... (元のコードのロジックを再現)
        opt_output = product_dir / f"{mol_name}_opt.out" 
        
        try:
            atoms, coords = extract_final_structure(opt_output) # orca_utils
            
            if atoms and coords:
                freq_inp_content = generate_orca_input(self.config, mol_name, atoms, coords, calc_type='freq') # orca_utils
                
                freq_inp_name = f"{mol_name}_freq.inp"
                freq_inp_path = product_dir / freq_inp_name
                
                safe_write(freq_inp_path, freq_inp_content) # pipeline_utils
                
                self.logger.info(f"Generated frequency input for {mol_name} at {freq_inp_path.name}")
                
                self.add_job(str(freq_inp_path), mol_name, 'freq')
                
            else:
                self.logger.error(f"Could not extract structure for {mol_name} freq chain.")

        except Exception as e:
            # tracebackを使用（元のコードの依存関係を維持）
            self.logger.error(f"Error during frequency chain for {mol_name}: {e}\n{traceback.format_exc()}")
