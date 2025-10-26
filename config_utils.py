# config_utils.py
import configparser
from pathlib import Path

def load_config(config_path='config.txt'):
    """Loads and returns the configuration from config.txt."""
    config = configparser.ConfigParser()
    path = Path(config_path)
    
    if not path.exists():
        # 設定ファイルが見つからない場合は例外を発生
        raise FileNotFoundError(f"Configuration file not found at {config_path}")
        
    config.read(path)
    
    # 使用されていたセクションの最低限のバリデーション
    if 'paths' not in config or 'orca' not in config:
        raise ValueError("Configuration must contain 'paths' and 'orca' sections.")
        
    return config
