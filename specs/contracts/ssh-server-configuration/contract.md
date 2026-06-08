# SSH-Server-Configuration Contract

This is the cross-OS abstract contract for the
**ssh-server-configuration** feature. Every `codecraftai-sysman-*`
package that ships an SSH-server-configuration manager MUST honor
this contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-ssh-server-configuration/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-ssh-server-configuration/).
It uses OpenSSH `sshd`, `sshd -t`, and `/etc/ssh/sshd_config`
through an `ICommandRunner` and an `IFileOperator`. OpenSSH ships
on all three supported OSes (`/etc/ssh/sshd_config` on Linux /
macOS; `%ProgramData%\ssh\sshd_config` on Windows), so this
contract is straightforward across OSes aside from the config
path and service-reload mechanism.

---

## Scope

The ssh-server-configuration feature provides idempotent,
auditable control over a host's `sshd` configuration. It covers:

- Reading, setting, and removing named `sshd_config` keywords.
- Listing all configured keywords.
- Adding, removing, and listing `Match` blocks.
- Reloading and validating `sshd` configuration.
- Managing a user's `~/.ssh/authorized_keys` entries.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`
and an `IFileOperator` (for `sshd_config` and
`authorized_keys`).

---

## Verbs

Every OS implementation MUST expose an `SshServerManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `get_sshd_setting` | `(keyword: str) → SshdSetting \| None` | Read |
| `set_sshd_setting` | `(keyword: str, value: str) → SshdActionResult` | Write |
| `remove_sshd_setting` | `(keyword: str) → SshdActionResult` | Write |
| `list_sshd_settings` | `() → list[SshdSetting]` | Read |
| `add_match_block` | `(criteria: str, settings: dict[str, str]) → SshdActionResult` | Write |
| `remove_match_block` | `(criteria: str) → SshdActionResult` | Write |
| `list_match_blocks` | `() → list[SshdMatchBlock]` | Read |
| `reload_sshd` | `() → SshdActionResult` | Write |
| `test_sshd_config` | `() → SshdTestResult` | Read |
| `list_authorized_keys` | `(user: str) → list[AuthorizedKey]` | Read |
| `add_authorized_key` | `(user: str, key: str) → SshdActionResult` | Write |
| `remove_authorized_key` | `(user: str, fingerprint: str) → SshdActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `set_sshd_setting` MUST read the current
   value and return `SKIPPED` when it already matches.
   `remove_sshd_setting` MUST return `SKIPPED` when the keyword is
   absent. `add_match_block` MUST return `SKIPPED` when a matching
   block with identical rendered content already exists.
   `remove_match_block` MUST return `SKIPPED` when no such block
   exists. `add_authorized_key` MUST return `SKIPPED` when an
   entry with the same fingerprint is already present;
   `remove_authorized_key` MUST return `SKIPPED` when no entry
   has the given fingerprint. `reload_sshd` is operational and
   MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner or writing the config.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Pre-reload validation.** Every write that modifies
   `sshd_config` MUST run `sshd -t` (or the OS equivalent) before
   writing. If validation fails, the write MUST return `FAILED`
   with the validator's stderr and MUST NOT persist the change.
5. **Key-format validation.** `add_authorized_key` MUST validate
   that the supplied key is a parseable OpenSSH public-key line
   before writing, and MUST return `FAILED` with a descriptive
   `detail` on parse failure.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner. `list_authorized_keys` for a user other than the
   caller MAY elevate if the OS spec documents the policy.
2. **Typed errors.** Query failures MUST raise `SshdQueryError`
   for unexpected failures. An unknown keyword or user MUST
   return `None` / empty list rather than raise.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `SshdActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or validation failed. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `SshdSetting` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `keyword` | `str` | The `sshd_config` keyword. |
| `value` | `str` | The configured value. |
| `source_line` | `int \| None` | Line number in the config file where the setting appears. |

### `SshdMatchBlock` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `criteria` | `str` | The full `Match` criteria string (e.g., `"User alice Address 10.0.0.0/8"`). |
| `settings` | `dict[str, str]` | Keyword → value settings inside the block. |
| `source_line` | `int \| None` | Line number where the block starts. |

### `AuthorizedKey` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `key_type` | `str` | e.g., `"ssh-ed25519"`, `"ssh-rsa"`. |
| `key_body` | `str` | The base64-encoded key body. |
| `comment` | `str \| None` | Optional comment / label from the end of the line. |
| `fingerprint` | `str` | SHA-256 fingerprint (OpenSSH format). |
| `options` | `str \| None` | Optional per-key options prefix. |

### `SshdActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `SshdActionStatus` | Outcome category. |
| `action` | `str` | Short identifier (e.g., `"set:PermitRootLogin"`). |
| `detail` | `str \| None` | Human-readable explanation. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `SshdTestResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `valid` | `bool` | Whether the configuration passed `sshd -t`. |
| `messages` | `list[str]` | Validator messages. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `SshdQueryError` | A read fails for a reason other than "keyword unknown" / "user unknown". |

### `SshServerManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `True` | When `True`, writes pass `elevated=True`. |
| `sshd_config_path` | `str` | OS-specific | Path to `sshd_config`. |

---

## Keyword Mapping

The abstract `keyword` parameter is an OpenSSH `sshd_config`
keyword. Keyword semantics are uniform across OSes; only the
config path and reload mechanism differ.

| OS | Config path | Reload mechanism |
|----|-------------|------------------|
| Red Hat Enterprise Linux | `/etc/ssh/sshd_config` | `systemctl reload sshd` |
| Ubuntu | `/etc/ssh/sshd_config` | `systemctl reload ssh` (service name differs) |
| macOS | `/etc/ssh/sshd_config` | `launchctl kickstart -k system/com.openssh.sshd` |
| Windows | `%ProgramData%\ssh\sshd_config` | `Restart-Service sshd` |
| UEFI | N/A | UEFI has no SSH server. The ssh-server-configuration contract does not apply. |

Each OS spec MUST include a Keyword-Mapping section stating its
default config path and reload command.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| `list_authorized_keys(user=other)` | OS-specific; the spec MUST state whether elevation is used. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL / Ubuntu / macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                ▼
        <Os>SshServerManager
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

1. Accept an `ICommandRunner`, an `IFileOperator`, and an
   `SshServerManagerConfig` in their constructor.
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
| `SshServerManager` | `UbuntuSshServerManager` | `MacosSshServerManager` | `WindowsSshServerManager` | `SshServerManager` |
| `SshServerManagerConfig` | `UbuntuSshServerManagerConfig` | `MacosSshServerManagerConfig` | `WindowsSshServerManagerConfig` | `SshServerManagerConfig` |
| `SshdActionStatus` | `UbuntuSshdActionStatus` | `MacosSshdActionStatus` | `WindowsSshdActionStatus` | `SshdActionStatus` |
| `SshdActionResult` | `UbuntuSshdActionResult` | `MacosSshdActionResult` | `WindowsSshdActionResult` | `SshdActionResult` |
| `SshdSetting` | `UbuntuSshdSetting` | `MacosSshdSetting` | `WindowsSshdSetting` | `SshdDirective` |
| `SshdMatchBlock` | `UbuntuSshdMatchBlock` | `MacosSshdMatchBlock` | `WindowsSshdMatchBlock` | `SshdMatchBlock` |
| `AuthorizedKey` | `UbuntuAuthorizedKey` | `MacosAuthorizedKey` | `WindowsAuthorizedKey` | `AuthorizedKey` |
| `SshdTestResult` | `UbuntuSshdTestResult` | `MacosSshdTestResult` | `WindowsSshdTestResult` | `SshdTestResult` |
| `SshdQueryError` | `UbuntuSshdQueryError` | `MacosSshdQueryError` | `WindowsSshdQueryError` | `SshdQueryError` |

The RHEL reference uses `SshdDirective`; new OS packages use
`SshdSetting`.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `SshdActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per write verb proving `SKIPPED` on
   matching state.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One pre-reload validation failure test proving `FAILED` when
   `sshd -t` rejects the change.
5. One `list_sshd_settings` parser test covering multiple
   keywords.
6. One `add_match_block` / `remove_match_block` round-trip test.
7. One `list_authorized_keys` parser test covering multiple key
   types and key options.
8. One `add_authorized_key` key-format-validation failure test.
9. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Host-key generation and rotation.
- Certificate-based SSH host / user certificate issuance
  (delegated to `certificate-issuance`).
- SSH client configuration (`ssh_config`).
- `known_hosts` management.
- `sshd` service lifecycle — lives in `service-management`.
- PAM integration for SSH authentication.
- `authorized_keys` command-restriction policies beyond the
  `options` field on `AuthorizedKey`.
- SELinux / AppArmor profile wiring for `sshd`.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Stock OpenSSH on every host, but config paths and reload
  surfaces diverge.** Ubuntu and macOS both keep `sshd_config`
  at `/etc/ssh/sshd_config`; Windows keeps it at
  `C:\ProgramData\ssh\sshd_config`. Reload routes through
  `systemctl reload ssh` on Ubuntu, `launchctl kickstart -k
  system/com.openssh.sshd` on macOS, and
  `Restart-Service -Name 'sshd'` on Windows. The verb surface
  is identical; the argv shapes are not.
- **`test_sshd_config` is universal but binary names differ.**
  Ubuntu and macOS dispatch `sshd -t`; Windows dispatches
  `sshd.exe -t`. Each per-OS spec resolves the binary path
  through its `service_name` / `sshd_path` config fields rather
  than assuming `$PATH`.
- **File I/O via `ICommandRunner`.** `sshd_config` reads,
  writes, and `Match` block edits route through the runner
  using `cat` / `tee` (Ubuntu / macOS) and `Get-Content` /
  `Set-Content` (Windows) rather than a separate
  `IFileOperator`. `authorized_keys` reads do likewise. See the
  README "Implementation Conventions" file-I/O section.
- **Read-shape returns sentinels, not raises.**
  `get_sshd_setting(keyword)` returns `None` when the keyword
  is unset rather than raising; `list_match_blocks` returns an
  empty list when no `Match` blocks are present. Per the README
  "Reads degrade gracefully" convention.
- **Windows `elevation_blocked: bool`.** `sshd_config` writes
  under `C:\ProgramData\ssh\` and `Restart-Service` against the
  `sshd` service surface the structured Windows elevation
  extension. See the README "Implementation Conventions"
  elevation-blocked entry.
