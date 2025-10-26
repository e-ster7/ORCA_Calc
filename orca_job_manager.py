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
        # ORCAジョブの実行に必要な全てのパスを準備
        work_dir = Path(self.config['paths']['working_dir']) / inp_path.stem
        product_dir = Path(self.config['paths']['product_dir'])
        orca_path = work_dir / inp_path.name
        output_path = work_dir / f"{inp_path.stem}.out"

        self.handler.update_status_running(str(inp_path)) # 状態をRUNNINGに更新
        
        try:
            ensure_directory(work_dir) # work_dirを作成
            shutil.copy(inp_path, work_dir) # inpファイルをwork_dirにコピー

            # --- ORCA プロセスの実行 ---
            with open(output_path, 'w') as out_f:
                subprocess.run(
                    [self.orca_executable, str(orca_path)],
                    cwd=work_dir,
                    stdout=out_f,
                    stderr=subprocess.STDOUT,
                    check=False
                )
            
            # --- 結果のチェック ---
            success, message = check_orca_output(output_path) # orca_utilsに依存
            
            # --- 結果の委託 ---
            if success:
                self.handler.handle_success(orca_path, mol_name, calc_type, work_dir, product_dir)
            else:
                # ★★★ ここからが変更点 ★★★
                # 仕様書2.3.3b: ハンドラを呼ぶ *前* にリトライ回数を増やす
                current_retries = self.state_store.increment_retry_count(str(inp_path))
                self.handler.handle_failure(str(inp_path), mol_name, message, current_retries)
                # ★★★ 変更点ここまで ★★★
                
        except Exception as e:
            self.logger.error(f"Execution error for {mol_name} ({calc_type}): {e}")
            
            # ★★★ ここからが変更点 ★★★
            # 実行時例外でもリトライ回数を増やし、ハンドラに渡す
            current_retries = self.state_store.increment_retry_count(str(inp_path))
            error_message = f'Execution Error: {e}'
            # inp_path (job_id) と エラーメッセージ、リトライ回数を渡す
            self.handler.handle_failure(str(inp_path), mol_name, error_message, current_retries)
            # ★★★ 変更点ここまで ★★★
            
        finally:
            inp_path.unlink(missing_ok=True) # 元のinpファイルを削除
