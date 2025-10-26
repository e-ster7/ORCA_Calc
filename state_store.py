# state_store.py
import json
from pathlib import Path
from datetime import datetime
# 依存関係: logging_utilsからロガーを取得
from logging_utils import get_logger

class StateStore:
    """Manages the state of running and completed jobs."""
    def __init__(self, state_file='state_store.json'):
        self.state_file = Path(state_file)
        self.job_info = {}
        self.logger = get_logger('state_store')
        self._load_state()

    def _load_state(self):
        """Loads state from file if it exists."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r') as f:
                    self.job_info = json.load(f)
                self.logger.info(f"Loaded state with {len(self.job_info)} entries.")
            except Exception as e:
                self.logger.error(f"Failed to load state file: {e}")
                self.job_info = {}

    def _save_state(self):
        """Saves current state to file."""
        try:
            with open(self.state_file, 'w') as f:
                json.dump(self.job_info, f, indent=4)
        except Exception as e:
            self.logger.error(f"Failed to save state file: {e}")

    def add_job(self, mol_name, calc_type, orca_path, status='PENDING'):
        """Adds or updates a job entry."""
        job_id = orca_path 
        self.job_info[job_id] = {
            'molecule': mol_name,
            'calc_type': calc_type,
            'orca_path': orca_path,
            'status': status,
            'start_time': str(datetime.now())
        }
        self._save_state()
        
    def get_job(self, job_id):
        """Retrieves a job by its ID."""
        return self.job_info.get(job_id)

    def update_status(self, job_id, status):
        """Updates the status of a job."""
        if job_id in self.job_info:
            self.job_info[job_id]['status'] = status
            self._save_state()
            return True
        return False
        
    def _same_job(self, job1, job2):
        """Check if two job infos represent the same job"""
        return (job1.get('molecule') == job2.get('molecule') and 
                job1.get('calc_type') == job2.get('calc_type'))

    def has_pending_or_running(self, new_job_info):
        """Checks if a similar job is already running or pending."""
        for job_id, job_info in self.job_info.items():
            if job_info['status'] in ['PENDING', 'RUNNING'] and self._same_job(job_info, new_job_info):
                return True
        return False

    # ★★★ ここからが変更点 ★★★
    def get_jobs_by_status(self, status):
        """
        指定されたステータスを持つすべてのジョブを取得します。
        (仕様書に基づく追加機能)
        """
        found_jobs = []
        target_status = status.upper()
        
        # job_id (orca_path) と job_info の両方を返す
        for job_id, job_info in self.job_info.items():
            if job_info.get('status', '').upper() == target_status:
                found_jobs.append((job_id, job_info))
                
        return found_jobs
    # ★★★ 変更点ここまで ★★★
