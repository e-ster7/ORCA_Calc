ご指摘の「つけっぱなし」運用上の課題に対する具体的なアプローチと、変更が必要なモジュールを以下に詳細に検討します。

-----

## 1\. 外部システムレベルの堅牢性

## 1.1. プロセス監視と自動再起動 

| 課題 | アプローチの検討と変更箇所 |
| :--- | :--- |
| **不足要素**：外部プロセス監視ツール | **アプローチ**：この課題は**コードの外部**（OSまたはコンテナレイヤー）で解決されるべきであり、Pythonコードの変更は最小限に留めます。|
| **変更モジュール** | **`main_coordinator_and_scheduler.py`**（最小限の変更） |
| **具体的なアクション** | 1. **コード側の準備:** スクリプトが外部プロセス監視ツール（例：`systemd`）によって実行されることを想定し、スクリプトの**終了コード**（Exit Code）がエラー時に確実に `1` などの非ゼロ値になるようにします。現在の `main` 関数では `sys.exit(1)` が含まれているため、この点はクリアされています。 2. **設定側の準備:** プロセス監視設定（例：`systemd` ユニットファイル）を作成し、パイプラインがクラッシュした場合に自動的に再起動するポリシー（`Restart=on-failure` など）を設定します。 |

-----

## 2\. 内部パイプラインの自己回復とレジリエンス

## 2.1. 状態のチェックと回復（コールドスタート） 

| 課題 | アプローチの検討と変更箇所 |
| :--- | :--- |
| **不足要素**：起動時の状態回復ロジック | **アプローチ**：`StateStore` のデータ構造を利用し、起動時に `RUNNING` 状態のジョブを検出し、キューに戻すロジックを**軸**に実装します。|
| **変更モジュール** | **`main_coordinator_and_scheduler.py`**（`main` 関数と `JobScheduler` の変更）、**`state_store.py`**（検索用メソッドの追加） |
| **具体的なアクション** | 1. **`state_store.py` (変更):** ステータスに基づいてジョブを検索するメソッド（例：`get_jobs_by_status(status)`）を追加します。 2. **`main_coordinator_and_scheduler.py` (変更):** <br>  a. `main` 関数内で `JobScheduler.start()` の直前に、`StateStore` をチェックするロジックを挿入します。<br>  b. `StateStore`から 'RUNNING' のジョブを取得し、それらを `JobScheduler.add_job()` に再度渡し、実行キューに戻します。このとき、`add_job` がジョブを 'RUNNING' から 'PENDING' に更新するようにします。 |

## 2.2. ネットワーク/API障害に対する高度なリトライ 

| 課題 | アプローチの検討と変更箇所 |
| :--- | :--- |
| **不足要素**：指数関数的バックオフを用いたリトライ | **アプローチ**：`send_notification` 関数にリトライロジックを直接組み込み、サービスの**堅牢性を高めます**。 |
| **変更モジュール** | **`notification_service.py`** |
| **具体的なアクション** | 1. **`notification_service.py` (変更):** <br>  a. `send_notification` 関数に**リトライループ**と**指数関数的バックオフ**（`time.sleep(2**i)` など）を実装します。<br>  b. **一時的なエラー**（`SMTPServerDisconnected`、`SMTPAuthenticationError`以外の一般的な`SMTPException`や`socket.timeout`など）のみを捕捉し、リトライ対象とします。<br>  c. **恒久的なエラー**（認証失敗など）はリトライせずにログに記録し、失敗として処理します。 |

## 2.3. ジョブの恒久的な失敗判定

| 課題 | アプローチの検討と変更箇所 |
| :--- | :--- |
| **不足要素**：最大リトライ回数の設定 | **アプローチ**：`StateStore`でリトライ回数を追跡し、**ジョブ実行の開始時**（`OrcaExecutor`）および**失敗時**（`JobCompletionHandler`）に回数を更新・チェックします。|
| **変更モジュール** | **`state_store.py`**、**`orca_executor.py`**、**`job_handler.py`** |
| **具体的なアクション** | 1. **`state_store.py` (変更):** <br>  a. `add_job` のデータ構造に `retry_count` (初期値 0) を追加します。<br>  b. `increment_retry_count(job_id)` メソッドを追加します。 2. **`config.txt` (新規設定):** `[pipeline]`セクションなどに `max_retries = 3` の設定を追加します。 3. **`orca_executor.py` (変更):** <br>  a. 実行前に `StateStore` から `retry_count` を取得し、最大値を超えていないかチェックします。<br>  b. 実行失敗時、`handler.handle_failure()` を呼び出す前に、`StateStore` のリトライ回数をインクリメントします。 4. **`job_handler.py` (変更):** `handle_failure` の中で、リトライ回数が最大値を超えた場合、`StateStore` のステータスを **`PERMANENT_FAILED`** に更新するように処理を分岐させます。 |

-----

## 3\. 運用とメンテナンス

## 3.1. ログローテーションとアーカイブ 

| 課題 | アプローチの検討と変更箇所 |
| :--- | :--- |
| **不足要素**：ログローテーション機能 | **アプローチ**：`logging_utils.py` のロギングハンドラを標準の `FileHandler` から、自動ローテーション機能を持つ `TimedRotatingFileHandler` に置き換えます。|
| **変更モジュール** | **`logging_utils.py`**、**`pipeline_utils.py`** |
| **具体的なアクション** | 1. **`pipeline_utils.py` (変更):** `log_filename` 定数をファイル名パターン（例：`orca_pipeline.log`）に変更し、ユニークなタイムスタンプの組み込みを削除します。 2. **`logging_utils.py` (変更):** <br>  a. `logging.FileHandler` を `logging.handlers.TimedRotatingFileHandler` に変更します。<br>  b. ローテーション間隔（例：`when='D', interval=1, backupCount=7` で毎日ローテーション、7世代保持）を設定に追加します。 |

## 3.2. 一時ファイルと作業ディレクトリのクリーンアップ

| 課題 | アプローチの検討と変更箇所 |
| :--- | :--- |
| **不足要素**：ガベージコレクション（GC）機能 | **アプローチ**：一時ファイルが不要になる**最終段階**であるジョブハンドリングの**直後**に、作業ディレクトリを削除します。|
| **変更モジュール** | **`orca_executor.py`**（`finally` ブロックの変更） |
| **具体的なアクション** | 1. **`orca_executor.py` (変更):** <br>  a. `execute` メソッド内の `finally` ブロックに、`shutil.rmtree(work_dir, ignore_errors=True)` を追加します。<br>  b. `work_dir` 内で必要なファイル（最終出力や中間ファイルなど）が全て `product_dir` にコピーされた**後**に、このクリーンアップが実行されることを保証します。（現在の実装では `_handle_success` が `shutil.copy` を実行しているため、`finally` の前に `shutil.copy` が完了していることを確認する必要がありますが、`JobHandler` にロジックを委任しているため、`finally` に配置するのが最も安全です。） |
