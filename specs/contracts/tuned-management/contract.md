# Tuned-Management Contract

This is the cross-OS abstract contract for the
**tuned-management** feature. Every `automojo-sysman-*` package
that ships a tuned manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-tuned-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-tuned-management/).
It wraps `tuned-adm`, `tuned.service`, and profile directories
under `/etc/tuned/` and `/usr/lib/tuned/` through an
`ICommandRunner`.

> **RHEL-primary feature.**
> - Ubuntu MAY implement this contract if the `tuned` package is
>   installed. Absent the package, every verb MUST return `FAILED`
>   or raise `TunedUnavailableError` per the OS spec.
> - macOS and Windows have no tuned equivalent. Their
>   implementations MAY:
>     - return `FAILED` with `detail="tuned is not available on
>       <os>."` for every verb, or
>     - synthesise profile semantics by delegating to OS-native
>       tuning (`powercfg` on Windows, `pmset` on macOS) with a
>       fixed, documented profile name mapping.
>   The OS spec MUST pick one strategy and document it exhaustively.

---

## Scope

The tuned-management feature provides idempotent, auditable
control over a host's system-wide performance profile. It covers:

- Listing available profiles.
- Querying the currently active profile.
- Setting the active profile.
- Creating and deleting user-defined profiles.
- Reloading the active profile.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`
and an `IFileOperator` (for user-profile directory entries).

---

## Verbs

Every OS implementation MUST expose a `TunedManager` class (the
OS-prefixed variant — see §Naming) whose public surface is the
following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `list_profiles` | `() → list[TunedProfile]` | Read |
| `get_active_profile` | `() → TunedProfile \| None` | Read |
| `set_active_profile` | `(name: str) → TunedActionResult` | Write |
| `create_profile` | `(spec: TunedProfileSpec) → TunedActionResult` | Write |
| `delete_profile` | `(name: str) → TunedActionResult` | Write |
| `reload_profile` | `() → TunedActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `set_active_profile` MUST return
   `SKIPPED` when the named profile is already active.
   `create_profile` MUST return `SKIPPED` when a profile with the
   same name and identical rendered content exists.
   `delete_profile` MUST return `SKIPPED` when no such profile
   exists. `reload_profile` is operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner or writing profile files.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Built-in protection.** `delete_profile` MUST return `FAILED`
   for any profile that originates from the OS's built-in
   profile directory (`/usr/lib/tuned/` on RHEL). Only user
   profiles under `/etc/tuned/` are deletable.
5. **Platform-unsupported writes.** On OSes without a tuned
   backend that chose the `FAILED` strategy, writes MUST return
   `FAILED` with a descriptive `detail`.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** Query failures MUST raise `TunedQueryError`
   for unexpected failures. A system with tuned installed but no
   active profile MUST cause `get_active_profile` to return
   `None` rather than raise.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `TunedActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or tuned is unavailable. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `TunedProfile` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Profile name. |
| `origin` | `str` | `"builtin"` (under `/usr/lib/tuned/`) or `"user"` (under `/etc/tuned/`) or the OS equivalent. |
| `description` | `str \| None` | Human-readable description. |
| `summary` | `str \| None` | Short summary line. |

### `TunedProfileSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `name` | `str` | Profile name. |
| `parent` | `str \| None` | Optional parent profile to inherit from. |
| `description` | `str \| None` | Description for the profile. |
| `settings` | `dict[str, dict[str, str]]` | Section → key → value map (e.g., `{"cpu": {"governor": "performance"}}`). |

### `TunedActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `TunedActionStatus` | Outcome category. |
| `profile_name` | `str \| None` | The profile targeted, or `None` for `reload_profile`. |
| `detail` | `str \| None` | Human-readable explanation. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `TunedQueryError` | A read fails for a reason other than "no active profile". |
| `TunedUnavailableError` | An OS implementation chooses the raising strategy and tuned is unavailable. |

### `TunedManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `True` | When `True`, writes pass `elevated=True`. |

---

## Profile Mapping

The abstract `name` parameter maps to each OS's native profile /
power-plan identifier.

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `tuned-adm` profile | Canonical. Built-in under `/usr/lib/tuned/`, user under `/etc/tuned/`. |
| Ubuntu | Same as RHEL when `tuned` is installed | Otherwise OPTIONAL. |
| macOS | `pmset` + `pmset -a customize` | Profile names map to a documented fixed set (`balanced`, `performance`, `powersave`) synthesising `pmset` presets. `create_profile` / `delete_profile` MAY return `FAILED`. |
| Windows | `powercfg` power plan GUIDs | Profile names map to a documented fixed set. Custom profile creation via `powercfg -duplicatescheme` is an extension. |
| UEFI | N/A | The tuned-management contract does not apply. |

Each OS spec MUST include a Profile-Mapping section stating its
chosen strategy and any fixed name-to-native-plan mapping.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL / Ubuntu / macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>TunedManager
                │
                │  .run(argv, elevated=…, capture_output=True)
                ▼
          ICommandRunner
                │
        ┌───────┴────────┐
        ▼                ▼
  LocalCommandRunner   SSHCommandRunner
        │                │
        └────────┬───────┘
                 │  aspects compose here
                 ▼
        PersistenceAspect, RetryAspect, TimeoutAspect
```

All OS implementations MUST:

1. Accept an `ICommandRunner`, an `IFileOperator`, and a
   `TunedManagerConfig` in their constructor.
2. Never construct their own subprocess or file access.
3. Not hold state across calls beyond the injected collaborators
   and the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `TunedManager` | `UbuntuTunedManager` | `MacosTunedManager` | `WindowsTunedManager` | `TunedManager` |
| `TunedManagerConfig` | `UbuntuTunedManagerConfig` | `MacosTunedManagerConfig` | `WindowsTunedManagerConfig` | `TunedManagerConfig` |
| `TunedActionStatus` | `UbuntuTunedActionStatus` | `MacosTunedActionStatus` | `WindowsTunedActionStatus` | `TunedActionStatus` |
| `TunedActionResult` | `UbuntuTunedActionResult` | `MacosTunedActionResult` | `WindowsTunedActionResult` | `TunedActionResult` |
| `TunedProfile` | `UbuntuTunedProfile` | `MacosTunedProfile` | `WindowsTunedProfile` | `TunedProfile` |
| `TunedProfileSpec` | `UbuntuTunedProfileSpec` | `MacosTunedProfileSpec` | `WindowsTunedProfileSpec` | `TunedProfileSpec` |
| `TunedQueryError` | `UbuntuTunedQueryError` | `MacosTunedQueryError` | `WindowsTunedQueryError` | `TunedQueryError` |
| `TunedUnavailableError` | `UbuntuTunedUnavailableError` | `MacosTunedUnavailableError` | `WindowsTunedUnavailableError` | `TunedUnavailableError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `TunedActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per applicable write verb proving
   `SKIPPED` on matching state.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `list_profiles` parser test covering multiple profiles
   including both built-in and user origins.
5. One `get_active_profile` test for a system with and without an
   active profile.
6. One `delete_profile` protection test proving `FAILED` for a
   built-in profile.
7. For OPTIONAL-OS implementations that chose `FAILED`: one test
   per verb proving the unsupported path. For implementations
   that chose delegation: one test per documented profile name
   proving correct `powercfg` / `pmset` invocation.
8. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Per-device tuning script authoring inside a profile.
- Dynamic profile selection (`tuned` recommend mode).
- Realtime kernel tuning integrations.
- NUMA-balancing knobs beyond what a profile exposes.
- Power-plan GUID management on Windows.
- macOS `nvram` boot-arg power tuning.
- Profile inheritance graph validation beyond a single parent.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **No cross-OS implementations exist.** This contract is
  RHEL-primary by design; the `tuned` daemon, `tuned-adm`, and
  the per-profile `tuned.conf` model have no native analog on
  macOS or Windows, and Ubuntu hosts only ship the daemon when
  the operator opts into the package. Per-OS implementations on
  Ubuntu / macOS / Windows would return `FAILED` with stable
  detail tokens of the form `unsupported_on_host_os_<host>`
  documented in the contract — see the README "FAILED with
  stable detail token" convention and stable-detail-token
  catalog.
- **File I/O via `ICommandRunner`.** Any future Ubuntu
  implementation building on the `tuned` package would route
  custom-profile `tuned.conf` reads and writes through the
  runner using `cat` / `tee` rather than a separate
  `IFileOperator`, per the README "Implementation Conventions"
  file-I/O section.
