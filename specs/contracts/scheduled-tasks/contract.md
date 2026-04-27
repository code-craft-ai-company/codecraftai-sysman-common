# Scheduled-Tasks Contract

This is the cross-OS abstract contract for the **scheduled-tasks**
feature. Every `automojo-sysman-*` package that ships a scheduled-
task manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-scheduled-tasks/`](../../../../../automojo-sysman-linux-redhat/specs/3-scheduled-tasks/).
It manages cron drop-ins under `/etc/cron.d/` and systemd timer +
service unit pairs through an `ICommandRunner` and an
`IFileOperator`. This contract generalises the verb set for OSes
whose native scheduling surface is launchd (macOS) or Task
Scheduler / `schtasks` (Windows).

---

## Scope

The scheduled-tasks feature provides idempotent, auditable control
over periodic or calendar-triggered task execution. It covers:

- Creating a task from a specification (schedule + command +
  environment + user).
- Deleting a task.
- Enabling or disabling a task.
- Running a task on demand.
- Querying a task's configuration and current state.
- Listing all tasks at a given owner scope.
- Dry-run-aware writes.
- Elevation for system-scope writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`
and, where the backing store is a file, an `IFileOperator`.

---

## Verbs

Every OS implementation MUST expose a `ScheduledTaskManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `create_task` | `(spec: TaskSpec) → ScheduledTaskActionResult` | Write |
| `delete_task` | `(name: str, owner: TaskOwner) → ScheduledTaskActionResult` | Write |
| `enable_task` | `(name: str, owner: TaskOwner) → ScheduledTaskActionResult` | Write |
| `disable_task` | `(name: str, owner: TaskOwner) → ScheduledTaskActionResult` | Write |
| `run_task_now` | `(name: str, owner: TaskOwner) → ScheduledTaskActionResult` | Write |
| `get_task` | `(name: str, owner: TaskOwner) → TaskInfo \| None` | Read |
| `list_tasks` | `(owner: TaskOwner) → list[TaskInfo]` | Read |
| `validate_schedule` | `(schedule: str) → bool` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `create_task` MUST compute the rendered
   native form of the spec and compare it to the existing task (if
   any); matching state MUST return `SKIPPED`. `delete_task` MUST
   return `SKIPPED` (or `FAILED` with a clear message, per OS spec)
   when the task does not exist. `enable_task` / `disable_task`
   MUST return `SKIPPED` when the task is already in the requested
   state.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner or file operator.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Create-with-enable semantics.** When `TaskSpec.enabled=True`,
   `create_task` MUST also enable the task; when `False`, the task
   MUST be created but not enabled. Failure to enable after
   successful creation MUST surface as `FAILED` with a `message`
   that identifies the step.
5. **Schedule validation.** `create_task` MUST validate the schedule
   string before any write. Invalid schedules MUST return `FAILED`
   with a descriptive `message` and no runner or file-operator
   calls.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` — except
   where the task store is owner-restricted and the caller is
   querying another user's scope. The OS spec MUST document any
   such exception.
2. **Typed errors.** `list_tasks` MUST raise
   `ScheduledTaskQueryError` for unexpected failures. `get_task`
   MUST return `None` for an unknown task.
3. **Pure parsing / pure validation.** `validate_schedule` MUST NOT
   invoke the runner or file operator and MUST be pure-Python
   syntactic validation.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `ScheduledTaskActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The operation ran and succeeded. |
| `FAILED` | The operation ran and failed, or a precondition was not met. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `TaskOwner` (enum)

| Value | Meaning |
|-------|---------|
| `SYSTEM` | Task runs as a system task (root / SYSTEM). |
| `USER` | Task runs in the context of a specific user. |

### `TaskSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Task name. Constrained to alphanumeric + hyphen by default. |
| `schedule` | `str` | Schedule string (cron expression, OnCalendar, StartCalendarInterval, Task Scheduler trigger). |
| `command` | `str` | The command to execute. |
| `arguments` | `list[str]` | Optional argv to append to `command`. |
| `working_dir` | `str \| None` | Working directory for execution. |
| `env` | `dict[str, str] \| None` | Environment overrides. |
| `user` | `str \| None` | User to run as. Required for `USER` owner on some OSes. |
| `owner` | `TaskOwner` | System vs user scope. |
| `enabled` | `bool` | Whether the task should be enabled after creation. |
| `description` | `str \| None` | Human-readable description. |

### `TaskInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Task name. |
| `owner` | `TaskOwner` | Owner scope. |
| `schedule` | `str \| None` | Schedule expression. |
| `command` | `str \| None` | Command. |
| `user` | `str \| None` | Running user. |
| `enabled` | `bool \| None` | Current enabled state. |
| `active` | `bool \| None` | Whether a run is currently in progress (where observable). |
| `last_run` | `datetime \| None` | Last run time when available. |
| `next_run` | `datetime \| None` | Next scheduled run when available. |
| `readable` | `bool` | `False` when the native entry exists but could not be parsed. |

### `ScheduledTaskActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `ScheduledTaskActionStatus` | Outcome category. |
| `name` | `str` | The task targeted. |
| `owner` | `TaskOwner` | Owner scope. |
| `message` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `ScheduledTaskQueryError` | `list_tasks` or an unexpected `get_task` failure (not "task not found"). |

### `ScheduledTaskManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, no mutations dispatch. |
| `elevated` | `bool` | `False` | When `True`, system-owner writes pass `elevated=True`. |
| `system_store_dir` | `str \| None` | OS-default | Override for the system-task backing store. |
| `user_store_dir` | `str \| None` | OS-default | Override for per-user task stores. |

---

## Owner-Scope Mapping

The abstract `TaskOwner` maps to each OS's native scope concept.

| OS | SYSTEM surface | USER surface | Notes |
|----|----------------|--------------|-------|
| Red Hat Enterprise Linux | `/etc/cron.d/<name>` drop-ins and `/etc/systemd/system/<name>.timer` + `.service` | `crontab -u <user>` entries and `~<user>/.config/systemd/user/` | The OS spec MUST state whether it prefers cron or systemd timers. |
| Ubuntu | Same as RHEL | Same as RHEL | — |
| macOS | `/Library/LaunchDaemons/<label>.plist` | `~<user>/Library/LaunchAgents/<label>.plist` | Schedule maps to `StartCalendarInterval` or `StartInterval`. |
| Windows | Task Scheduler root folder via `schtasks` / `Register-ScheduledTask` | Per-user task folder via the same tooling with `-User <user>` | Triggers use `TimeTrigger`, `DailyTrigger`, `CalendarTrigger`. |
| UEFI | N/A | N/A | UEFI has no persistent scheduler. The scheduled-tasks contract does not apply. |

Each OS spec MUST include an Owner-Scope-Mapping section stating
which native surface is used for each owner and how the spec is
rendered.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, system-owner write | Pass `elevated=True` to the runner and/or file operator. |
| Config `elevated=True`, user-owner write for the current user | Not required on most OSes; the OS spec MUST state the policy. |
| Config `elevated=True`, user-owner write for another user | Pass `elevated=True`. |
| Any read | Do NOT pass `elevated=True` unless the OS requires it for another user's scope. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, file operator, config
                ▼
        <Os>ScheduledTaskManager
                │
                ├── file operator → write task definition
                └── runner → enable/disable/run-now
                     │
                     ▼
          ICommandRunner  /  IFileOperator
                │
        ┌───────┴────────┐
        ▼                ▼
  Local{Command,File}Runner   SSH{Command,File}Runner
                         │
                  aspects compose here
                         │
                         ▼
        PersistenceAspect, RetryAspect, TimeoutAspect
```

All OS implementations MUST:

1. Accept an `ICommandRunner`, an `IFileOperator` (when the backing
   store is a file), and a `ScheduledTaskManagerConfig` in their
   constructor.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `ScheduledTaskManager` | `UbuntuScheduledTaskManager` | `MacosScheduledTaskManager` | `WindowsScheduledTaskManager` | `ScheduledTaskManager` |
| `ScheduledTaskManagerConfig` | `UbuntuScheduledTaskManagerConfig` | `MacosScheduledTaskManagerConfig` | `WindowsScheduledTaskManagerConfig` | `ScheduledTaskConfig` |
| `ScheduledTaskActionStatus` | `UbuntuScheduledTaskActionStatus` | `MacosScheduledTaskActionStatus` | `WindowsScheduledTaskActionStatus` | `ScheduledTaskActionStatus` |
| `ScheduledTaskActionResult` | `UbuntuScheduledTaskActionResult` | `MacosScheduledTaskActionResult` | `WindowsScheduledTaskActionResult` | `ScheduledTaskResult` |
| `TaskSpec` | `UbuntuTaskSpec` | `MacosTaskSpec` | `WindowsTaskSpec` | `CronJobEntry` / `SystemdTimerEntry` |
| `TaskInfo` | `UbuntuTaskInfo` | `MacosTaskInfo` | `WindowsTaskInfo` | `ScheduledTaskInfo` |
| `TaskOwner` | `UbuntuTaskOwner` | `MacosTaskOwner` | `WindowsTaskOwner` | `TaskType` (partial overlap) |
| `ScheduledTaskQueryError` | `UbuntuScheduledTaskQueryError` | `MacosScheduledTaskQueryError` | `WindowsScheduledTaskQueryError` | `ScheduledTaskQueryError` |

The RHEL package splits the spec into two types (`CronJobEntry` and
`SystemdTimerEntry`) because it exposes both scheduling backends.
New OS packages use a single unified `TaskSpec`.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `ScheduledTaskActionResult` sequence when driven
  by a real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb, per owner scope.
2. One idempotency test per write proving `SKIPPED` on matching
   state.
3. One invalid-schedule test proving `FAILED` with no runner /
   file-operator call.
4. One `list_tasks` parser test per owner scope.
5. One `get_task` test for a known task and an unknown task.
6. One `validate_schedule` test covering valid and invalid inputs,
   proving no runner / file-operator call.
7. One dry-run test per write verb proving no side effects occur.
8. One elevation test per scope proving writes pass `elevated=True`
   and reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Event-driven triggers (file-change, login, session-lock).
- Task-chaining / dependencies between tasks.
- Run-history querying beyond `last_run` / `next_run`.
- Concurrency control (max parallel instances).
- Resource-gated triggers (on-battery, on-ac-power, idle).
- XML task-definition authoring for Windows Task Scheduler beyond
  the minimum `TaskSpec` surface.
- launchd KeepAlive / RunAtLoad semantics beyond scheduled runs.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence is structural.** Ubuntu uses systemd
  timers as the primary scheduling backend (with cron as a
  reserved fallback under a `cron_backend=True` extension flag);
  macOS uses launchd plists under `LaunchDaemons` /
  `LaunchAgents` with `launchctl bootstrap` / `bootout` /
  `kickstart`; Windows uses Windows Task Scheduler via
  `Register-ScheduledTask` and friends. Each OS spec defines its
  own `validate_schedule` rules — OnCalendar + cron on Ubuntu,
  `StartCalendarInterval` / `StartInterval` on macOS,
  `New-ScheduledTaskTrigger` shapes on Windows.
- **`TaskOwner` mapping is per-OS.** Ubuntu maps `SYSTEM` to a
  system unit and `USER` to user-scoped systemd-user timers.
  macOS maps `SYSTEM` to `/Library/LaunchDaemons/` (`system`
  domain), `USER` to `~/Library/LaunchAgents/` (`gui/<uid>`
  domain) with a `launchctl asuser <uid>` wrapper when needed.
  Windows maps via the `-Principal` argument on
  `Register-ScheduledTask`.
- **File I/O via `ICommandRunner`.** systemd unit files, launchd
  plists, and the Windows scheduled-task XML imports route
  through the runner using `cat` / `tee` / `Get-Content` /
  `Set-Content` rather than a separate `IFileOperator`. See the
  README "Implementation Conventions" file-I/O section.
- **Read-shape returns `None`, not raises.** `get_task(name,
  owner)` returns `None` when the task is absent; `list_tasks`
  returns an empty list when no tasks exist. Per the README
  "Reads degrade gracefully" convention.
- **Windows `elevation_blocked: bool`.** `Register-ScheduledTask`
  / `Unregister-ScheduledTask` writes for SYSTEM-owner tasks
  surface the structured Windows elevation extension. See the
  README "Implementation Conventions" elevation-blocked entry.
