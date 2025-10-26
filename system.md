

## 📘 Class Documentation (Revised Architecture)

| Class Name | Module | Role and Purpose | Dependencies (Injected) | Key Methods |
| :--- | :--- | :--- | :--- | :--- |
| **JobScheduler** | `main_coordinator_and_scheduler.py` | The **core root** of the pipeline. Manages job reception (`add_job`), the worker queue, thread lifecycle (`start`, `shutdown`), and delegates all execution logic. | `config`, `StateStore`, `OrcaExecutor` | `start()`, `shutdown()`, `add_job()`, `join()` |
| **ThreadWorker** | `main_coordinator_and_scheduler.py` | Executes the job from the queue by calling the **injected** `OrcaExecutor` instance via `JobScheduler`. | `job_queue`, `JobScheduler` (instance) | `run()`, `stop()` |
| **OrcaExecutor** | `orca_executor.py` | **Single Responsibility:** Executes the ORCA subprocess, manages working directories, checks output, and reports the result (**success/failure**) to the injected `JobCompletionHandler`. | `config`, `JobCompletionHandler` (instance) | `execute(inp_file, mol_name, calc_type)` |
| **JobCompletionHandler** | `job_handler.py` | **Single Responsibility:** Handles all post-execution logic, including file movement, plotting, notifications, and **chaining** (e.g., opt to freq). | `config`, `StateStore`, `NotificationThrottle`, `JobScheduler` (instance) | `handle_success()`, `handle_failure()`, `_chain_frequency_calculation()`, `set_scheduler()` |
| **StateStore** | `state_store.py` | Manages the persistent state of all jobs (`state_store.json`). | (None internal, depends on `logging_utils` for logging) | `add_job()`, `update_status()`, `has_pending_or_running()` |
| **NotificationThrottle** | `notification_service.py` | Provides rate limiting for email notifications based on a time interval. | (None) | `can_send(subject)` |
| **XYZHandler** | `file_watcher.py` | Handles `watchdog` events for new `.xyz` files and calls `JobScheduler.add_job` to submit the new task. | `config`, `JobScheduler` (instance) | `on_created(event)` |

***

## 🛠️ Function and Method Documentation (Revised Architecture)

### A. Core Scheduling (`main_coordinator_and_scheduler.py`)

| Name | Type | Role and Detail | Arguments | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| `start` | Method | **(JobScheduler)** Initializes and starts the configured number of `ThreadWorker` threads. Sets the internal state `is_running` to `True`. | None | `ThreadWorker` |
| `shutdown` | Method | **(JobScheduler)** Gracefully stops all active `ThreadWorker` threads by setting their `running` flag to `False`. | None | `ThreadWorker.stop()` |
| `add_job` | Method | **(JobScheduler)** Validates the job against `StateStore` for duplicates, updates the state to 'PENDING', and enqueues the job for execution. | `inp_file` (str), `mol_name` (str), `calc_type` (str) | `StateStore.has_pending_or_running`, `StateStore.add_job` |
| `execute` | Method | **(OrcaExecutor)** **Called by** `ThreadWorker` via `JobScheduler`. Executes the ORCA subprocess and uses `check_orca_output` to determine success or failure, delegating the result to the injected `JobCompletionHandler`. | `inp_file`, `mol_name`, `calc_type` | `JobCompletionHandler.handle_success`, `JobCompletionHandler.handle_failure`, `orca_utils.check_orca_output` |

### B. Job Handling (`job_handler.py`)

| Name | Type | Role and Detail | Arguments | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| `set_scheduler` | Method | **(JobCompletionHandler)** Used for **Setter Injection** to break the circular dependency (`Handler` needs `Scheduler` for chaining, `Scheduler` needs `Executor` which needs `Handler`). | `scheduler` (`JobScheduler` instance) | (None) |
| `handle_success` | Method | **(JobCompletionHandler)** Post-execution logic for success: copies output, updates `StateStore`, calls plotting functions, calls `_chain_frequency_calculation`, and sends notification. | `orca_path`, `mol_name`, `calc_type`, `work_dir`, `product_dir` | `StateStore.update_status`, `notification_service.send_notification`, `orca_utils` (plotting) |
| `handle_failure` | Method | **(JobCompletionHandler)** Post-execution logic for failure: updates `StateStore` with the error message and sends a notification. | `orca_path`, `mol_name`, `message` | `StateStore.update_status`, `notification_service.send_notification` |
| `_chain_frequency_calculation`| Method | **(JobCompletionHandler, Internal)** Logic for extracting the final geometry from an optimized job and creating a new 'freq' job, which is submitted back to the `JobScheduler`. | `mol_name`, `product_dir` | `orca_utils.extract_final_structure`, `orca_utils.generate_orca_input`, `pipeline_utils.safe_write`, `JobScheduler.add_job` |

### C. ORCA Utilities (`orca_utils.py`)

| Name | Type | Role and Detail | Arguments | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| **generate_orca_input**| Function | Creates the string content for an ORCA `.inp` file based on configuration and coordinates. | `config`, `mol_name`, `atoms` (list), `coords` (list of list), `calc_type` (str) | (None) |
| **check_orca_output**| Function | Parses the ORCA `.out` file to verify if the run terminated normally and if optimization converged. | `output_path` (Path) | (None) |
| **extract_final_structure**| Function | Searches the ORCA output for the "FINAL COORDINATES" block and returns the extracted geometry. | `output_path` (Path) | (None) |
| **generate_energy_plot**| Function | Generates and saves a Matplotlib plot of energy convergence data from the ORCA output. | `output_path` (Path), `save_dir` (Path) | `matplotlib` (conditional import) |

### D. File Watching (`file_watcher.py`)

| Name | Type | Role and Detail | Arguments | Dependencies |
| :--- | :--- | :--- | :--- | :--- |
| **process_existing_xyz_files**| Function | Called once at pipeline startup. Scans the input directory for existing `.xyz` files, generates `.inp` files, and submits them to the scheduler. | `config`, `job_manager` (`JobScheduler` instance) | `orca_utils.parse_xyz`, `orca_utils.generate_orca_input`, `pipeline_utils.safe_write`, `JobScheduler.add_job` |
| `on_created` | Method | **(XYZHandler)** Handles the `watchdog` event for a new file creation. Copies the new `.xyz` file, converts it to an `.inp`, and submits the job. | `event` (`watchdog.events.FileCreatedEvent`) | `orca_utils.parse_xyz`, `orca_utils.generate_orca_input`, `pipeline_utils.safe_write`, `JobScheduler.add_job` |

### E. Other Utility Modules

| Name | Type | Role and Detail | Arguments |
| :--- | :--- | :--- | :--- |
| **load_config** | Function | **(`config_utils.py`)** Loads configuration from `config.txt`. | `config_path` (str) |
| **send_notification**| Function | **(`notification_service.py`)** Sends an email via Gmail, checking the injected `NotificationThrottle`. | `config`, `subject`, `body`, `throttle_instance` |
| **safe_write** | Function | **(`pipeline_utils.py`)** Safely writes file content, ensuring parent directories exist. | `path` (Path/str), `content` (str) |
| **get_logger** | Function | **(`logging_utils.py`)** Returns a named `logging.Logger` instance. | `name` (str) |
