# Certificate-Issuance Contract

This is the cross-OS abstract contract for the
**certificate-issuance** feature. Every `automojo-sysman-*`
package that ships a certificate-issuance manager MUST honor this
contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-certificate-issuance/`](../../../../../automojo-sysman-linux-redhat/specs/3-certificate-issuance/).
It wraps `openssl`, `getcert` (certmonger), and `certbot` through
an `ICommandRunner`. This contract generalises the verb set for
OSes whose issuance surface is the Linux `openssl` / ACME /
Dogtag family, macOS Keychain plus `security` plus ACME, or
Windows Certificate Services (`certreq.exe`, PowerShell `PKI`
module).

Credential material (key passphrases, ACME credentials) MUST
flow on runner `stdin` and never on argv. The `command` field in
any result MUST be sanitised.

---

## Scope

The certificate-issuance feature provides idempotent, auditable
control over host-issued X.509 certificates, keyed by a
caller-chosen alias. It covers:

- Requesting a new certificate from a configured certificate
  authority or via ACME.
- Renewing an existing certificate identified by alias.
- Revoking a certificate with a reason code.
- Fetching the metadata for a certificate by alias.
- Listing the certificates managed on the host.
- Exporting a certificate (and optionally its key) to a
  filesystem path.
- Importing an existing certificate + key pair from a
  filesystem path under a new alias.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate unless the OS's
  certificate store is access-controlled.

The feature does NOT manage CA trust anchors — that is
`certificate-trust-management`.

---

## Verbs

Every OS implementation MUST expose a
`CertificateIssuanceManager` class (the OS-prefixed variant —
see §Naming) whose public surface is the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `request_certificate` | `(spec: CertificateRequestSpec, credential: Credential \| None) → CertificateActionResult` | Write |
| `renew_certificate` | `(alias: str, credential: Credential \| None) → CertificateActionResult` | Write |
| `revoke_certificate` | `(alias: str, reason: str) → CertificateActionResult` | Write |
| `get_certificate` | `(alias: str) → CertificateInfo \| None` | Read |
| `list_certificates` | `() → list[CertificateInfo]` | Read |
| `export_certificate` | `(alias: str, destination_path: str, include_key: bool, credential: Credential \| None) → CertificateActionResult` | Write |
| `import_certificate` | `(source_path: str, alias: str, credential: Credential \| None) → CertificateActionResult` | Write |

### Method-level invariants (writes)

1. **Idempotency guard.** `request_certificate` MUST return
   `SKIPPED` when a certificate under `alias` already exists AND
   its remaining validity exceeds `config.renew_after_days`.
   `renew_certificate` MUST return `SKIPPED` under the same
   threshold. `revoke_certificate` MUST return `SKIPPED` when the
   certificate is already revoked. `import_certificate` MUST
   return `SKIPPED` when an identical certificate already exists
   under the alias (by SHA-256 fingerprint).
2. **Dry-run short-circuit.** `dry_run=True` MUST return
   `DRY_RUN` without invoking the runner.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **Credential safety.** Every passphrase / credential byte
   MUST flow on `stdin` only. The `command` field in the result
   MUST be sanitised, as MUST the argv passed to the runner.
5. **Mode bits.** On OSes with POSIX permissions, newly written
   private-key files MUST be chmod'd to `0600`, certificate files
   to `0644`, immediately after the write.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` unless
   the OS requires it.
2. **Typed errors.** `get_certificate` MUST return `None` for an
   unknown alias rather than raise. `list_certificates` MAY raise
   `CertificateQueryError` for unexpected failures or, per the
   per-OS spec, return an empty list with the failure surfaced via
   logging. See the README "Implementation Conventions"
   graceful-read pattern.
3. **Pure parsing.** Parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `CertificateActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or a precondition was not met. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `CertificateIssuer` (enum)

| Value | Meaning |
|-------|---------|
| `SELF_SIGNED` | Self-signed via `openssl req -x509` or native equivalent. |
| `ACME` | ACME-protocol issuer (Let's Encrypt, ZeroSSL, etc.). |
| `CERTMONGER` | Linux certmonger (tracking-based). |
| `ADCS` | Windows Active Directory Certificate Services. |
| `KEYCHAIN_CA` | macOS Keychain-held CA. |

### `CertificateRequestSpec` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `alias` | `str` | Caller-chosen identifier. |
| `subject_common_name` | `str` | Certificate CN. |
| `subject_alternatives` | `list[str]` | SAN entries (DNS, IP, URI, email). |
| `issuer` | `CertificateIssuer` | Issuer selection. |
| `key_algorithm` | `str` | `"rsa"` or `"ec"`. |
| `key_size_or_curve` | `str` | `"3072"` for RSA, `"P-256"` for EC, etc. |
| `key_usages` | `list[str]` | Key-usage OIDs or short names. |
| `extended_key_usages` | `list[str]` | EKU short names (`"serverAuth"`, `"clientAuth"`). |
| `acme_method` | `str \| None` | ACME validation method when `issuer=ACME` (`"webroot"`, `"standalone"`, `"dns-<plugin>"`). |
| `renew_after_days` | `int \| None` | Override the config-default renewal threshold. |

### `CertificateInfo` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `alias` | `str` | Caller-chosen alias. |
| `subject` | `str` | Certificate subject DN. |
| `issuer` | `str` | Issuer DN. |
| `serial` | `str` | Hex serial. |
| `not_before` | `str` | ISO-8601 validity start. |
| `not_after` | `str` | ISO-8601 validity end. |
| `sha256_fingerprint` | `str` | Hex SHA-256 fingerprint. |
| `sans` | `list[str]` | Subject-alternative names. |
| `key_algorithm` | `str` | `"rsa"` or `"ec"`. |
| `revoked` | `bool` | Revocation state when tracked by the issuer. |
| `storage_path` | `str \| None` | Filesystem path of the managed certificate file, when applicable. |

### `CertificateActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `CertificateActionStatus` | Outcome category. |
| `alias` | `str \| None` | Alias acted upon. |
| `path` | `str \| None` | Output path (export) or certificate path (request). |
| `detail` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | Sanitised argv. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `CertificateQueryError` | A read fails unexpectedly. |
| `CertificateCredentialError` | A verb requires a credential and none was supplied. |
| `CertificateAliasNotFoundError` | `renew_certificate`, `revoke_certificate`, or `export_certificate` is given an unknown alias. |

### `CertificateIssuanceManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |
| `renew_after_days` | `int` | `30` | Default renewal threshold in days. |
| `default_key_algorithm` | `str` | `"rsa"` | Default key algorithm when the spec does not specify. |
| `default_key_size_or_curve` | `str` | `"3072"` | Default key size / curve. |

---

## Issuer Mapping

The abstract `CertificateIssuer` maps to each OS's native
tooling:

| OS | Supported issuers | Notes |
|----|-------------------|-------|
| Red Hat Enterprise Linux | `SELF_SIGNED` (openssl), `ACME` (certbot), `CERTMONGER` (getcert) | Canonical. `ADCS` and `KEYCHAIN_CA` MUST return `FAILED`. |
| Ubuntu | Same as RHEL. | — |
| macOS | `SELF_SIGNED` (openssl), `ACME` (certbot or acme.sh), `KEYCHAIN_CA` (`security create-certificate` against a Keychain-resident CA). `CERTMONGER` MUST return `FAILED`. | — |
| Windows | `SELF_SIGNED` (`New-SelfSignedCertificate`), `ACME` (Posh-ACME or win-acme), `ADCS` (`certreq.exe` + CSR template). `CERTMONGER` and `KEYCHAIN_CA` MUST return `FAILED`. | — |
| UEFI | N/A | UEFI does not own an X.509 issuance surface at this layer. The contract does not apply. |

Each OS spec MUST include an Issuer-Mapping section.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, config
                │  supplies credential objects for passphrases
                ▼
        <Os>CertificateIssuanceManager
                │
                │  .run(argv, elevated=…, stdin=<secret>, capture_output=True)
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

1. Accept an `ICommandRunner` and a
   `CertificateIssuanceManagerConfig` in their constructor.
2. Never construct their own subprocess.
3. Never place secret bytes on argv. Every credential-bearing
   code path MUST use `stdin`.
4. Not hold state across calls beyond the config.
5. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `CertificateIssuanceManager` | `UbuntuCertificateIssuanceManager` | `MacosCertificateIssuanceManager` | `WindowsCertificateIssuanceManager` | `CertificateIssuanceManager` |
| `CertificateIssuanceManagerConfig` | `UbuntuCertificateIssuanceManagerConfig` | `MacosCertificateIssuanceManagerConfig` | `WindowsCertificateIssuanceManagerConfig` | `CertificateIssuanceConfig` |
| `CertificateActionStatus` | `UbuntuCertificateActionStatus` | `MacosCertificateActionStatus` | `WindowsCertificateActionStatus` | `CertificateActionStatus` |
| `CertificateActionResult` | `UbuntuCertificateActionResult` | `MacosCertificateActionResult` | `WindowsCertificateActionResult` | `CertificateActionResult` |
| `CertificateIssuer` | `UbuntuCertificateIssuer` | `MacosCertificateIssuer` | `WindowsCertificateIssuer` | `CertificateIssuer` |
| `CertificateRequestSpec` | `UbuntuCertificateRequestSpec` | `MacosCertificateRequestSpec` | `WindowsCertificateRequestSpec` | `CertificateRequestSpec` |
| `CertificateInfo` | `UbuntuCertificateInfo` | `MacosCertificateInfo` | `WindowsCertificateInfo` | `CertificateInfo` |
| `CertificateQueryError` | `UbuntuCertificateQueryError` | `MacosCertificateQueryError` | `WindowsCertificateQueryError` | `CertificateQueryError` |
| `CertificateCredentialError` | `UbuntuCertificateCredentialError` | `MacosCertificateCredentialError` | `WindowsCertificateCredentialError` | `CertificateCredentialError` |
| `CertificateAliasNotFoundError` | `UbuntuCertificateAliasNotFoundError` | `MacosCertificateAliasNotFoundError` | `WindowsCertificateAliasNotFoundError` | `CertificateAliasNotFoundError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `CertificateActionResult` sequence when driven
  by a real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`. Retry aspects MUST NOT re-send secret bytes beyond
  the runner's documented retry-redelivery contract.
- Persistence aspects MUST NOT mutate the result. Persistence
  aspects MUST NOT log `stdin` bytes (passphrases, ACME
  credentials).

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test proving `SKIPPED` when an existing
   certificate's remaining validity exceeds the renewal
   threshold.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One `get_certificate` parser test covering a certificate with
   multiple SANs.
5. One `list_certificates` parser test covering representative
   output.
6. One credential-safety test proving passphrases never appear in
   the recorded argv.
7. One unsupported-issuer test proving `FAILED` with a
   descriptive `detail` for any `CertificateIssuer` the OS does
   not support.
8. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- CA trust-store management (see
  `certificate-trust-management`).
- Certificate-pinning policy distribution.
- HSM / TPM-resident key provisioning.
- OCSP stapling configuration on individual servers.
- S/MIME email-certificate enrolment.
- Code-signing certificate lifecycle beyond the basic `import` /
  `export` verbs.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Backend divergence.** Ubuntu and Windows wrap `certbot` /
  `Get-Certificate` plus the Windows AD-CS auto-enroll surface;
  macOS uses the Keychain (`security` CLI) and surfaces a
  `MacosCertificateInfo` shape with `keychain_path` rather than
  a generic store identifier.
- **File I/O via `ICommandRunner`.** PEM, PKCS12, and CSR file
  reads/writes route through the runner via `cat` / `tee` /
  `Get-Content` / `Set-Content` rather than `IFileOperator`.
- **Per-OS `CertificateBackend` enums.** Each OS defines its own
  prefixed enum (`UbuntuCertificateBackend`, `MacosCertificateBackend`,
  `WindowsCertificateBackend`) listing only the values realisable
  on that OS.
