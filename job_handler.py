# job_handler.py
import shutil
import traceback
from pathlib import Path

# --- 依存関係のインポート ---
from logging_utils import get_logger
from notification_service import send_notification # 通知サービス
from pipeline_utils import safe_write # I/Oユーティリティ
# ORCAユーティリティ
from orca_utils import (
    generate_orca_input, 
    extract_final_structure, 
    generate_energy_plot, 
    generate_comparison_plot
)

_handler_logger = get_logger('job_handler')

class JobCompletionHandler:
    """ジョブ成功・失敗時の後処理と、連鎖計算のロジックを担当するクラス。"""
    
    def __init__(self, config, state_store, notification_throttle, scheduler):
        # 依存関係の注入
        self.config = config
        self.state_store = state_store
        self.notification_throttle = notification_throttle
        self.scheduler = scheduler # JobSchedulerのインスタンス
        self.logger = _handler_logger
        
        # ★★★ 修正点7: max_retriesを[orca]セクションから取得 ★★★
        try:
            self.max_retries = int(config.get('orca', 'max_retries', fallback=3))
        except ValueError:
            self.logger.warning("Invalid 'max_retries' in config, defaulting to 3.")
            self.max_retries = 3

    def set_scheduler(self, scheduler):
        """循環依存解決のため、後からschedulerインスタンスを注入するメソッド。"""
        self.scheduler = scheduler

    # --- 状態更新のユーティリティメソッド ---
    def update_status_running(self, inp_path):
        self.state_store.update_status(inp_path, 'RUNNING')

    def update_status_error(self, inp_path, message):
        self.state_store.update_status(inp_path, f'FAILED: {message}')

    # --- 成功時のハンドリング ---
    def handle_success(self, orca_path, mol_name, calc_type, work_dir, product_dir):
        """Handles successful ORCA job completion."""
        self.logger.info(f"Job completed successfully: {mol_name} ({calc_type})")

        output_path = orca_path.with_suffix('.out')
        
        # ★★★ 修正点4: 分子ごとのディレクトリを作成 ★★★
        mol_product_dir = product_dir / mol_name
        mol_product_dir.mkdir(parents=True, exist_ok=True)
        
        final_output_path = mol_product_dir / output_path.name
        
        shutil.copy(output_path, final_output_path)
        self.state_store.update_status(str(final_output_path), 'COMPLETED')

        generate_energy_plot(final_output_path, mol_product_dir) # orca_utils

        if calc_type == 'opt':
            self._chain_frequency_calculation(mol_name, mol_product_dir)

        send_notification(
            self.config, 
            f"Job Success: {mol_name} ({calc_type})", 
            f"ORCA job for {mol_name} ({calc_type}) finished successfully.",
            throttle_instance=self.notification_throttle
        )

    # --- 失敗時のハンドリング ---
    def handle_failure(self, orca_path, mol_name, message, current_retries, error_type):
        """
        Handles ORCA job failure, checking retry counts and error type.
        """
        
        # 恒久的な失敗の条件:
        # 1. リトライ回数が上限を超えた
        # 2. エラータイプが 'FATAL_' で始まる (FATAL_INPUT, FATAL_RESOURCE, FATAL_EXECUTION)
        is_permanent_failure = (current_retries > self.max_retries) or (error_type.startswith("FATAL"))

        if is_permanent_failure:
            # --- 恒久的な失敗 (Permanent Failure) ---
            log_message = (
                f"Job PERMANENTLY FAILED (Retries: {current_retries}, Type: {error_type}): "
                f"{mol_name}. Reason: {message}"
            )
            self.logger.error(log_message)
            
            self.state_store.update_status(str(orca_path), f'PERMANENT_FAILED: {message}')
            
            send_notification(
                self.config, 
                f"Job PERMANENTLY FAILED: {mol_name}", 
                log_message,
                throttle_instance=self.notification_throttle
            )
            
            # 自己修復ロジック: リソース不足の場合、ワーカー数を減らす
            if error_type == "FATAL_RESOURCE":
                self.scheduler.reduce_workers(reason="Resource Limit")
        
        else:
            # --- 一時的な失敗 (Temporary Failure / RECOVERABLE) ---
            log_message = (
                f"Job failed (Attempt {current_retries}/{self.max_retries}, Type: {error_type}): "
                f"{mol_name}. Reason: {message}. Will retry on next startup."
            )
            self.logger.warning(log_message)
            
            self.state_store.update_status(str(orca_path), f'FAILED: {message}')
            
            send_notification(
                self.config, 
                f"Job Failure (Attempt {current_retries}): {mol_name}", 
                log_message,
                throttle_instance=self.notification_throttle
            )

    # --- 連鎖計算のロジック ---
    def _chain_frequency_calculation(self, mol_name, product_dir):
        """Chains an optimization job to a frequency job."""
        opt_output = product_dir / f"{mol_name}_opt.out" 
        
        try:
            atoms, coords = extract_final_structure(opt_output) # orca_utils
            
            if atoms and coords:
                freq_inp_content = generate_orca_input(self.config, mol_name, atoms, coords, calc_type='freq') # orca_utils
                
                freq_inp_name = f"{mol_name}_freq.inp"
                freq_inp_path = product_dir / freq_inp_name
                
                safe_write(freq_inp_path, freq_inp_content) # pipeline_utils
                
                self.logger.info(f"Generated frequency input for {mol_name} at {freq_inp_path.name}")
                
                # JobSchedulerに戻してジョブを追加
                self.scheduler.add_job(str(freq_inp_path), mol_name, 'freq')
                
            else:
                self.logger.error(f"Could not extract structure for {mol_name} freq chain.")

        except Exception as e:
            self.logger.error(f"Error during frequency chain for {mol_name}: {e}\n{traceback.format_exc()}")
