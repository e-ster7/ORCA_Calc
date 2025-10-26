# molden_service.py
import threading
import time
import json
import subprocess
from pathlib import Path
import shutil
import re

# --- プロジェクト内インポート (ユーティリティのみ) ---
from logging_utils import get_logger
from pipeline_utils import ensure_directory

class MoldenService(threading.Thread):
    """
    メインパイプラインとは独立して動作するサービス。
    state_store.json を監視し、完了したジョブを見つけて、
    .gbw ファイルから .molden.input ファイルを生成する。
    """
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.logger = get_logger('molden_service')
        self.running = True
    # --- 修正後 (L20-L25) ---
        self.daemon = True # メインスレッドが終了したら一緒に終了
        
        state_dir = Path(config['paths'].get('state_dir', 'folders/state'))
        self.state_file = state_dir / 'state_store.json'
        
        self.product_dir = Path(config['paths']['products_dir'])
        
        # orca_2mkl ユーティリティのパスを取得
        # orca本体と同じディレクトリにあると仮定
        orca_executable_path = Path(config.get('orca', 'orca_executable'))
        self.orca_2mkl_path = orca_executable_path.parent / "orca_2mkl"
        
        self.check_interval = 60 # 60秒ごとに state_store.json をチェック
        self.logger.info("MoldenService initialized. Watching for completed jobs...")
        
    def stop(self):
        """スレッドの停止を要求"""
        self.running = False
        self.logger.info("MoldenService stopping...")
        
    def run(self):
        """スレッドのメインループ"""
        while self.running:
            try:
                self.check_completed_jobs()
            except Exception as e:
                self.logger.error(f"Error in MoldenService loop: {e}", exc_info=True)
            
            time.sleep(self.check_interval)
    
    def check_completed_jobs(self):
        """
        state_store.json を直接読み込み、
        COMPLETED ステータスで .gbw ファイルを持つジョブを探す。
        """
        if not self.state_file.exists():
            return

        try:
            with open(self.state_file, 'r') as f:
                state_data = json.load(f)
        except json.JSONDecodeError:
            self.logger.warning(f"Could not parse state_store.json, skipping cycle.")
            return

        for job_id, info in state_data.items():
            # 完了したジョブを探す
            if info.get('status') == 'COMPLETED':
                
                mol_name = info.get('molecule')
                calc_type = info.get('calc_type')
                if not mol_name or not calc_type:
                    continue
                    
                mol_product_dir = self.product_dir / mol_name
                # job_handler がコピーした .gbw ファイル
                gbw_file = mol_product_dir / f"{mol_name}_{calc_type}.gbw"
                # 生成したい Molden ファイル
                molden_file = mol_product_dir / f"{mol_name}_{calc_type}.molden.input"
                
                # 失敗した場合のマーカーファイル
                molden_failed_marker = mol_product_dir / f"{mol_name}_{calc_type}.molden_failed"
                
                # 既に成功しているか、恒久的に失敗している場合はスキップ
                if molden_file.exists() or molden_failed_marker.exists():
                    continue
                    
                # .gbw ファイル（波動関数）が存在するかチェック
                if not gbw_file.exists():
                    self.logger.debug(f".gbw file not yet found for {mol_name} ({calc_type}), skipping.")
                    continue
                
                self.logger.info(f"Found completed job to process for Molden: {mol_name} ({calc_type})")
                self.generate_molden_file(mol_name, calc_type, mol_product_dir, gbw_file, molden_file, molden_failed_marker)

    def generate_molden_file(self, mol_name, calc_type, mol_product_dir, gbw_file, molden_file, molden_failed_marker):
        """
        orca_2mkl ユーティリティを実行して .gbw から .molden.input を生成する。
        """
        
        # orca_2mkl は .gbw と同じディレクトリで実行する必要がある
        
        base_name = f"{mol_name}_{calc_type}" # 例: "molecule_opt"
        
        try:
            # 1. orca_2mkl コマンドの準備
            # コマンド: orca_2mkl molecule_opt -molden
            cmd = [str(self.orca_2mkl_path), base_name, "-molden"]
                
            # 2. orca_2mkl を実行
            self.logger.info(f"Running orca_2mkl for {base_name}...")
            result = subprocess.run(
                cmd,
                cwd=mol_product_dir, # .gbw ファイルがあるディレクトリで実行
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=300 # 5分タイムアウト
            )
            
            # 3. 生成されたファイルを確認
            # orca_2mkl は {base_name}.molden.input という名前で出力する
            generated_file = mol_product_dir / f"{base_name}.molden.input"
            
            if generated_file.exists() and result.returncode == 0:
                # ファイル名が期待通りなので、特に移動は不要
                self.logger.info(f"Successfully generated {generated_file.name}")
            else:
                self.logger.error(f"orca_2mkl failed for {base_name}. STDERR: {result.stderr}")
                molden_failed_marker.touch()
                
        except Exception as e:
            self.logger.error(f"Failed to run orca_2mkl for {base_name}: {e}")
            molden_failed_marker.touch()

    def _extract_coords_from_out(self, output_path):
        """
        ★★★ この関数は不要になりました ★★★
        """
        pass
