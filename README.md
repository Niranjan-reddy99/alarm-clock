# Alarm Clock CLI

A robust, minimal alarm clock for the terminal. Built for developers who live in the CLI.

This project was built as a take-home assignment focusing on engineering judgment, clean architecture, testability, and responsible AI-assisted development.

---

## 🌟 Features

- **Natural Language Parsing**: Add alarms using phrases like `"in 10 minutes"`, `"tomorrow 7am"`, or `"8:30 PM"`.
- **Missed Alarm Detection**: If you close your terminal or your laptop goes to sleep, any alarms that should have fired while the application was off will be detected and displayed on your next run.
- **Robust State Machine**: Alarms transition cleanly through `PENDING` ➔ `RINGING` ➔ `DISMISSED` or `MISSED`.
- **Interactive Snooze**: Optional snooze capability. Unattended alarms auto-timeout gracefully after 60 seconds without blocking the scheduler.
- **Atomic Persistence**: Alarms are saved to a local JSON file. Atomic writes guarantee your data is never corrupted, even if the application is killed mid-write.

---

## 🚀 Installation & Usage

### Prerequisites
- Python 3.10+
- macOS or Linux (Timeout handling uses POSIX `select.select()`)

### Setup
```bash
git clone https://github.com/Niranjan-reddy99/alarm-clock.git
cd alarm-clock
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Commands

**Add an alarm**
```bash
python main.py add "8:30 PM" "Workout"
python main.py add "in 10 minutes" "Meeting"
```

**Add an alarm with snooze** (e.g., 5 minutes)
```bash
python main.py add "tomorrow 7am" "Morning Run" --snooze 5
```

**List all alarms**
```bash
python main.py list
```

**Delete an alarm**
```bash
python main.py delete 1
```

**Start the scheduler**
```bash
python main.py run
```
*Note: Keep this running in a dedicated terminal pane or tab.*

---

## 🏗 Architecture & Project Structure

The codebase is built strictly around **Separation of Concerns**. The core domain is entirely decoupled from I/O operations (Terminal / File System).

```text
alarm-clock/
├── src/
│   ├── constants.py     # Centralized configuration (magic numbers/paths)
│   ├── models.py        # Domain model (Alarm entity) & State Machine rules
│   ├── storage.py       # JSON persistence layer (CRUD, atomic writes)
│   ├── parser.py        # Natural language parsing (dateparser)
│   ├── notifier.py      # Terminal UI rendering and 60-second interactive prompts
│   ├── scheduler.py     # Orchestration loop & startup recovery
│   └── cli.py           # argparse wiring and command routing
├── tests/               # Comprehensive pytest suite (124 tests)
├── alarms.json          # Data store (auto-created on first use)
└── main.py              # Application entry point
```

### Alarm Lifecycle (State Machine)
Every state change is strictly enforced via `Alarm.transition()` in `models.py`.

```text
                     [add alarm]
                         ↓
                      PENDING
                         ↓  scheduler detects due time
                      RINGING
                    /         \
          [D] Dismiss      [S] Snooze (if --snooze was set)
               ↓                   ↓
          DISMISSED            PENDING  ← (new time = now + snooze)
                    
               RINGING
                  ↓  60-second timeout (no user response)
               MISSED
               
    On scheduler startup:
    PENDING + time in the past  →  MISSED  (displayed, not interactive)
```

---

## 🤔 Design Decisions & Tradeoffs

**1. JSON Storage over SQLite**
*Tradeoff:* JSON is less robust under concurrent writes and lacks query capability.
*Decision:* For a single-user CLI application, JSON is human-readable, debuggable, and requires no schema migrations. Adding SQLite would be premature optimization. To mitigate JSON's primary flaw, we implemented **atomic writes** (`os.replace()`) to prevent corruption.

**2. Polling Loop over Asyncio**
*Tradeoff:* Polling uses a thread-blocking `time.sleep(1)`. Asyncio offers superior I/O concurrency.
*Decision:* The problem domain (an alarm clock) requires roughly 1-second precision, not sub-millisecond I/O scaling. A simple `while True` loop is vastly easier to test and reason about than an event loop, with zero functional downsides for this use case.

**3. Sequential Processing (No Threads)**
*Tradeoff:* When an alarm rings, the prompt blocks the scheduler for up to 60 seconds. A second alarm due in that window is delayed.
*Decision:* We prioritize simplicity. Introducing threading for concurrent alarm prompts in a terminal creates rendering collisions (two banners fighting for stdout) and race conditions. A sequential design is correct and predictable.

**4. 60-Second Timeout via `select.select()`**
*Tradeoff:* Using `select` on `sys.stdin` is POSIX-only, meaning this CLI does not support Windows natively without WSL.
*Decision:* The requirements mandated a 60-second timeout on user input without using threads or asyncio. `select.select()` is the standard POSIX way to accomplish this.

**5. Minute-Level Uniqueness**
*Decision:* We strip seconds and microseconds from user input. `8:30 PM` and `8:30:15 PM` are treated as a collision. This drastically simplifies the scheduling logic and aligns with how humans actually think about alarms.

---

## 🧪 Testing

The project uses `pytest` and boasts a suite of **124 tests**.

**Run the tests:**
```bash
pytest -v
```

**Testing Strategy:**
- **Domain Tests (`test_models.py`)**: Validates every possible state transition and edge case around due/overdue semantics.
- **Persistence Tests (`test_storage.py`)**: Operates on isolated `tmp_path` files to verify CRUD operations, ID auto-incrementing, and atomic writes.
- **Integration Tests (`test_scheduler.py`)**: Uses `unittest.mock.patch` on `prompt_user` to simulate user input, testing the full lifecycle without blocking on actual terminal I/O. 
- **Critical Path Validation**: Tests explicitly verify that a ringing alarm is written to disk *before* the user prompt is shown, ensuring crash recovery.

---

## 🤖 How AI Was Used

AI was utilized as a pair-programming partner to implement this project efficiently while maintaining high standards.

- **Human**: Defined the problem scope, established the 7 core design decisions (e.g., minute-level uniqueness, sequential processing, explicit MISSED states), dictated the strict separation of concerns, and directed the phase-by-phase implementation.
- **AI (DeepMind Antigravity)**: Generated the boilerplate code, wrote the comprehensive docstrings, implemented the POSIX `select.select()` pattern for the timeout requirement, and generated the expansive `pytest` suite covering the edge cases defined by the human.
- **Human**: Reviewed the generated code file-by-file for architectural compliance, challenged the AI on concurrency patterns (enforcing a strict no-threading rule), ran manual smoke tests, and authored the final README narrative.

*In short: Human provided the engineering judgment and constraints; AI provided the velocity.*

---

## 🔮 Future Improvements

If given another 48 hours, the following features would be evaluated for inclusion:
1. **Cron-style Recurrence**: Support for "Every weekday at 7 AM". This requires a significant overhaul of the state machine, as an alarm would transition from `DISMISSED` back to `PENDING` with a newly calculated target time.
2. **Daemonization**: Running the scheduler in the background (via `launchd` on macOS or `systemd` on Linux) so the user doesn't need to keep a terminal tab open.
3. **OS Notifications**: Integrating with `osascript` (macOS) or `notify-send` (Linux) to trigger native system notifications alongside the terminal banner.
4. **Data Pruning**: A `clean` command (or auto-pruning) to remove `DISMISSED` and `MISSED` alarms older than 30 days to prevent the JSON file from growing indefinitely.
