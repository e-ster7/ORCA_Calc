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
    state_store.json を監視し、完了したOPTジョブを見つけて、
    Moldenファイルを自動生成する。
    """
    
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.logger = get_logger('molden_service')
        self.running = True
        self.daemon = True # メインスレッドが終了したら一緒に終了
        
        # 設定を読み込む
        self.state_file = Path(config.get('paths', 'state_file', fallback='state_store.json'))
        self.product_dir = Path(config.get('paths', 'product_dir'))
        self.orca_executable = config.get('orca', 'orca_executable')
        self.orca_settings = config.get('orca', 'settings_opt', fallback="B3LYP D4 def2-SVP OPT TightSCF")
        
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
            
            # ポーリング間隔
            time.sleep(self.check_interval)
    
    def check_completed_jobs(self):
        """
        StateStoreクラスに依存せず、state_store.json を直接読み込んで
        完了したジョブをスキャンする。
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
            if info.get('status') == 'COMPLETED' and info.get('calc_type') == 'opt':
                
                mol_name = info.get('molecule')
                if not mol_name:
                    continue
                    
                mol_product_dir = self.product_dir / mol_name
                opt_out_file = mol_product_dir / f"{mol_name}_opt.out"
                molden_file = mol_product_dir / f"{mol_name}.molden.input"
                
                # 失敗した場合のマーカーファイル
                molden_failed_marker = mol_product_dir / f"{mol_name}.molden_failed"
                
                # 既に成功しているか、恒久的に失敗している場合はスキップ
                if molden_file.exists() or molden_failed_marker.exists():
                    continue
                    
                if not opt_out_file.exists():
                    self.logger.debug(f"opt.out not yet found for {mol_name}, skipping.")
                    continue
                
                self.logger.info(f"Found completed job to process for Molden: {mol_name}")
                self.generate_molden_file(mol_name, mol_product_dir, opt_out_file, molden_failed_marker)

    def generate_molden_file(self, mol_name, mol_product_dir, opt_out_file, molden_failed_marker):
        """
        OrcaExecutor や orca_utils に依存せず、
        Moldenファイル生成のためだけにORCAを直接呼び出す。
        """
        molden_run_dir = mol_product_dir / "molden_run"
        ensure_directory(molden_run_dir)
        
        molden_inp_path = molden_run_dir / f"{mol_name}_molden.inp"
        
        try:
            # 1. orca_utils に依存せず、opt.out から最終座標を自力で解析
            final_coords_block = self._extract_coords_from_out(opt_out_file)
            
            if not final_coords_block:
                self.logger.warning(f"Could not extract final coords from {opt_out_file.name}")
                molden_failed_marker.touch()
                return

            # 2. Molden用入力ファイルを作成
            # 'OPT' を 'SP' (単一点計算) に置き換える
            calc_keywords = self.orca_settings.replace("OPT", "SP")
            
            molden_inp_lines = []
            molden_inp_lines.append(f"# Molden generation for {mol_name}")
            molden_inp_lines.append(f"! {calc_keywords}")
            molden_inp_lines.append(f"%pal nprocs 1 end")
            molden_inp_lines.append(f"%maxcore 1000")
            molden_inp_lines.append(f"")
            molden_inp_lines.append(f'# Moldenファイルを出力')
            molden_inp_lines.append(f'%moinp "{mol_name}.molden.input"')
            molden_inp_lines.append(f"")
            molden_inp_lines.append(f"* xyz {self.config.get('orca', 'charge', fallback=0)} {self.config.get('orca', 'multiplicity', fallback=1)}")
            molden_inp_lines.append(final_coords_block) # 座標ブロックを追加
            molden_inp_lines.append(f"*")
            
            molden_inp_content = "\n".join(molden_inp_lines)
            
            with open(molden_inp_path, 'w') as f:
                f.write(molden_inp_content)
                
            # 3. ORCAを実行
            self.logger.info(f"Running ORCA (SP) for Molden generation: {mol_name}")
            subprocess.run(
                [self.orca_executable, str(molden_inp_path.name)],
                cwd=molden_run_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=300
            )
            
            # 4. 生成されたMoldenファイルを製品ディレクトリのトップに移動
            generated_file = molden_run_dir / f"{mol_name}.molden.input"
            final_dest = mol_product_dir / f"{mol_name}.molden.input"
            
            if generated_file.exists():
                shutil.move(str(generated_file), str(final_dest))
                self.logger.info(f"Successfully generated {final_dest.name}")
            else:
                self.logger.error(f"ORCA ran but Molden file not found for {mol_name}")
                molden_failed_marker.touch()
                
        except Exception as e:
            self.logger.error(f"Failed to generate Molden file for {mol_name}: {e}")
            molden_failed_marker.touch()
        finally:
            # 一時的な実行ディレクトリを削除
            shutil.rmtree(molden_run_dir, ignore_errors=True)

    def _extract_coords_from_out(self, output_path):
        """
        orca_utils.py に依存しない、このクラス専用の座標パーサー。
        成功時と失敗時の両方のパターンに対応。
        """
        try:
            with open(output_path, 'r', errors='ignore') as f:
                content = f.read()
            
            # ★★★ ここからが修正部分 ★★★
            # パターン1: 成功時の座標ブロック (CARTESIAN COORDINATES (ANGSTROEM))
            success_pattern = re.compile(
                r"CARTESIAN COORDINATES \(ANGSTROEM\)\s*\n-+\n(.*?)\n-{10,}",
                re.DOTALL
            )
            
            match = success_pattern.search(content)
            
            if match:
                self.logger.debug(f"Found successful optimization coordinates in {output_path.name}")
                coords_block = match.group(1).strip()
                coord_lines = []
                for line in coords_block.split('\n'):
                    parts = line.split()
                    if len(parts) >= 4:
                        # ORCA入力形式 (Element X Y Z) に戻す
                        coord_lines.append(f"  {parts[0]} {parts[1]} {parts[2]} {parts[3]}")
                
                if coord_lines:
                    return "\n".join(coord_lines)
            
            # パターン2: 失敗時の座標ブロック (FINAL COORDINATES (CARTESIAN))
            failure_pattern = re.compile(
                r"FINAL COORDINATES \(CARTESIAN\)\n-+\n[^\n]*\n-+\n(.*?)\n-{10,}",
                re.DOTALL
            )
            
            match = failure_pattern.search(content)
            
            if match:
                self.logger.debug(f"Found final (non-converged) coordinates in {output_path.name}")
                coords_block = match.group(1).strip()
                coord_lines = []
                for line in coords_block.split('\n'):
                    parts = line.split()
                    if len(parts) >= 4:
                        # ORCA入力形式 (Element X Y Z) に戻す
                        coord_lines.append(f"  {parts[0]} {parts[1]} {parts[2]} {parts[3]}")
                
                if coord_lines:
                    return "\n".join(coord_lines)
            # ★★★ 修正部分ここまで ★★★
            
            self.logger.warning(f"Could not find coordinate block in {output_path.name}")
            return None
            
        except Exception as e:
            self.logger.error(f"Error parsing coordinates from {output_path.name}: {e}")
            return None
