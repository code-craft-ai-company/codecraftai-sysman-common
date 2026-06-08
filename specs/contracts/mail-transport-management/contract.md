# Mail-Transport-Management Contract

This is the cross-OS abstract contract for the
**mail-transport-management** feature. Every `codecraftai-sysman-*`
package that ships a mail-transport manager MUST honor this
contract.

The reference implementation is
[`codecraftai-sysman-linux-redhat/specs/3-mail-transport-management/`](../../../../../codecraftai-sysman-linux-redhat/specs/3-mail-transport-management/).
It wraps `postconf`, `postmap`, `newaliases`, `postqueue`, `mailq`,
and `postsuper` against a Postfix MTA and manages `/etc/aliases`
and `/etc/postfix/main.cf`. This contract generalises the verb set
for OSes whose MTA story is Postfix on macOS (shipped with the OS)
or an SMTP relay on Windows (where there is no built-in MTA
equivalent after the deprecation of the IIS SMTP feature).

> **Windows availability.** The default Windows implementation
> MUST return `FAILED` with `detail="no MTA installed"` for every
> verb unless a supported MTA (hMailServer, MailEnable, IIS SMTP
> on Server SKUs) is detected and explicitly selected via the
> OS-specific config. The Windows spec MUST document the detection
> and selection procedure.

---

## Scope

The mail-transport-management feature provides idempotent,
auditable control over the host's mail transport agent. It covers:

- Reading and mutating MTA daemon configuration (main directives).
- Managing local alias maps.
- Sending a probe message to validate delivery.
- Inspecting and draining the deferred / active queue.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate.

The feature is executed exclusively through an `ICommandRunner`.
Implementations MAY use an `IFileOperator` for alias and map
files; the established cross-OS pattern is to route file I/O
through `ICommandRunner` using OS-native file utilities. See the
README "Implementation Conventions".

---

## Verbs

Every OS implementation MUST expose a `MailTransportManager` class
(the OS-prefixed variant — see §Naming) whose public surface is
the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `get_mta_config` | `() → MailTransportConfig` | Read |
| `set_mta_config` | `(spec: MailTransportConfig) → MailActionResult` | Write |
| `add_alias` | `(local: str, remote: str) → MailActionResult` | Write |
| `remove_alias` | `(local: str) → MailActionResult` | Write |
| `list_aliases` | `() → list[MailAlias]` | Read |
| `test_mail_delivery` | `(to: str, from_: str, subject: str) → MailActionResult` | Write |
| `get_queue_status` | `() → MailQueueStatus` | Read |
| `flush_queue` | `() → MailActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `set_mta_config` MUST read current
   directives and return `SKIPPED` when the rendered spec matches.
   `add_alias` MUST return `SKIPPED` when the `(local, remote)`
   pair is already present. `remove_alias` MUST return `SKIPPED`
   when no entry exists for `local`. `test_mail_delivery` and
   `flush_queue` are operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return `DRY_RUN`
   without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated. Writes
   do NOT raise.
4. **Aliases database rebuild.** `add_alias` and `remove_alias`
   MUST rebuild the native aliases database (e.g., `newaliases` on
   Postfix) on `SUCCESS`. If the rebuild fails, the write MUST
   return `FAILED` even when the text mutation succeeded.
5. **MTA-unavailable.** When no supported MTA is installed, every
   write MUST return `FAILED` with `detail="no MTA installed"`.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` to the
   runner.
2. **Typed errors.** Query failures MAY raise `MailQueryError`
   carrying exit code and stderr, OR (per the per-OS spec)
   return an empty list / synthetic record so callers can
   proceed without a try/except wrapper. A system with no MTA
   installed MUST cause `get_mta_config` to raise
   `MailQueryError` with a `detail="no MTA installed"` marker
   (or, on Windows, return `FAILED` with stable detail token
   `windows_no_built_in_mta`). See the README "Implementation
   Conventions" graceful-read pattern and stable-token catalog.
3. **Pure parsing.** Output parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enum,
each prefixed with the OS name (see §Naming).

### `MailActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or no MTA is installed. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `MailActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `MailActionStatus` | Outcome category. |
| `action` | `str` | Short identifier (e.g., `"set_config"`, `"add_alias:root"`). |
| `detail` | `str \| None` | Human-readable explanation. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### `MailTransportConfig` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `hostname` | `str` | Host name the MTA presents on SMTP. |
| `origin` | `str` | Mail-origin domain (`$myorigin` on Postfix). |
| `relay_host` | `str \| None` | Upstream relay, if any. |
| `listen_interfaces` | `list[str]` | Interfaces or addresses the MTA binds to. |
| `inet_protocols` | `list[str]` | e.g., `["ipv4"]`, `["ipv4", "ipv6"]`. |
| `extra_directives` | `dict[str, str]` | OS-specific extra key/value directives. |

### `MailAlias` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `local` | `str` | Local mailbox alias (left-hand side). |
| `remote` | `str` | Target address list (comma-separated, right-hand side). |

### `MailQueueStatus` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `active_count` | `int` | Number of active messages. |
| `deferred_count` | `int` | Number of deferred messages. |
| `hold_count` | `int` | Number of messages on hold. |
| `total_bytes` | `int` | Aggregate bytes in the queue. |
| `oldest_age_seconds` | `int \| None` | Age of the oldest message, or `None` if empty. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `MailQueryError` | A read fails unexpectedly, or no MTA is installed. |

### `MailTransportManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, mutations short-circuit. |
| `elevated` | `bool` | `True` | When `True`, writes pass `elevated=True`. Default is `True` because MTA configuration nearly always requires root. |

---

## MTA Mapping

Mail transport has no natural scope parameter — a host runs at
most one MTA. The abstract verbs map to each OS's default MTA.

| OS | Default MTA | Notes |
|----|-------------|-------|
| Red Hat Enterprise Linux | Postfix | Canonical. `postconf`, `postqueue`, `newaliases`, `/etc/aliases`, `/etc/postfix/main.cf`. |
| Ubuntu | Postfix (may also be `exim4` or `sendmail`) | The Ubuntu spec MUST document MTA selection. Behavior for non-Postfix MTAs is an extension. |
| macOS | Postfix (shipped with the OS, frequently disabled) | The macOS spec MUST document that the Postfix daemon is present but typically not running; `lifecycle` delegation is the responsibility of the service-management feature. |
| Windows | No built-in MTA | Default implementation returns `FAILED` / raises `MailQueryError`. Third-party MTAs (hMailServer, MailEnable) are extensions. |
| UEFI | N/A | UEFI has no mail subsystem. The mail-transport-management contract does not apply. |

Each OS spec MUST include an MTA-Mapping section describing the
default MTA, the configuration file paths used, and the
"no-MTA-installed" detection procedure.

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
        <Os>MailTransportManager
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

1. Accept an `ICommandRunner` (and MAY accept an `IFileOperator`
   for alias and map files; the established pattern is to route
   file I/O through the runner) and a
   `MailTransportManagerConfig` in their constructor.
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
| `MailTransportManager` | `UbuntuMailTransportManager` | `MacosMailTransportManager` | `WindowsMailTransportManager` | `MailTransportManager` |
| `MailTransportManagerConfig` | `UbuntuMailTransportManagerConfig` | `MacosMailTransportManagerConfig` | `WindowsMailTransportManagerConfig` | `MailTransportManagerConfig` |
| `MailActionStatus` | `UbuntuMailActionStatus` | `MacosMailActionStatus` | `WindowsMailActionStatus` | `MailActionStatus` |
| `MailActionResult` | `UbuntuMailActionResult` | `MacosMailActionResult` | `WindowsMailActionResult` | `MailActionResult` |
| `MailTransportConfig` | `UbuntuMailTransportConfig` | `MacosMailTransportConfig` | `WindowsMailTransportConfig` | `MainCfDirectives` |
| `MailAlias` | `UbuntuMailAlias` | `MacosMailAlias` | `WindowsMailAlias` | `AliasEntry` |
| `MailQueueStatus` | `UbuntuMailQueueStatus` | `MacosMailQueueStatus` | `WindowsMailQueueStatus` | `MailQueueStatus` |
| `MailQueryError` | `UbuntuMailQueryError` | `MacosMailQueryError` | `WindowsMailQueryError` | `MailQueryError` |

The RHEL reference uses Postfix-specific names
(`MainCfDirectives`, `AliasEntry`); new OS packages use the
abstract names.

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `MailActionResult` sequence when driven by a
  real runner with aspects attached, modulo retry-induced timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test per applicable write verb proving `SKIPPED`
   on matching state.
3. One `get_mta_config` parser test covering a representative
   output sample.
4. One `list_aliases` parser test covering multiple alias entries.
5. One `test_mail_delivery` test proving correct payload
   construction.
6. One `get_queue_status` parser test covering a representative
   queue dump.
7. One dry-run test per write verb proving the runner is not
   invoked.
8. One elevation test proving writes pass `elevated=True` and reads
   do not, when configured.
9. One "MTA unavailable" test on Windows proving the documented
   `FAILED` / `MailQueryError` path.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Virtual domains and transport maps.
- TLS key / certificate material for SMTP+TLS (delegated to
  `certificate-issuance` and `certificate-trust-management`).
- SASL authentication setup.
- Greylisting, anti-spam / anti-virus integration.
- Per-message tracing beyond `test_mail_delivery`.
- IMAP / POP delivery integration (Dovecot, Cyrus).
- Mailbox format selection (Maildir vs mbox).
- `master.cf` per-service directive mutation (RHEL extension only).

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **`detail="windows_no_built_in_mta"`.** Windows ships no
  built-in MTA comparable to Postfix / sendmail; the Windows
  manager returns `FAILED` with this stable detail token for
  every write verb. See the README stable-token catalog.
- **`detail="windows_iis_smtp_aliases_unsupported"`.** Where
  IIS SMTP is the only available transport, alias-map writes
  return `FAILED` with this stable detail token because IIS
  SMTP does not implement Postfix-style alias maps.
- **Backend divergence.** Ubuntu wraps Postfix
  (`postconf` / `postmap` / `postfix reload`); macOS wraps
  Postfix or `sendmail` (`launchctl` for the daemon); Windows
  is largely a no-op. Per-OS `MailTransportConfig` shapes carry
  backend-specific fields.
- **Naming overrides.** Ubuntu uses `UbuntuMailTransportConfig`
  with a `postfix_main_cf_path` field; macOS uses
  `MacosMailTransportConfig` with a `launchd_label` field. See
  the README concrete-implementation naming convention.
