# orca_executor.py
import subprocess
import shutil
from pathlib import Path

# --- 依存関係のインポート ---
from logging_utils import get_logger
from pipeline_utils import ensure_directory # I/Oユーティリティ
from orca_utils import check_orca_output # ORCAユーティリティ

_executor_logger = get_logger('orca_executor')

class OrcaExecutor:
    """ORCAプロセスを実行し、結果をJobCompletionHandlerに渡す単一責任のクラス。"""
    
    def __init__(self, config, handler):
        # 依存関係の注入
        self.config = config
        self.handler = handler # JobCompletionHandlerのインスタンスを注入
        self.orca_executable = self.config['orca']['orca_executable']
        self.logger = _executor_logger

    def execute(self, inp_file, mol_name, calc_type):
        """Workerスレッドから呼び出され、ORCAジョブの実行を処理する。"""
        
        inp_path = Path(inp_file)
        work_dir = Path(self.config['paths']['working_dir']) / inp_path.stem
        product_dir = Path(self.config['paths']['product_dir'])
        orca_path = work_dir / inp_path.name
        output_path = work_dir / f"{inp_path.stem}.out"

        self.handler.update_status_running(str(inp_path)) # 状態をRUNNINGに更新
        
        try:
            # ★★★ ここからが変更点 (Phase 1: 準備フェーズ) ★★★
            try:
                ensure_directory(work_dir) # work_dirを作成
                shutil.copy(inp_path, work_dir) # inpファイルをwork_dirにコピー
            except (IOError, OSError) as e:
                # ファイルI/Oエラー（ディスクフル、ネットワーク切断など）
                self.logger.error(f"File I/O error for {mol_name} (Recoverable): {e}")
                current_retries = self.handler.state_store.increment_retry_count(str(inp_path))
                # OSエラーはリトライ可能（RECOVERABLE）として扱う
                self.handler.handle_failure(str(inp_path), mol_name, f"OS Error: {e}", current_retries, "RECOVERABLE")
                return # executeメソッドを終了
            # ★★★ 変更点ここまで ★★★

            # --- ORCA プロセスの実行 (Phase 2: 実行フェーズ) ---
            with open(output_path, 'w') as out_f:
                subprocess.run(
                    [self.orca_executable, str(orca_path)],
                    cwd=work_dir,
                    stdout=out_f,
                    stderr=subprocess.STDOUT,
                    check=False
                )
            
            # --- 結果のチェック ---
            success, message, error_type = check_orca_output(output_path) # orca_utilsに依存
            
            # --- 結果の委託 ---
            if success:
                self.handler.handle_success(orca_path, mol_name, calc_type, work_dir, product_dir)
            else:
                current_retries = self.handler.state_store.increment_retry_count(str(inp_path))
                # orca_utils から渡された error_type をそのまま渡す
                self.handler.handle_failure(str(inp_path), mol_name, message, current_retries, error_type)
                
        except Exception as e:
            # ★★★ ここからが変更点 (Phase 2 の例外) ★★★
            # subprocess.run 自体の失敗など、予期せぬ実行時エラー
            self.logger.error(f"Execution error for {mol_name} (Fatal): {e}")
            current_retries = self.handler.state_store.increment_retry_count(str(inp_path))
            error_message = f'Execution Error: {e}'
            # 実行時例外は 'FATAL_EXECUTION' (リトライ不要) として扱う
            self.handler.handle_failure(str(inp_path), mol_name, error_message, current_retries, "FATAL_EXECUTION")
            # ★★★ 変更点ここまで ★★★
            
        finally:
            # ガベージコレクション (Task 3.2)
            try:
                shutil.rmtree(work_dir, ignore_errors=True)
                self.logger.info(f"Cleaned up working directory: {work_dir}")
            except Exception as e:
                self.logger.error(f"Failed to cleanup working directory {work_dir}: {e}")

            inp_path.unlink(missing_ok=True) # 元のinpファイルを削除
