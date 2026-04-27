# automojo-sysman-common Requirements

The `automojo-sysman-common` package shall provide a single shared
foundation that every `automojo-sysman-*` per-OS package builds on,
covering both the cross-OS feature contracts (under
`specs/contracts/`) and the shared Python base classes (under
`source/packages/automojo/sysman/common/`). The contracts define the
verbs, return shapes, status vocabulary, and invariants every per-OS
package must honour, while the base classes deliver the
`BaseFeatureManager` / `ActionStatus` / `FeatureConfig` /
`FeatureActionResult` types and the host-OS-dispatch helpers
(`detect_host_os`, `normalise_override_host_os`) that the per-OS
managers extend. The package shall remain dependency-light, importing
only `automojo-interfaces`, `automojo-errors`, and `automojo-waiting`
at runtime, and shall ship no public CLI.
