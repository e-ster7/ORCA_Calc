ご要望に基づき、前の手順で作成した8つの機能モジュール（枝）に存在する**クラス**、**関数**、**メソッド**について、AIがコードの構造、機能、および依存関係を正確に理解できるように、非常に詳細な説明書（APIドキュメント形式）を作成します。

この情報は、AIがコードの変更、デバッグ、または機能追加を行う際の**コンテキスト**として機能します。

---

## 📘 クラス説明書 (Class Documentation)

| クラス名 | 定義場所 | 役割と目的 | 初期化 (Constructor) | 主なメソッドと依存関係 |
| :--- | :--- | :--- | :--- | :--- |
| **StateStore** | `state_store.py` | 実行中および完了したジョブの状態（ステータス、ファイルパスなど）を一元管理します。`state_store.json` ファイルへの永続化を行います。 | `__init__(self, state_file='state_store.json')` | `add_job`, `update_status`, `has_pending_or_running`。**依存:** `logging_utils`。 |
| **NotificationThrottle** | `notification_service.py` | 同じ件名 (`subject`) の通知が短期間に何度も送信されるのを防ぐための、時間ベースのレート制限機能を提供します。 | `__init__(self, interval_minutes=60)` | `can_send(subject)`: 送信可能かチェックし、送信可能なら時間を更新。 |
| **ThreadWorker** | `orca_job_manager.py` | `JobManager` のためにジョブキューからタスクを取り出し、個々の ORCA ジョブを実行する**スレッド**です。デーモンとして動作します。 | `__init__(self, job_queue, manager)` | `run()`: キューからジョブを取得し、`JobManager._execute_job` を呼び出す。`stop()`。 |
| **JobManager** | `orca_job_manager.py` | ORCA計算パイプラインの**心臓部**。ジョブのキュー管理、スレッド管理、実行、成功/失敗時の処理連鎖（例: 最適化→振動数）を担当します。 | `__init__(self, config, state_store, notification_throttle)` | `start()`, `shutdown()`, `add_job()`, `_execute_job()` (内部)。**依存:** `config`, `state_store`, `notification_throttle` の**インスタンス**を注入（DI）される。 |
| **XYZHandler** | `file_watcher.py` | `watchdog` ライブラリのイベントハンドラを継承し、監視ディレクトリに新しい `.xyz` ファイルが作成されたときに、ORCA入力ファイル (`.inp`) を作成し、ジョブキューに追加する処理を担当します。 | `__init__(self, config, job_manager)` | `on_created(event)`: ファイル作成イベント発生時に呼び出される。**依存:** `JobManager` の**インスタンス**を注入（DI）される。 |

---

## 🛠️ 関数・メソッド説明書 (Function and Method Documentation)

### A. 共通ユーティリティ (`pipeline_utils.py`)

| 名前 | 種別 | 役割と詳細 | 入力 (Arguments) | 戻り値 (Returns) |
| :--- | :--- | :--- | :--- | :--- |
| **safe_write** | 関数 | ファイルに内容を安全に書き込みます。親ディレクトリが存在しない場合は作成します。 | `path` (str/Path), `content` (str) | `True` (成功時) / `False` (I/Oエラー時)。 |
| **get_unique_path**| 関数 | 指定されたパスが存在する場合、連番を付加した一意な新しいパスを返します。 | `base_path` (str/Path) | 存在しない `Path` オブジェクト。 |
| **ensure_directory**| 関数 | 指定されたパスのディレクトリが確実に存在するように作成します (`parents=True, exist_ok=True` 付き)。 | `path` (str/Path) | なし。 |

---

### B. 設定・ロギング・通知 (`config_utils.py`, `logging_utils.py`, `notification_service.py`)

| 名前 | 種別 | 役割と詳細 | 入力 (Arguments) | 戻り値 (Returns) |
| :--- | :--- | :--- | :--- | :--- |
| **load_config** | 関数 | `config.txt` ファイルを読み込み、`configparser` オブジェクトとして返します。ファイルが存在しない場合は例外を発生させます。 | `config_path` (str, 既定値: 'config.txt') | `configparser.ConfigParser` オブジェクト。 |
| **get_logger** | 関数 | 指定された名前のロガーインスタンスを返します。 | `name` (str) | `logging.Logger` インスタンス。 |
| **set_log_level** | 関数 | グローバルなロギングレベルを設定します（例: 'INFO', 'DEBUG'）。 | `level` (str) | なし。 |
| **send_notification**| 関数 | 設定ファイルに定義された Gmail アカウントを使用してメール通知を送信します。スロットルインスタンスが提供された場合は、送信前にチェックします。 | `config` (`configparser`), `subject` (str), `body` (str), `throttle_instance` (`NotificationThrottle`, オプション) | なし。 |
| `can_send` | メソッド | **(NotificationThrottle)** 指定された件名の通知が、インターバル期間を過ぎているか確認します。送信可能であれば、最終送信時間を更新します。 | `subject` (str) | `True` (送信可能) / `False` (制限中)。 |

---

### C. ORCA入出力処理 (`orca_utils.py`)

| 名前 | 種別 | 役割と詳細 | 入力 (Arguments) | 戻り値 (Returns) |
| :--- | :--- | :--- | :--- | :--- |
| **generate_orca_input**| 関数 | 分子名、原子リスト、座標から ORCA の `.inp` ファイルの内容を文字列として生成します。 | `config`, `mol_name`, `atoms` (list), `coords` (list of list), `calc_type` (str, 既定値: 'opt') | 生成された ORCA 入力ファイルのコンテンツ (str)。 |
| **parse_xyz** | 関数 | XYZ ファイルのコンテンツ文字列を解析し、原子のリストと座標のリストに分離します。 | `xyz_content` (str) | `atoms` (list of str), `coords` (list of list of float)。 |
| **check_orca_output**| 関数 | ORCA の `.out` ファイルをチェックし、ジョブが正常に終了し、最適化が収束したかを確認します。 | `output_path` (Path) | `(success: bool, message: str)` のタプル。 |
| **extract_final_structure**| 関数 | 収束した ORCA 出力ファイルから、最終的な原子の座標と原子種を抽出します。 | `output_path` (Path) | `(atoms: list, coords: list of list)` のタプル。抽出失敗時は `(None, None)`。 |
| **generate_energy_plot**| 関数 | ORCA 出力からエネルギー推移を抽出し、PNGファイルとしてプロットを保存します。`matplotlib` に依存します。 | `output_path` (Path), `save_dir` (Path) | `True` (成功時) / `False` (失敗時)。 |
| **generate_comparison_plot**| 関数 | 最適化と振動数の最終エネルギー値を比較する棒グラフを生成・保存します。`matplotlib` に依存します。 | `opt_path` (Path), `freq_path` (Path), `save_dir` (Path) | `True` (成功時) / `False` (失敗時)。 |

---

### D. ジョブ管理 (`orca_job_manager.py`)

| 名前 | 種別 | 役割と詳細 | 入力 (Arguments) | 戻り値 (Returns) |
| :--- | :--- | :--- | :--- | :--- |
| `start` | メソッド | **(JobManager)** 指定された数の `ThreadWorker` を作成し、ジョブの処理を開始します。 | なし | なし |
| `shutdown` | メソッド | **(JobManager)** すべてのワーカーに停止を指示し、キューの処理を終了します。 | なし | なし |
| `add_job` | メソッド | **(JobManager)** 新しいジョブをキューに追加し、`StateStore` のステータスを 'PENDING' に更新します。重複ジョブはスキップされます。 | `inp_file` (str), `mol_name` (str), `calc_type` (str) | なし |
| `_execute_job` | メソッド | **(JobManager, 内部)** 実際に ORCA コマンドを実行し、出力を監視し、成功/失敗ハンドラを呼び出します。 | `inp_file`, `mol_name`, `calc_type` | なし |
| `_handle_success` | メソッド | **(JobManager, 内部)** ジョブ成功時の後処理（出力ファイル移動、プロット生成、通知、振動数計算への連鎖）を行います。 | `orca_path`, `mol_name`, `calc_type`, `work_dir`, `product_dir` | なし |
| `_chain_frequency_calculation`| メソッド | **(JobManager, 内部)** 最適化（'opt'）ジョブの成功後、最終構造を抽出し、振動数（'freq'）計算ジョブを生成・追加します。 | `mol_name`, `work_dir`, `product_dir` | なし |

---

### E. ファイル監視 (`file_watcher.py`)

| 名前 | 種別 | 役割と詳細 | 入力 (Arguments) | 戻り値 (Returns) |
| :--- | :--- | :--- | :--- | :--- |
| **process_existing_xyz_files**| 関数 | 起動時に、監視ディレクトリ内の既存の `.xyz` ファイルを全て処理し、INPファイルを生成してジョブキューに追加します。 | `config`, `job_manager` (`JobManager`インスタンス) | なし |
| `on_created` | メソッド | **(XYZHandler)** ファイルシステムイベントにより、新しい `.xyz` ファイルが検出されたときに自動で呼び出されます。INPファイル生成とジョブ追加を行います。 | `event` (`watchdog.events.FileCreatedEvent`) | なし |
