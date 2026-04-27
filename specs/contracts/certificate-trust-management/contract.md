# Certificate-Trust-Management Contract

This is the cross-OS abstract contract for the
**certificate-trust-management** feature. Every
`automojo-sysman-*` package that ships a certificate-trust
manager MUST honor this contract.

The reference implementation is
[`automojo-sysman-linux-redhat/specs/3-certificate-trust-management/`](../../../../../automojo-sysman-linux-redhat/specs/3-certificate-trust-management/).
It wraps `update-ca-trust`, `openssl`, and direct file
operations under `/etc/pki/ca-trust/source/anchors/` through an
`ICommandRunner` (and MAY use an `IFileOperator` where available;
the established pattern is to route file I/O through
`ICommandRunner` — see the README "Implementation Conventions").
This contract generalises
the verb set for OSes whose trust-store surface is the Linux
CA-trust family (`update-ca-trust`, `update-ca-certificates`),
macOS Keychain trust (`security add-trusted-cert`,
`security remove-trusted-cert` against login and system
keychains), or Windows certificate stores (`Certutil -addstore`,
PowerShell `PKI` module against `Cert:\LocalMachine\Root` and
`Cert:\CurrentUser\Root`).

---

## Scope

The certificate-trust-management feature provides idempotent,
auditable control over the host's CA trust stores. It covers:

- Adding a trusted CA certificate to a named trust store with a
  purpose / usage designation.
- Removing a trusted CA certificate from a named trust store by
  fingerprint.
- Listing the trusted certificates currently in a store.
- Retrieving structured metadata for an individual certificate
  by fingerprint.
- Rebuilding / refreshing the consolidated trust bundle after
  changes.
- Enabling or disabling a store (where the OS exposes that
  toggle).
- Verifying a certificate chain against the system trust store.
- Dry-run-aware writes.
- Elevation for writes; reads never elevate unless the OS store
  is access-controlled.

The feature does NOT issue or renew certificates — that is
`certificate-issuance`.

---

## Verbs

Every OS implementation MUST expose a
`CertificateTrustManager` class (the OS-prefixed variant — see
§Naming) whose public surface is the following set of verbs.

| Verb | Signature | Kind |
|------|-----------|------|
| `add_trusted_cert` | `(store: str, path: str, purpose: TrustPurpose) → CertTrustActionResult` | Write |
| `remove_trusted_cert` | `(store: str, fingerprint: str) → CertTrustActionResult` | Write |
| `list_trusted_certs` | `(store: str) → list[TrustAnchor]` | Read |
| `get_cert_details` | `(fingerprint: str) → CertMetadata \| None` | Read |
| `update_trust_store` | `() → CertTrustActionResult` | Write |
| `set_store_enabled` | `(store: str, enabled: bool) → CertTrustActionResult` | Write |
| `verify_certificate` | `(cert_path: str, store: str \| None) → CertVerifyResult` | Read |

### Method-level invariants (writes)

1. **Idempotency guard.** `add_trusted_cert` MUST return
   `SKIPPED` when a certificate with the same SHA-256 fingerprint
   is already installed in the named store.
   `remove_trusted_cert` MUST return `SKIPPED` when no such
   fingerprint is found. `set_store_enabled` MUST return
   `SKIPPED` when the store is already in the requested state.
   `update_trust_store` is operational and MUST NOT skip.
2. **Dry-run short-circuit.** `dry_run=True` MUST return
   `DRY_RUN` without invoking the runner or file operator.
3. **Error surface.** Failures MUST return `FAILED` with
   `exit_code`, `stdout`, `stderr`, and `command` populated.
4. **PEM validation.** `add_trusted_cert` MUST validate that the
   source file is a syntactically valid certificate (PEM or the
   OS's native format) before the file operator is asked to
   write or the native install command is invoked. Validation
   failure MUST return `FAILED`.
5. **Refresh coupling.** `add_trusted_cert` and
   `remove_trusted_cert` MUST NOT implicitly invoke
   `update_trust_store`. Callers are responsible for explicitly
   calling `update_trust_store` where the OS requires it.

### Method-level invariants (reads)

1. **No elevation.** Reads MUST NOT pass `elevated=True` unless
   the OS requires it to inspect a protected store.
2. **Typed errors.** Reads MAY raise `CertTrustQueryError` for
   unexpected failures or, per the per-OS spec, return an empty
   list / `None` so callers can proceed without a try/except
   wrapper. `get_cert_details` MUST return `None` for an unknown
   fingerprint rather than raise. See the README "Implementation
   Conventions" graceful-read pattern.
3. **Pure parsing.** Parsing runs in pure Python.

---

## Data Models

Every OS implementation MUST expose these dataclasses and enums,
each prefixed with the OS name (see §Naming).

### `CertTrustActionStatus` (enum)

| Value | Meaning |
|-------|---------|
| `SUCCESS` | The command ran and succeeded. |
| `FAILED` | The command ran and returned non-zero, or a precondition was not met. |
| `SKIPPED` | The idempotency guard determined no action was needed. |
| `DRY_RUN` | Dry-run mode short-circuited the command. |

### `TrustPurpose` (enum)

| Value | Meaning |
|-------|---------|
| `TLS_SERVER` | Trust for TLS server authentication. |
| `TLS_CLIENT` | Trust for TLS client authentication. |
| `CODE_SIGNING` | Trust for code-signing validation. |
| `EMAIL` | Trust for S/MIME email signatures. |
| `ANY` | Trust for any purpose, where the OS supports wildcard trust. |

### `TrustAnchor` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `store` | `str` | Store name the anchor lives in. |
| `subject` | `str` | Subject DN. |
| `issuer` | `str` | Issuer DN. |
| `serial` | `str` | Hex serial. |
| `sha256_fingerprint` | `str` | Hex SHA-256 fingerprint. |
| `not_before` | `str` | ISO-8601 validity start. |
| `not_after` | `str` | ISO-8601 validity end. |
| `purposes` | `list[TrustPurpose]` | Purposes the anchor is trusted for. |
| `path` | `str \| None` | On-disk path when applicable. |

### `CertMetadata` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `subject` | `str` | Subject DN. |
| `issuer` | `str` | Issuer DN. |
| `serial` | `str` | Hex serial. |
| `not_before` | `str` | ISO-8601 validity start. |
| `not_after` | `str` | ISO-8601 validity end. |
| `sha256_fingerprint` | `str` | Hex SHA-256 fingerprint. |
| `sans` | `list[str]` | Subject alternative names. |

### `CertVerifyResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `ok` | `bool` | Whether the chain verified. |
| `output` | `str` | Verbatim verifier output. |
| `chain_length` | `int \| None` | Depth of verification when known. |

### `CertTrustActionResult` (dataclass)

| Field | Type | Description |
|-------|------|-------------|
| `status` | `CertTrustActionStatus` | Outcome category. |
| `store` | `str \| None` | Store acted upon. |
| `sha256_fingerprint` | `str \| None` | Fingerprint of the affected certificate. |
| `detail` | `str \| None` | Human-readable detail. |
| `exit_code` | `int \| None` | Runner exit code. |
| `stdout` | `str \| None` | Captured stdout. |
| `stderr` | `str \| None` | Captured stderr. |
| `command` | `list[str] \| None` | The argv that was (or would have been) executed. |

### Exceptions

| Exception | Raised When |
|-----------|-------------|
| `CertTrustQueryError` | A read fails unexpectedly. |
| `CertTrustStoreNotFoundError` | An unknown store name is supplied. |
| `CertTrustInvalidCertificateError` | Source bytes for `add_trusted_cert` do not parse as a valid certificate. |

### `CertificateTrustManagerConfig` (dataclass)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `dry_run` | `bool` | `False` | When `True`, writes short-circuit. |
| `elevated` | `bool` | `False` | When `True`, writes pass `elevated=True` to the runner. |

---

## Trust-Store Mapping

The abstract `store` identifier maps to each OS's native stores:

| OS | Native concept | Notes |
|----|----------------|-------|
| Red Hat Enterprise Linux | `"system-ca"` → `/etc/pki/ca-trust/source/anchors/`; `"system-ca-blocklist"` → `.../blacklist/`; `"java-ca"` where the `ca-certificates-java` layer is installed. | Canonical. `update_trust_store` runs `update-ca-trust extract`. |
| Ubuntu | `"system-ca"` → `/usr/local/share/ca-certificates/`; `update-ca-certificates` refreshes. | — |
| macOS | `"system-ca"` → System keychain; `"user-ca"` → login keychain. `set_store_enabled` MAY return `FAILED` (keychain stores are always enabled). | — |
| Windows | `"system-ca"` → `Cert:\LocalMachine\Root`; `"user-ca"` → `Cert:\CurrentUser\Root`; `"system-intermediate"` → `Cert:\LocalMachine\CA`. | — |
| UEFI | N/A | UEFI db/dbx are covered by `secure-boot`, not this feature. |

Each OS spec MUST include a Trust-Store Mapping section.

---

## Elevation

| Situation | Behavior |
|-----------|----------|
| Config `elevated=True`, write method | Pass `elevated=True` to the runner. |
| Config `elevated=True`, read method | Do NOT pass `elevated=True`, except where the OS requires it. |
| Config `elevated=False` | Never pass `elevated=True`. |
| OS mechanism | `sudo` on RHEL/Ubuntu/macOS; Administrator token / UAC on Windows. |

---

## Execution Model

```
        Maintenance coordinator
                │
                │  instantiates + injects runner, file operator, config
                ▼
        <Os>CertificateTrustManager
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

1. Accept an `ICommandRunner` and a
   `CertificateTrustManagerConfig` in their constructor.
   Implementations whose trust store is a filesystem layout MAY
   also accept an `IFileOperator`.
2. Never construct their own subprocess.
3. Not hold state across calls beyond the config.
4. Be safe under any aspect composition on the runner.

---

## Naming

Concrete types per OS are prefixed with the full Pascal-case OS
name. No abbreviations.

| Abstract | Ubuntu | macOS | Windows | RHEL (reference) |
|----------|--------|-------|---------|------------------|
| `CertificateTrustManager` | `UbuntuCertificateTrustManager` | `MacosCertificateTrustManager` | `WindowsCertificateTrustManager` | `CertificateTrustManager` |
| `CertificateTrustManagerConfig` | `UbuntuCertificateTrustManagerConfig` | `MacosCertificateTrustManagerConfig` | `WindowsCertificateTrustManagerConfig` | `CertificateTrustManagerConfig` |
| `CertTrustActionStatus` | `UbuntuCertTrustActionStatus` | `MacosCertTrustActionStatus` | `WindowsCertTrustActionStatus` | `CertTrustActionStatus` |
| `CertTrustActionResult` | `UbuntuCertTrustActionResult` | `MacosCertTrustActionResult` | `WindowsCertTrustActionResult` | `CertTrustActionResult` |
| `TrustPurpose` | `UbuntuTrustPurpose` | `MacosTrustPurpose` | `WindowsTrustPurpose` | `TrustPurpose` |
| `TrustAnchor` | `UbuntuTrustAnchor` | `MacosTrustAnchor` | `WindowsTrustAnchor` | `TrustAnchor` |
| `CertMetadata` | `UbuntuCertMetadata` | `MacosCertMetadata` | `WindowsCertMetadata` | `CertMetadata` |
| `CertVerifyResult` | `UbuntuCertVerifyResult` | `MacosCertVerifyResult` | `WindowsCertVerifyResult` | `CertVerifyResult` |
| `CertTrustQueryError` | `UbuntuCertTrustQueryError` | `MacosCertTrustQueryError` | `WindowsCertTrustQueryError` | `CertTrustQueryError` |
| `CertTrustStoreNotFoundError` | `UbuntuCertTrustStoreNotFoundError` | `MacosCertTrustStoreNotFoundError` | `WindowsCertTrustStoreNotFoundError` | `CertTrustStoreNotFoundError` |
| `CertTrustInvalidCertificateError` | `UbuntuCertTrustInvalidCertificateError` | `MacosCertTrustInvalidCertificateError` | `WindowsCertTrustInvalidCertificateError` | `CertTrustInvalidCertificateError` |

---

## Aspect Composition

Aspect behavior MUST be transparent to the manager:

- A manager tested with a `MockCommandRunner` and no aspects MUST
  produce the same `CertTrustActionResult` sequence when driven
  by a real runner with aspects attached, modulo retry-induced
  timing.
- Retry aspects are permitted to flip `status` from `FAILED` to
  `SUCCESS`.
- Persistence aspects MUST NOT mutate the result.

---

## Tests

Each OS implementation MUST include at minimum:

1. One command-construction test per write verb.
2. One idempotency test proving `SKIPPED` when an identical
   certificate is already trusted in the store.
3. One dry-run test per write verb proving the runner is not
   invoked.
4. One PEM-validation test proving
   `CertTrustInvalidCertificateError` for a malformed source
   file, without any install command being dispatched.
5. One `list_trusted_certs` parser test covering representative
   output with multiple purposes.
6. One `get_cert_details` test covering a known fingerprint and
   an unknown fingerprint (returns `None`).
7. One `update_trust_store` / refresh test proving the correct
   native refresh command is dispatched.
8. One elevation test proving writes pass `elevated=True` and
   reads do not, when configured.
9. One unknown-store test proving
   `CertTrustStoreNotFoundError` is raised.

---

## Out of Scope for the Base Contract

The following are intentionally NOT in the contract. They MAY be
added by any OS implementation as extensions but are not required
for contract conformance:

- Certificate issuance / renewal (see
  `certificate-issuance`).
- UEFI db/dbx management (see `secure-boot`).
- Browser-private trust stores (Firefox NSS, Chrome on Linux).
- JVM trust stores beyond the Linux `java-ca` consolidation.
- Application-specific trust stores (Python, Node.js, Go).
- CRL / OCSP distribution-point management.

---

## Implementation Drift

Phase 3 cross-OS implementations surfaced these intentional
deviations from the contract.

- **Per-OS trust-store identifiers.** Ubuntu uses path-based
  store names (`/usr/local/share/ca-certificates/`); macOS uses
  `system` / `login` keychain identifiers; Windows uses
  `LocalMachine\Root` / `CurrentUser\Root` registry-style paths.
  Per-OS specs document the exact accepted store identifiers.
- **File I/O via `ICommandRunner`.** Anchor files, PEM bundles,
  and DER blobs are read/written through the runner using `cat`,
  `tee`, `Get-Content`, `Set-Content`.
- **Naming overrides.** Ubuntu surface uses
  `UbuntuCertificateTrustInfo` / `UbuntuCertificateTrustSpec`
  (`Info` / `Spec` split aligned with the rest of the package)
  rather than the contract's combined `CertificateTrustEntry`.
