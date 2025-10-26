はい、承知いたしました。
プロジェクトの最終状態に基づいて、関数/メソッドの説明書とクラスの説明書をそれぞれ作成します。

---

## 🛠️ 関数/メソッド 詳細説明書 (最終版)

この文書は、プロジェクト内の主要な関数とメソッドについて、その役割、引数、依存関係を詳細に記述します。

### A. コアスケジューリング (`main_coordinator.py`)

| 名前                | タイプ | 役割と詳細                                                                                                                               | 引数                                                               | 依存関係 (呼び出し先)                                                                                                                                                                                                                                                                                                 |
| :------------------ | :----- | :--------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `main`              | 関数   | パイプライン全体の**起動シーケンス**を制御します。設定読み込み、依存関係の初期化と注入（DI）、起動時リカバリ、既存ファイル処理、スケジューラ/ウォッチャー/Moldenサービスの開始、正常シャットダウン処理を行います。 | なし                                                               | `load_config`, `get_logger`, `ensure_directory`, `StateStore`, `NotificationThrottle`, `JobCompletionHandler`, `OrcaExecutor`, `JobScheduler`, `MoldenService`, `process_existing_xyz_files`, `XYZHandler`, `Observer`                                                                                             |
| `start`             | メソッド | **(JobScheduler)** 設定された `num_threads` に基づき `ThreadWorker` スレッドを初期化して開始します。パイプラインの `is_running` 状態を `True` に設定します。                     | なし                                                               | `ThreadWorker`                                                                                                                                                                                                                                                                                                         |
| `shutdown`          | メソッド | **(JobScheduler)** すべての `ThreadWorker` スレッドに停止フラグ (`running = False`) を設定し、安全なシャットダウンを促します。                                                       | なし                                                               | `ThreadWorker.stop()`                                                                                                                                                                                                                                                                                                |
| `add_job`           | メソッド | **(JobScheduler)** 新規またはリカバリジョブを受け付けます。重複チェック（リカバリ時はスキップ）を行い、`StateStore` の状態を `PENDING` に更新し、ジョブキュー (`Queue`) に追加します。 | `inp_file` (str), `mol_name` (str), `calc_type` (str), `is_recovery` (bool, Optional) | `StateStore.has_pending_or_running`, `StateStore.add_job`                                                                                                                                                                 |
| `reduce_workers`    | メソッド | **(JobScheduler)** `JobHandler` からリソース不足 (`FATAL_RESOURCE`) が報告された際に呼び出されます。ワーカー数を1減らし（1未満にはしない）、該当ワーカーを停止させ、管理者へ緊急通知を送信します。 | `reason` (str, Optional)                                           | `send_notification`, `ThreadWorker.stop()`                                                                                                                                                                         |
| `run`               | メソッド | **(ThreadWorker)** スレッドのメインループ。ジョブキューからジョブを取得し、注入された `OrcaExecutor` の `execute` メソッドを呼び出して計算を実行します。                        | なし                                                               | `OrcaExecutor.execute`                                                                                                                                                                                             |
| `stop`              | メソッド | **(ThreadWorker)** スレッドの `running` フラグを `False` に設定し、`run` メソッドのループを終了させます。                                                                      | なし                                                               | なし                                                                                                                                                                                                                                                                                                         |
| `execute`           | メソッド | **(OrcaExecutor)** `ThreadWorker` から呼び出されます。一時ディレクトリの準備、ORCAサブプロセスの実行、`check_orca_output` による結果解析、`JobCompletionHandler` への結果委譲、一時ディレクトリの削除（`finally`）を行います。**OSエラー**と**ORCAエラー**を区別して処理します。 | `inp_file` (str), `mol_name` (str), `calc_type` (str)            | `ensure_directory`, `shutil.copy`, `subprocess.run`, `check_orca_output`, `JobCompletionHandler.handle_success`, `JobCompletionHandler.handle_failure`, `shutil.rmtree` |

---

### B. ジョブハンドリング (`job_handler.py`)

| 名前                          | タイプ | 役割と詳細                                                                                                                                                                                           | 引数                                                                                         | 依存関係 (呼び出し先)                                                                                                                                                                                                                            |
| :---------------------------- | :----- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `set_scheduler`               | メソッド | **(JobCompletionHandler)** `main` 関数から呼び出され、`JobScheduler` インスタンスを後から注入することで、**循環依存**（Handler <-> Scheduler）を解決します。                                           | `scheduler` (`JobScheduler` instance)                                                        | なし                                                                                                                                                                                                                                           |
| `handle_success`              | メソッド | **(JobCompletionHandler)** 計算成功時の後処理を担当。`.out` と `.gbw` ファイルを製品ディレクトリにコピーし、`StateStore` を `COMPLETED` に更新し、エネルギープロット生成、振動数計算の連鎖、完了通知送信を行います。 | `orca_path` (Path), `mol_name` (str), `calc_type` (str), `work_dir` (Path), `product_dir` (Path) | `shutil.copy`, `StateStore.update_status`, `generate_energy_plot`, `_chain_frequency_calculation`, `send_notification` |
| `handle_failure`              | メソッド | **(JobCompletionHandler)** 計算失敗時の後処理を担当。リトライ回数とエラータイプ (`FATAL_` かどうか) をチェックし、`StateStore` を `FAILED` または `PERMANENT_FAILED` に更新し、失敗通知を送信します。**リソースエラー** (`FATAL_RESOURCE`) の場合は `scheduler.reduce_workers` を呼び出して自己修復を試みます。 | `orca_path` (str), `mol_name` (str), `message` (str), `current_retries` (int), `error_type` (str) | `StateStore.update_status`, `send_notification`, `JobScheduler.reduce_workers` |
| `_chain_frequency_calculation`| メソッド | **(JobCompletionHandler, 内部)** 成功したOPT計算の `.out` ファイルから最終構造を抽出し、FREQ計算用の `.inp` ファイルを生成して `product_dir` に保存し、`JobScheduler.add_job` で新しいジョブとして登録します。 | `mol_name` (str), `product_dir` (Path)                                                         | `extract_final_structure`, `generate_orca_input`, `safe_write`, `JobScheduler.add_job` |

---

### C. ORCAユーティリティ (`orca_utils.py`)

| 名前                      | タイプ | 役割と詳細                                                                                                                                                                                 | 引数                                                                              | 依存関係 (呼び出し先) |
| :------------------------ | :----- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------- | :------------------ |
| `generate_orca_input`     | 関数   | `config.txt` の設定 (メソッド、基底、溶媒、RIJCOSXなど) とXYZ座標から、ORCAの `.inp` ファイルの内容（文字列）を動的に生成します。                                                               | `config` (ConfigParser), `mol_name` (str), `atoms` (list), `coords` (list of list), `calc_type` (str) | なし                |
| `parse_xyz`               | 関数   | `.xyz` ファイルの内容（文字列）を受け取り、原子リスト (`atoms`) と座標リスト (`coords`) を抽出して返します。                                                                                       | `xyz_content` (str)                                                               | なし                |
| `check_orca_output`       | 関数   | ORCAの `.out` ファイルを解析し、計算の成否 (`bool`)、メッセージ (`str`)、**エラータイプ** (`'N/A'`, `'RECOVERABLE'`, `'FATAL_INPUT'`, `'FATAL_RESOURCE'`) の3つ組を返します。入力ミス、リソース不足を区別します。 | `output_path` (Path)                                                              | なし                |
| `extract_final_structure` | 関数   | `.out` ファイルを解析し、**成功時** (`ANGSTROEM` 形式) または **失敗時** (`CARTESIAN` 形式) の**最終座標**を抽出して、原子リストと座標リストを返します。内部で `_parse_coordinate_block` を呼び出します。        | `output_path` (Path)                                                              | `_parse_coordinate_block` |
| `_parse_coordinate_block` | 関数   | `extract_final_structure` から呼び出されるヘルパー関数。座標ブロックの文字列を受け取り、成功/失敗フォーマットに応じて原子リストと座標リストを解析して返します。（**失敗時のインデックス解析バグ修正済み**）                   | `coords_block` (str), `format_type` (str)                                         | なし                |
| `_get_energy_data`        | 関数   | `.out` ファイルから最適化ステップごとのエネルギー (`E_...= ...`) を抽出し、数値のリストとして返します。（**タイプミス修正済み**）                                                                 | `output_path` (Path)                                                              | なし                |
| `generate_energy_plot`    | 関数   | `_get_energy_data` で取得したエネルギーリストを使い、`matplotlib` でエネルギー収束グラフ（PNG画像）を生成して保存します。                                                                       | `output_path` (Path), `save_dir` (Path)                                           | `_get_energy_data`, `matplotlib` (条件付き) |
| `generate_comparison_plot`| 関数   | OPT計算とFREQ計算の最終エネルギーを比較する棒グラフを生成します（現在は未使用）。                                                                                                               | `opt_path` (Path), `freq_path` (Path), `save_dir` (Path)                            | `_get_energy_data`, `matplotlib` (条件付き) |

---

### D. ファイル監視 (`file_watcher.py`)

| 名前                         | タイプ | 役割と詳細                                                                                                                                                     | 引数                                                     | 依存関係 (呼び出し先)                                                                                                |
| :--------------------------- | :----- | :------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------- |
| `process_existing_xyz_files` | 関数   | パイプライン**起動時**に一度だけ呼び出されます。`input_dir` 内の既存の `.xyz` ファイルをスキャンし、`.inp` ファイルを生成して `waiting_dir` に移動させ、`JobScheduler.add_job` でジョブを登録します。 | `config` (ConfigParser), `job_manager` (`JobScheduler` instance) | `parse_xyz`, `generate_orca_input`, `safe_write`, `JobScheduler.add_job` |
| `on_created`                 | メソッド | **(XYZHandler)** `watchdog` ライブラリによって、`input_dir` に新しいファイルが作成されると**リアルタイム**に呼び出されます。`.xyz` ファイルであれば、`.inp` を生成し、`JobScheduler.add_job` でジョブを登録します。 | `event` (`watchdog.events.FileCreatedEvent`)             | `parse_xyz`, `generate_orca_input`, `safe_write`, `JobScheduler.add_job` |

---

### E. Moldenサービス (`molden_service.py`)

| 名前                   | タイプ | 役割と詳細                                                                                                                                                                                                                           | 引数                                                                                                   | 依存関係 (呼び出し先)                                                                                                              |
| :--------------------- | :----- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------- |
| `run`                  | メソッド | **(MoldenService)** スレッドのメインループ。`check_interval` ごとに `check_completed_jobs` を呼び出します。                                                                                                                            | なし                                                                                                   | `check_completed_jobs`                                                                                                             |
| `stop`                 | メソッド | **(MoldenService)** スレッドの `running` フラグを `False` に設定し、ループを終了させます。                                                                                                                                             | なし                                                                                                   | なし                                                                                                                               |
| `check_completed_jobs` | メソッド | **(MoldenService)** `state_store.json` を直接読み込み、`COMPLETED` ステータスのジョブを探します。`.gbw` ファイルが存在し、かつ `.molden.input` がまだ生成されていない場合、`generate_molden_file` を呼び出します。失敗マーカー (`.molden_failed`) もチェックします。 | なし                                                                                                   | `json.load`, `generate_molden_file`                                                                                                |
| `generate_molden_file` | メソッド | **(MoldenService)** `orca_2mkl` コマンドを `subprocess` で実行し、指定された `.gbw` ファイルから `.molden.input` ファイルを生成します。成功/失敗に応じてログを出力し、失敗時はマーカーファイルを作成して無限リトライを防ぎます。                           | `mol_name` (str), `calc_type` (str), `mol_product_dir` (Path), `gbw_file` (Path), `molden_file` (Path), `molden_failed_marker` (Path) | `subprocess.run`, `Path.touch`                                                                                                   |
| `_extract_coords_from_out` | メソッド | **(MoldenService)** ***[削除済み]*** この関数は `orca_2mkl` アプローチへの変更により不要になりました。                                                                                                                             | -                                                                                                      | -                                                                                                                                |

---

### F. その他ユーティリティモジュール

| 名前                | タイプ | モジュール                    | 役割と詳細                                                                                                                                                     | 引数                                                            |
| :------------------ | :----- | :-------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------- |
| `load_config`       | 関数   | `config_utils.py`           | `config.txt` を読み込み、`ConfigParser` オブジェクトとして返します。必須セクション (`[paths]`, `[orca]`) の存在をチェックします。                                 | `config_path` (str, Optional)                                   |
| `can_send`          | メソッド | `notification_service.py` | **(NotificationThrottle)** 指定された件名の通知が、設定された `interval` 内に送信されていないかチェックします（レート制限）。                                          | `subject` (str)                                                 |
| `send_notification` | 関数   | `notification_service.py` | Gmail経由でメールを送信します。**指数関数的バックオフ**による自動リトライ機能（一時的なネットワークエラーの場合）と、認証エラー時の即時失敗処理を実装しています。 | `config` (ConfigParser), `subject` (str), `body` (str), `throttle_instance` (Optional) |
| `safe_write`        | 関数   | `pipeline_utils.py`         | ファイルを安全に書き込みます。親ディレクトリが存在しない場合は自動的に作成します。                                                                                  | `path` (Path/str), `content` (str)                              |
| `ensure_directory`  | 関数   | `pipeline_utils.py`         | 指定されたパスのディレクトリが存在することを保証します。存在しない場合は作成します。                                                                                | `path` (Path/str)                                               |
| `get_logger`        | 関数   | `logging_utils.py`          | 指定された名前で、設定済みの `logging.Logger` インスタンスを取得します。                                                                                         | `name` (str)                                                    |
| `set_log_level`     | 関数   | `logging_utils.py`          | パイプライン全体のグローバルなログレベルを設定します。                                                                                                            | `level` (str, e.g., 'INFO', 'DEBUG')                            |

---
---

## 📘 クラス 詳細説明書 (最終版)

この文書は、プロジェクト内の主要なクラスについて、その役割、依存関係、主要メソッドを詳細に記述します。

### 1. `JobScheduler`

* **モジュール:** `main_coordinator.py`
* **役割:** パイプライン全体の**調整役**であり、**ルート（幹）**となるクラスです。ジョブの受付、実行キューの管理、`ThreadWorker` スレッドのライフサイクル管理を担当します。計算実行や結果処理の**具体的なロジックは持たず**、すべて注入された依存オブジェクト（`OrcaExecutor`, `StateStore`）に委譲します。
* **依存関係 (注入):**
    * `config` (ConfigParser): 設定情報へのアクセス。
    * `StateStore` (インスタンス): ジョブ状態の永続化と重複チェック。
    * `OrcaExecutor` (インスタンス): 実際の計算実行ロジック。
* **主要メソッド:**
    * `start()`: ワーカープールを開始します。
    * `shutdown()`: ワーカープールを安全に停止させます。
    * `add_job(inp_file, mol_name, calc_type, is_recovery=False)`: 新規またはリカバリジョブをキューに追加します。
    * `reduce_workers(reason="Resource")`: リソース不足エラー時にワーカー数を動的に減らします。
    * `join()`: すべてのワーカースレッドの終了を待ちます。

---

### 2. `ThreadWorker`

* **モジュール:** `main_coordinator.py`
* **役割:** `JobScheduler` によって管理される**ワーカースレッド**の実体です。ジョブキューから計算タスクを取得し、注入された `OrcaExecutor` の `execute` メソッドを呼び出すことで、計算を実行します。
* **依存関係 (注入):**
    * `job_queue` (Queue): 計算タスクが格納されるキュー。
    * `manager` (`JobScheduler` インスタンス): `OrcaExecutor` インスタンスにアクセスするために使用。
* **主要メソッド:**
    * `run()`: スレッドのメイン実行ループ。キューからジョブを取得し `OrcaExecutor.execute` を呼び出します。
    * `stop()`: スレッドの実行ループを終了させるためのフラグを設定します。

---

### 3. `OrcaExecutor`

* **モジュール:** `orca_job_manager.py`
* **役割:** ORCAプロセス実行の**単一責任**を担います。一時作業ディレクトリの管理、`subprocess` によるORCAの起動、`orca_utils.check_orca_output` を用いた標準出力の監視と結果判定、そして結果（成否、メッセージ、エラータイプ）の `JobCompletionHandler` への報告を行います。**ファイルI/Oエラー**と**ORCA実行エラー**を区別して処理します。
* **依存関係 (注入):**
    * `config` (ConfigParser): ORCA実行パスやディレクトリパスへのアクセス。
    * `handler` (`JobCompletionHandler` インスタンス): 計算結果（成功/失敗）の報告先。
* **主要メソッド:**
    * `execute(inp_file, mol_name, calc_type)`: ORCA計算を実行し、結果を `handler` に渡します。

---

### 4. `JobCompletionHandler`

* **モジュール:** `job_handler.py`
* **役割:** 計算**完了後**のすべての処理の**単一責任**を担います。成功時には結果ファイル（`.out`, `.gbw`）のコピー、`StateStore` の状態更新、エネルギープロット生成、振動数計算の**連鎖起動** (`_chain_frequency_calculation`)、通知送信を行います。失敗時にはリトライ回数とエラータイプに基づき `StateStore` の状態更新（`FAILED` または `PERMANENT_FAILED`）、通知送信、そして**リソースエラー時の自己修復** (`scheduler.reduce_workers`) を行います。
* **依存関係 (注入):**
    * `config` (ConfigParser): 設定情報へのアクセス。
    * `StateStore` (インスタンス): ジョブ状態の更新。
    * `NotificationThrottle` (インスタンス): 通知のレート制限。
    * `scheduler` (`JobScheduler` インスタンス, Setter注入): 振動数計算の連鎖起動のため。
* **主要メソッド:**
    * `handle_success(orca_path, mol_name, calc_type, work_dir, product_dir)`: 成功時の後処理を実行します。
    * `handle_failure(orca_path, mol_name, message, current_retries, error_type)`: 失敗時の後処理を実行します。エラータイプとリトライ回数で恒久失敗を判定します。
    * `_chain_frequency_calculation(mol_name, product_dir)`: OPT成功後にFREQ計算を起動します。
    * `set_scheduler(scheduler)`: `JobScheduler` インスタンスを後から設定します。

---

### 5. `StateStore`

* **モジュール:** `state_store.py`
* **役割:** すべてのジョブの状態（`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `PERMANENT_FAILED`）と**リトライ回数**を `state_store.json` ファイルに**永続化**します。起動時にJSONを読み込み、状態変更があるたびに書き込みます。
* **依存関係 (内部):**
    * `logging_utils`: ログ出力用。
* **主要メソッド:**
    * `add_job(mol_name, calc_type, orca_path, status='PENDING')`: ジョブを追加または更新（リトライ回数を保持）。新規時はリトライ回数を0に初期化します。
    * `update_status(job_id, status)`: ジョブの状態を更新します。
    * `has_pending_or_running(new_job_info)`: 同じ分子/計算タイプのジョブが待機中または実行中でないかチェックします。
    * `get_jobs_by_status(status)`: 指定された状態のジョブリストを取得します（起動時リカバリ用）。
    * `increment_retry_count(job_id)`: 指定されたジョブのリトライ回数を+1します。
    * `get_retry_count(job_id)`: 指定されたジョブの現在のリトライ回数を取得します。

---

### 6. `NotificationThrottle`

* **モジュール:** `notification_service.py`
* **役割:** 通知の**レート制限**を提供します。同じ件名の通知が短時間に連続して送信されるのを防ぎます。
* **依存関係:** なし
* **主要メソッド:**
    * `can_send(subject)`: 指定された件名の通知が現在送信可能かどうかを判定します。

---

### 7. `XYZHandler`

* **モジュール:** `file_watcher.py`
* **役割:** `watchdog` ライブラリと連携し、`input_dir` でのファイル作成イベントを監視します。新しい `.xyz` ファイルが検出されると、`.inp` ファイルを生成し、`JobScheduler.add_job` を呼び出して計算ジョブを登録します。
* **依存関係 (注入):**
    * `config` (ConfigParser): ディレクトリパスやORCA設定へのアクセス。
    * `job_manager` (`JobScheduler` インスタンス): 新規ジョブの登録先。
* **主要メソッド:**
    * `on_created(event)`: `watchdog` から呼び出されるイベントハンドラ。`.xyz` ファイルを処理します。

---

### 8. `MoldenService`

* **モジュール:** `molden_service.py`
* **役割:** メインの計算パイプラインとは**独立して**バックグラウンドで動作する**サイドカー**サービス。`state_store.json` を定期的に監視し、`COMPLETED` ステータスのジョブを見つけます。対応する `.gbw` ファイルが存在すれば、ORCA付属の `orca_2mkl` コマンドを実行して `.molden.input` ファイルを生成します。**無限リトライ防止**のための失敗マーカー管理機能も持ちます。
* **依存関係 (注入):**
    * `config` (ConfigParser): ディレクトリパスや `orca_2mkl` パスへのアクセス。
* **主要メソッド:**
    * `run()`: サービススレッドのメインループ。定期的に `check_completed_jobs` を呼び出します。
    * `stop()`: サービススレッドを安全に停止させます。
    * `check_completed_jobs()`: `state_store.json` を読み込み、処理対象の完了ジョブを探します。
    * `generate_molden_file(...)`: `orca_2mkl` コマンドを実行してMoldenファイルを生成します。
