# automojo-sysman-common Tasks

The initial migration task migrated the cross-OS contracts out of
`automojo-interfaces/specs/sysman-contracts/` into
`automojo-sysman-common/specs/contracts/`, upstreamed the previously
vendored `featurebase.py` (which had been duplicated across the
Ubuntu, macOS, Windows, and UEFI sysman packages) into the canonical
location at `source/packages/automojo/sysman/common/featurebase.py`,
and re-pointed every per-OS sysman package's pyproject.toml and
Python imports at the new module. Ongoing tasks track changes to the
shared base classes (e.g., new status values, new helpers) and
contract updates that emerge as new per-OS implementations land.
