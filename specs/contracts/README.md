# Sysman Contracts

This folder contains **cross-OS abstract contracts** that the
`automojo-sysman-*` packages implement. A contract defines, for a given
feature area (firewall management, service management, package
management, …), the verbs, return types, invariants, and execution
model that every OS-specific implementation must honor.

The contracts live in the dedicated `automojo-sysman-common`
package, separate from `automojo-interfaces` (which is reserved
for low-level cross-cutting Python protocols like
`ICommandRunner` and `IFileOperator`). `automojo-sysman-common`
is the shared foundation for every per-OS sysman package and
hosts both these contracts and the shared `featurebase.py`
module they all extend.

## Why a contract layer?

The `automojo-sysman-linux-redhat` package is the canonical
implementation reference. Its spec architecture — layer-numbered
folders (`1-`, `2-`, `3-`), `requirements.md` / `design.md` /
`tasks.md` per feature, idempotent operations expressed through an
`ICommandRunner` — is being replicated across the
`automojo-sysman-linux-ubuntu`, `automojo-sysman-macos`,
`automojo-sysman-windows`, and (narrower) `automojo-sysman-uefi`
packages.

Without a shared contract the four packages would drift:

- Different method names for the same verb (`add_service()` vs
  `allow_service()`).
- Different result-status vocabularies (`SKIPPED` vs `NOOP` vs
  `ALREADY_PRESENT`).
- Different expectations for dry-run, elevation, and error surfaces.
- Different parameter orderings and optional-parameter semantics.

The contract locks those decisions at the suite level. Per-OS specs
then describe only what is OS-specific: the native tools invoked, the
command strings constructed, the output parsers, and any feature gaps.

## What a contract specifies

Each contract document defines:

1. **Verbs** — the public methods every OS implementation must expose
   for the feature, with signatures in abstract (non-OS-specific) form.
2. **Result type shape** — the dataclass fields and enum values for
   the action and query result types, in a form every implementation
   can return.
3. **Status vocabulary** — the canonical set of statuses
   (`SUCCESS`, `FAILED`, `SKIPPED`, `DRY_RUN`, and any feature-specific
   additions) that every implementation uses.
4. **Invariants** — cross-OS behavior guarantees: dry-run short-
   circuits all writes; idempotency guards read current state before
   acting; elevation is applied only to writes; query methods never
   elevate.
5. **Zone / profile / anchor mapping** — for features whose abstract
   verb takes a scoping parameter that does not map one-to-one across
   OSes (firewall zones, process cgroup scopes, service units), the
   contract defines the abstract parameter and each OS maps it to its
   native concept.
6. **Execution model** — how the feature uses `ICommandRunner`, how
   aspects (persistence, retry, timeout) compose, and what is
   permitted to bypass the runner (typically: nothing).

## What a contract does NOT specify

- The exact command strings. Those are OS-specific and live in each
  per-OS `design.md`.
- The on-disk configuration file layout (e.g., `/etc/pf.conf`,
  Windows Firewall registry paths, ufw `/etc/ufw/`).
- Testing details — each OS implementation chooses its own fixture
  inputs, though they all use a `MockCommandRunner`.

## Implementation Conventions

The conventions in this section are universal patterns that emerged
across five waves of Phase 3 implementation work (75 cross-OS feature
implementations across Ubuntu, macOS, and Windows, plus 5 UEFI
features). Each pattern was discovered when the original contract
language collided with implementation reality on at least one OS, and
was then adopted by every other implementation that touched the same
seam.

The conventions take precedence over older contract language that
contradicts them. When a contract still says "use `IFileOperator`" or
"reads MUST raise on failure", treat the convention here as the
authoritative version. Contributors writing new contracts should
encode these conventions from the start.

### 1. `ICommandRunner` is the file-I/O seam

Every cross-OS implementation routes file I/O through `ICommandRunner`
using OS-native file utilities — `cat`, `tee`, `rm`, `mv`, `mkdir`,
`chmod`, `chown` on POSIX hosts; `Get-Content`, `Set-Content`,
`Out-File`, `Add-Content`, `Remove-Item`, `Move-Item` (typically
inside a `powershell.exe -Command` invocation) on Windows. No
concrete `IFileOperator` exists in the ecosystem today, and the
established pattern has been to keep file I/O on the same runner the
manager already injects.

The original contract language (frequently "uses an `IFileOperator`
extension") was authored speculatively before the runner-only
convention solidified. Going forward, contracts MAY reference
`IFileOperator` as an option, but the established pattern is:

> File I/O MAY use `IFileOperator` if the host package provides one;
> the established pattern is to route file I/O through
> `ICommandRunner` using OS-native file utilities.

Contributors writing a new manager should follow the runner-only
pattern unless they have a specific reason to reach for a different
seam.

### 2. `command: list[str] | None` field on action results

Every per-OS `*ActionResult` dataclass carries a
`command: list[str] | None` field that records the argv that was (or
would have been) executed. This field is populated by the
`featurebase._dispatch` helper that every manager uses to invoke the
runner; it is set on `SUCCESS`, `FAILED`, and `DRY_RUN` results and
is `None` only on `SKIPPED` results that short-circuit before
construction of the argv.

The field does NOT appear on the upstream
`automojo.interfaces.icommandrunner.RunResult` — it is a convenience
for callers that want to log, replay, or diff the exact argv without
re-deriving it from `detail`. Contracts whose data-model tables omit
`command` SHOULD be read as if `command` were present; new contracts
MUST list it as a standard optional field on every action-result
dataclass.

### 3. `requires_reboot: bool` on action results that mutate boot-time-only state

Several features mutate state that the kernel / firmware / OS only
re-reads at boot time: Windows hostname rename via `Rename-Computer`,
Windows kernel-parameters via `bcdedit`, Windows BitLocker enablement,
UEFI capsule-update staging, and a handful of others. The convention
is for the `*ActionResult` to carry a
`requires_reboot: bool = False` field; the manager sets it to `True`
when the underlying tool reports the change was staged but a reboot
is required for the change to take effect.

Contracts whose action-result tables predate this convention SHOULD
treat the field as optional / additive. New contracts MUST include
`requires_reboot` on any action-result type whose feature mutates
boot-time-only state.

### 4. OS-prefixed concrete type names

OS-specific implementations prefix every public type with the OS
name in PascalCase: `UbuntuFirewallManager`,
`MacosFirewallManager`, `WindowsFirewallManager`, and (for the
firmware contracts) `UefiBootManager`,
`UefiCapsuleUpdateManager`, etc. The RHEL reference package retains
unprefixed names for historical reasons; every new package
prefixes.

This is what allows a coordinator that spans mixed-OS fleets to
import all four packages without alias-collision. Contracts whose
Naming sections do not yet enumerate the prefix variants SHOULD be
read as if they did.

### 5. `FAILED` with a stable detail token for unsupported (host_os, verb) combos

When a feature has no scriptable implementation on a given host OS
(e.g., Linux LUKS volume-listing on macOS, Windows hostname rename on
the UEFI shell, BIOS-mode firmware capsule-update on a system without
UEFI runtime services), the manager returns `*ActionResult` with
`status=FAILED` and `detail` populated with a short, stable,
machine-readable token. The token uses lowercase-with-underscores and
is designed to be `grep`-able in logs and diffable across runs.

This convention replaces the older "raise NotImplementedError"
suggestion that appeared in some early contracts. `NotImplementedError`
makes a coordinator's life harder: it forces every caller to wrap
manager calls in `try`/`except`, and it loses the structured
context (config, runner state, attempted argv) that the action-result
shape preserves. The token-based pattern keeps the result shape
uniform and gives callers a stable predicate to skip-or-fail on.

See the catalog at the end of this section for the canonical token
strings.

### 6. `elevation_blocked: bool` on Windows `RunResult`

The Windows `LocalCommandRunner` pre-detects elevation status using
`ctypes.windll.shell32.IsUserAnAdmin()`. When a manager passes
`elevated=True` but the calling process is not running with an
elevated token, the runner short-circuits, returns a `RunResult`
with `status=FAILED` and an additional `elevation_blocked=True`
field, and never invokes the underlying command.

This is a Windows-only extension to `RunResult`; POSIX runners do not
carry it. Contracts that mention elevation SHOULD acknowledge that
the Windows surface includes this extra field. Managers SHOULD pass
the field through onto the corresponding action-result `detail`
field (commonly as `detail="elevation_blocked"`) so coordinators can
distinguish elevation failures from real command failures without
parsing stderr.

### 7. Reads degrade gracefully; raising is the exception, not the rule

Several early contracts said "reads MUST raise `*QueryError` on
failure". Implementation reality is that most read paths return a
None / empty / synthetic record on failure rather than raise:
`get_mounts()` returns an empty list when the mount-listing tool is
absent; `stat_file()` returns `None` when the path does not exist;
`get_realm_status()` returns a `RealmStatus(joined=False, ...)`
synthetic record when the realm-discovery tool reports the host is
not joined; `query_state()` for a firewall returns
`FirewallState(running=False, ...)` when the daemon is off.

The convention is:

> Read methods MAY raise `*QueryError` OR return a None / empty /
> synthetic record per the per-OS spec. Whichever the per-OS spec
> picks, it MUST be consistent across the read surface and MUST be
> documented.

Cross-OS callers handle both shapes via the `*QueryError` Union and
the documented sentinel records. New contracts SHOULD write reads as
"MAY raise" rather than "MUST raise".

### 8. Per-OS backend enums

Several features ship a single abstract concept on the contract
(e.g., `BackupKind`, `VirtBackend`, `ContainerEngine`) that
diverges into OS-specific enums in practice: `UbuntuBackupKind`
(rsync, restic, duplicity), `MacosBackupKind` (Time Machine,
rsync), `WindowsBackupKind` (wbadmin, Restore Points);
`UbuntuVirtBackend` (libvirt/KVM), `MacosVirtBackend` (HyperKit
deprecated, Virtualization.framework), `WindowsVirtBackend`
(Hyper-V); and similar splits for container engines, mail
transports, and storage backends.

The convention is that each OS spec defines its own backend enum
with the OS prefix and lists the values that are actually realisable
on that OS. The contract's abstract enum (when one exists) is treated
as an aspirational union — it does not need to enumerate every
per-OS value, and an OS implementation does NOT need to implement an
enum value just because the contract lists it.

### 9. Concrete-implementation naming overrides

A pattern exists where the contract uses a clean abstract name
(`SystemIdentity`, `MailTransportConfig`, `BootEntry`,
`AclSet` / `AclEntry` / `AclPrincipal`) while the per-OS
implementation prefers a name that fits the rest of its package
(`UbuntuHostIdentity`, `UbuntuMailTransportConfig`,
`UbuntuBootEntryInfo`, `UbuntuAclInfo` / `UbuntuAceInfo` /
`UbuntuAceSpec`). The field shapes also occasionally diverge — the
per-OS dataclass collapses two contract fields into one, splits
read-shape vs write-shape, or drops a contract field that has no
native analog.

The convention is to allow the divergence and surface it in a
"Concrete-Implementation Notes" subsection on the affected contract.
The contract retains the abstract names for cross-OS code; the per-OS
spec documents what the concrete names are and how they map. Cross-OS
adapter layers (when they materialise) translate at the boundary.

### 10. UEFI managers carry an `override_host_os` config field

Every UEFI manager (`UefiBootManager`,
`UefiCapsuleUpdateManager`, `UefiEfiVariableManager`,
`UefiEspManager`, `UefiSecureBootManager`) carries an
`override_host_os: str | None = None` field on its config dataclass.
When set, the manager treats the host as if it were the named OS for
the purpose of selecting backend tools (e.g., `efibootmgr` on
Linux-flavored hosts, `bcdedit` on Windows). When `None`, the
manager auto-detects via `platform.system()`.

This field is testability infrastructure — it lets the suite drive
the manager through every backend on a single host without spinning
up multiple VMs. Contracts for UEFI features SHOULD list it as a
standard config field. Cross-OS contracts (non-UEFI) MAY adopt the
same idiom but typically do not need to.

### 11. Elevation-model inversion when the underlying tool refuses root

A handful of features wrap tools that explicitly refuse to run as
root: Homebrew on macOS (`package-management`, `repository-management`)
prints a hard error and exits when invoked under `sudo`. The
convention for these features is to permanently pass `elevated=False`
to the runner and instead wrap the argv with
`sudo -u <brew_user>` (or the OS-equivalent run-as-user mechanism)
when a write needs to happen on a host whose calling process IS
elevated.

This inverts the standard "writes elevate" rule. Contracts whose
write surface intersects with a tool that refuses root MUST document
the inversion in their Implementation Drift section, and per-OS
implementations MUST enforce the inversion via property tests
(typically `test_brew_never_elevates_even_when_config_elevated`).
The inversion is permitted; silent elevation that the tool then
rejects is not.

### 12. Plaintext-credential argv-leak avoidance

Several features take a credential parameter (passwords for
`user-group-management.set_password`, passphrases for
`encryption-management.unlock_volume`, bind passwords for
`identity-management.join_realm`). The convention for credential
delivery to the runner is, in order of preference:

1. **Stdin** (Ubuntu `chpasswd`, Linux `cryptsetup luksOpen`,
   `realm join --user`): the credential is piped on stdin and
   never appears in argv. The runner's `command` field on the
   resulting `*ActionResult` is argv-only, so logs and replays
   carry no plaintext.
2. **In-process secure-string** (Windows
   `ConvertTo-SecureString -AsPlainText -Force`): the credential
   is converted inside the PowerShell scriptblock and never reaches
   the OS-level argv. Logs see the conversion call but not the
   plaintext.
3. **Argv (last resort)** (macOS `sysadminctl -password`,
   `dsconfigad -password`): the credential lands in argv because
   the tool refuses any other channel. Per-OS specs MUST document
   the argv-leak risk explicitly and managers MUST sanitise the
   recorded `command` field via a `_sanitise_argv_passwords` helper
   that replaces the password value with `<redacted>`.

Contracts that take credentials SHOULD note which delivery channel
each per-OS implementation uses. New features that take credentials
MUST follow the preference order; if the preferred channel is not
available on a given host, the per-OS spec MUST document why and
implement the redaction helper.

### Stable detail-token catalog

Implementers depend on the following tokens being grep-able and
stable across releases. New tokens MUST follow the
`lowercase_with_underscores` form and SHOULD encode the OS family
or the specific limitation (not a sentence). The list below is the
catalog of tokens currently emitted by Phase 3 implementations:

| Token | Meaning |
|-------|---------|
| `unsupported_on_host_os_<host>` | The (verb, host) combination is not implementable on the named host OS (e.g., `unsupported_on_host_os_darwin`). |
| `firmware_setup_ui_only` | The action requires firmware-setup UI interaction and cannot be scripted. |
| `firmware_downgrade_blocked` | Firmware-rollback is blocked by capsule version-lock policy. |
| `apfs_no_quota_support` | APFS volumes do not expose user/group quotas natively. |
| `windows_no_built_in_mta` | Windows ships no built-in mail-transport agent comparable to Postfix / sendmail. |
| `windows_no_powershell_io_limit` | Windows Job Objects do not expose per-job I/O bandwidth caps via PowerShell. |
| `windows_no_powershell_job_object_memory_limit` | Windows Job Objects do not expose per-job memory caps via PowerShell at this binding level. |
| `windows_no_kdump_concept` | Windows has no `kdump` analog; crash dumps go through MEMORY.DMP / minidump policy instead. |
| `windows_iis_smtp_aliases_unsupported` | The IIS SMTP server does not implement Postfix-style alias maps. |
| `attribute_preservation_read_failed` | A pre-write read needed to preserve filesystem attributes (xattr / ACL / ADS) failed. |
| `destructive_operation_requires_explicit_confirm` | The verb refused to act because the destructive-confirm flag was not set. |
| `macos_no_per_group_cpu_limit` | macOS launchd / cgroup-v2 substitute lacks per-group CPU caps. |
| `macos_no_per_group_io_limit` | macOS lacks per-group block-I/O caps. |
| `parameter_not_supported` | The named parameter is not implemented on the current backend. |
| `unknown_timezone_id` | The supplied timezone identifier did not resolve to an OS-known zone. |
| `hyperkit_deprecated` | macOS HyperKit is deprecated; the manager refused the requested backend. |
| `pswindowsupdate_required` | The Windows update path requires the `PSWindowsUpdate` PowerShell module which is not installed. |
| `unsupported_target_kind` | The verb does not implement the supplied target-kind. |
| `homebrew_no_disable_untap_required` | Homebrew offers no per-tap "disabled" state; the manager refused and recommended `untap`. |
| `not_set` | The queried key is unset; returned as `detail` on a successful read that found no value. |
| `elevation_blocked` | Windows-only; the runner refused the call because the process is not elevated. |

The catalog is intentionally kept short and grep-able. When a new
unsupported-combo emerges in Phase 4 work, prefer adding a new entry
here over inventing a one-off token in a single per-OS spec.

## How a per-OS spec references the contract

Each per-OS feature spec (e.g.,
`automojo-sysman-linux-ubuntu/specs/3-firewall-management/`) opens
with a reference to the contract:

```markdown
This spec implements the firewall-management contract defined at
`automojo-interfaces/specs/sysman-contracts/firewall-management/contract.md`
for Ubuntu (and Debian-family) Linux hosts using `ufw`.
```

The per-OS `design.md` then only needs to cover:

- The OS-specific command mappings.
- Output parsing for OS-specific tool output.
- Any feature gaps or deviations from the contract (explicitly flagged).
- OS-specific error conditions.

## Current contracts

All 43 RHEL layer-3 feature areas have cross-OS contracts, plus 5
UEFI-firmware-specific contracts, plus the Layer 1/2 foundations.
50 contracts total.

### Layer 1 — Infrastructure

| Feature | Contract | Scope parameter |
|---------|----------|-----------------|
| command-execution | [`command-execution/contract.md`](command-execution/contract.md) | none |

### Layer 2 — Data

| Feature | Contract | Scope parameter |
|---------|----------|-----------------|
| maintenance-reporting | [`maintenance-reporting/contract.md`](maintenance-reporting/contract.md) | none |

### Layer 3 — Business Logic

| Feature | Contract | Scope parameter | Platform notes |
|---------|----------|-----------------|----------------|
| acl-management | [`acl-management/contract.md`](acl-management/contract.md) | filesystem path | — |
| audit-management | [`audit-management/contract.md`](audit-management/contract.md) | audit-rule identifier | — |
| authentication-management | [`authentication-management/contract.md`](authentication-management/contract.md) | PAM service / LSA package | — |
| backup-restore | [`backup-restore/contract.md`](backup-restore/contract.md) | backup spec | OS semantics diverge; `BackupKind` carries per-OS fallbacks |
| boot-management | [`boot-management/contract.md`](boot-management/contract.md) | boot entry ID | **UEFI firmware** boot entries (distinct from bootloader-management) |
| bootloader-management | [`bootloader-management/contract.md`](bootloader-management/contract.md) | bootloader config + entry ID | GRUB / systemd-boot / BCD / Apple bootloader |
| capsule-update | [`capsule-update/contract.md`](capsule-update/contract.md) | device identifier (GUID) | UEFI firmware updates |
| certificate-issuance | [`certificate-issuance/contract.md`](certificate-issuance/contract.md) | certificate subject / alias | — |
| certificate-trust-management | [`certificate-trust-management/contract.md`](certificate-trust-management/contract.md) | trust store name | — |
| cockpit-management | [`cockpit-management/contract.md`](cockpit-management/contract.md) | Cockpit module name | **RHEL-primary**; macOS/Windows MAY return `FAILED` |
| configuration-management | [`configuration-management/contract.md`](configuration-management/contract.md) | config source (path / plist / registry / NVRAM) | — |
| container-management | [`container-management/contract.md`](container-management/contract.md) | container engine | Docker / Podman / containerd / Docker Desktop |
| dns-server-management | [`dns-server-management/contract.md`](dns-server-management/contract.md) | zone name | BIND / dnsmasq / Windows DNS Server |
| efi-variables | [`efi-variables/contract.md`](efi-variables/contract.md) | variable namespace (GUID / alias) | UEFI NVRAM variables |
| encryption-management | [`encryption-management/contract.md`](encryption-management/contract.md) | volume / device | LUKS / FileVault / BitLocker |
| environment-configuration | [`environment-configuration/contract.md`](environment-configuration/contract.md) | `EnvScope` (SYSTEM / USER) | — |
| esp-management | [`esp-management/contract.md`](esp-management/contract.md) | none (one ESP per host) | EFI System Partition access |
| filesystem-management | [`filesystem-management/contract.md`](filesystem-management/contract.md) | none | — |
| filesystem-quotas | [`filesystem-quotas/contract.md`](filesystem-quotas/contract.md) | mountpoint + user/group | — |
| firewall-management | [`firewall-management/contract.md`](firewall-management/contract.md) | zone / profile / anchor | — |
| hardware-inventory | [`hardware-inventory/contract.md`](hardware-inventory/contract.md) | none | Read-only feature; drops `DRY_RUN` status |
| identity-management | [`identity-management/contract.md`](identity-management/contract.md) | realm / domain | FreeIPA / AD |
| insights-management | [`insights-management/contract.md`](insights-management/contract.md) | — | **RHEL-only**; other OSes MAY `NotImplementedError` |
| kdump-management | [`kdump-management/contract.md`](kdump-management/contract.md) | dump target | **Linux-primary**; macOS/Windows map to native crash facilities |
| kernel-parameters | [`kernel-parameters/contract.md`](kernel-parameters/contract.md) | none | — |
| localization-management | [`localization-management/contract.md`](localization-management/contract.md) | none | — |
| log-management | [`log-management/contract.md`](log-management/contract.md) | log source identifier | — |
| mail-transport-management | [`mail-transport-management/contract.md`](mail-transport-management/contract.md) | none | Windows lacks built-in MTA — defaults to `FAILED` |
| network-configuration | [`network-configuration/contract.md`](network-configuration/contract.md) | interface name | — |
| nfs-server-management | [`nfs-server-management/contract.md`](nfs-server-management/contract.md) | export path | — |
| package-management | [`package-management/contract.md`](package-management/contract.md) | none | — |
| precision-time-management | [`precision-time-management/contract.md`](precision-time-management/contract.md) | none | chrony / ntpd / w32tm |
| process-management | [`process-management/contract.md`](process-management/contract.md) | PID or process name | — |
| remote-log-forwarding | [`remote-log-forwarding/contract.md`](remote-log-forwarding/contract.md) | forwarding destination | macOS cannot support `TLS` transport natively |
| repository-management | [`repository-management/contract.md`](repository-management/contract.md) | repository name | — |
| resource-control-management | [`resource-control-management/contract.md`](resource-control-management/contract.md) | resource-control group name | cgroups / launchd limits / Job Objects |
| samba-server-management | [`samba-server-management/contract.md`](samba-server-management/contract.md) | SMB share name | — |
| scheduled-tasks | [`scheduled-tasks/contract.md`](scheduled-tasks/contract.md) | `TaskOwner` (SYSTEM / USER) | — |
| secure-boot | [`secure-boot/contract.md`](secure-boot/contract.md) | key slot (`PK` / `KEK` / `db` / `dbx` / `MOK`) | UEFI Secure Boot |
| security-compliance | [`security-compliance/contract.md`](security-compliance/contract.md) | profile name | — |
| selinux-management | [`selinux-management/contract.md`](selinux-management/contract.md) | boolean name / file context | **Linux-only**; Ubuntu conditional on selinux-policy |
| service-management | [`service-management/contract.md`](service-management/contract.md) | `ServiceScope` (SYSTEM / USER) + service name | — |
| ssh-server-configuration | [`ssh-server-configuration/contract.md`](ssh-server-configuration/contract.md) | sshd config section + keyword | — |
| storage-management | [`storage-management/contract.md`](storage-management/contract.md) | volume / pool identifier | LVM / APFS / Storage Spaces |
| subscription-management | [`subscription-management/contract.md`](subscription-management/contract.md) | — | **RHEL-only**; other OSes MAY `NotImplementedError` |
| tuned-management | [`tuned-management/contract.md`](tuned-management/contract.md) | profile name | **RHEL-primary**; Ubuntu conditional |
| user-group-management | [`user-group-management/contract.md`](user-group-management/contract.md) | user vs group | — |
| virtualization-management | [`virtualization-management/contract.md`](virtualization-management/contract.md) | hypervisor backend + VM name | KVM/libvirt / HyperKit / Hyper-V |

## Per-OS spec policy

**Contracts are authored ahead of code. Per-OS specs are authored
*with* code.**

A contract in this folder locks the cross-OS semantics of a feature
(verbs, return types, invariants, scope mappings, elevation, aspect
composition). That information is genuinely reusable — every
per-OS implementation must honor it, and it doesn't change when
someone opens a man page.

A per-OS `design.md` / `requirements.md` / `tasks.md` set
(e.g., `automojo-sysman-linux-ubuntu/specs/3-<feature>/`) pins
down OS-specific commands, flag strings, output parsers, and
idempotency guards. These details are only reliable once they have
been tested against a live system — speculative ahead-of-code
drafts drift quickly and rot silently.

Going forward, new per-OS specs are written as part of the
implementation PR that delivers the feature on that OS. The spec
and the code ship together and review together. Specs without
implementations are not maintained.

## Per-OS spec inventory

Existing per-OS spec sets (written as Phase 1/2 exemplars, retained
as patterns):

| Feature | Ubuntu | macOS | Windows | UEFI |
|---------|--------|-------|---------|------|
| command-execution | ✓ | ✓ | ✓ | — |
| maintenance-reporting | ✓ | ✓ | ✓ | — |
| configuration-management | ✓ | ✓ | ✓ | — |
| environment-configuration | ✓ | ✓ | ✓ | — |
| filesystem-management | ✓ | ✓ | ✓ | — |
| firewall-management | ✓ | ✓ | ✓ | — |
| kernel-parameters | ✓ | ✓ | ✓ | — |
| log-management | ✓ | ✓ | ✓ | — |
| network-configuration | ✓ | ✓ | ✓ | — |
| package-management | ✓ | ✓ | ✓ | — |
| repository-management | ✓ | ✓ | ✓ | — |
| scheduled-tasks | ✓ | ✓ | ✓ | — |
| security-compliance | ✓ | ✓ | ✓ | — |
| service-management | ✓ | ✓ | ✓ | — |
| user-group-management | ✓ | ✓ | ✓ | — |
| boot-management (UEFI firmware) | — | — | — | ✓ |
| capsule-update | — | — | — | ✓ |
| efi-variables | — | — | — | ✓ |
| esp-management | — | — | — | ✓ |
| secure-boot | — | — | — | ✓ |

All other contracts (the 30 drafted during Phase 3a/3b) do not have
per-OS specs yet. They will be written alongside the implementation
work for each `automojo-sysman-*` package, not ahead of it.
