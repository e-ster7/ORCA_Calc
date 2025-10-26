# file_watcher.py
import os
import time
from pathlib import Path
from watchdog.events import FileSystemEventHandler

# --- 依存関係の明示的なインポート ---
from logging_utils import get_logger
from orca_utils import parse_xyz, generate_orca_input # ORCAユーティリティ
from pipeline_utils import safe_write # I/Oユーティリティ
# JobManagerは外部から注入される（DI）

_watcher_logger = get_logger('file_watcher')

def process_existing_xyz_files(config, job_manager):
    """Processes all existing XYZ files in the input directory at startup."""
    # ... (元のコードのロジックを再現)
    input_dir = Path(config['paths']['input_dir'])
    waiting_dir = Path(config['paths']['waiting_dir'])
    
    _watcher_logger.info("Checking for existing XYZ files...")
    
    for xyz_path in input_dir.glob('*.xyz'):
        try:
            mol_name = xyz_path.stem
            
            with open(xyz_path, 'r') as f:
                xyz_content = f.read()

            atoms, coords = parse_xyz(xyz_content) # orca_utils
            
            if not atoms:
                continue

            inp_content = generate_orca_input(config, mol_name, atoms, coords, calc_type='opt') # orca_utils
            
            inp_path = waiting_dir / f"{mol_name}_opt.inp"
            
            safe_write(inp_path, inp_content) # pipeline_utils
            
            xyz_path.rename(waiting_dir / xyz_path.name)
            
            job_manager.add_job(str(inp_path), mol_name, 'opt') # 注入されたJobManagerのメソッド
            
        except Exception as e:
            _watcher_logger.error(f"Error processing existing XYZ file {xyz_path.name}: {e}")


class XYZHandler(FileSystemEventHandler):
    """Handles file system events for new XYZ files."""
    def __init__(self, config, job_manager):
        self.config = config
        self.job_manager = job_manager # JobManagerの注入
        self.waiting_dir = Path(config['paths']['waiting_dir'])
        self.logger = _watcher_logger

    def on_created(self, event):
        """Called when a file or directory is created."""
        if not event.is_directory and event.src_path.lower().endswith('.xyz'):
            xyz_path = Path(event.src_path)
            self.logger.info(f"New XYZ file detected: {xyz_path.name}")
            
            time.sleep(1) # ファイルの書き込み完了を待つ
            
            try:
                # ... (元のコードのロジックを再現)
                mol_name = xyz_path.stem
                
                with open(xyz_path, 'r') as f:
                    xyz_content = f.read()

                atoms, coords = parse_xyz(xyz_content) # orca_utils
                
                if not atoms:
                    return

                inp_content = generate_orca_input(self.config, mol_name, atoms, coords, calc_type='opt') # orca_utils
                
                inp_path = self.waiting_dir / f"{mol_name}_opt.inp"
                
                safe_write(inp_path, inp_content) # pipeline_utils
                
                xyz_path.rename(self.waiting_dir / xyz_path.name)
                
                self.job_manager.add_job(str(inp_path), mol_name, 'opt') # 注入されたJobManagerのメソッド
                
            except Exception as e:
                self.logger.error(f"Error processing new XYZ file {xyz_path.name}: {e}")
