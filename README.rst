==============================
Code Craft AI Sysman Common
==============================

The ``codecraftai-sysman-common`` package is the shared foundation for the
``codecraftai-sysman-*`` system-management package family (RHEL, Ubuntu,
macOS, Windows, UEFI). It hosts the cross-OS feature contracts that
every per-OS sysman package implements, together with the shared base
classes and helper utilities that the per-OS packages reuse.

Highlights
==========

- **Cross-OS feature contracts** under ``specs/contracts/`` — 50
  markdown contracts that define the verbs, return shapes, status
  vocabulary, and invariants every per-OS sysman package implements.
- **Shared base classes** under
  ``source/packages/ccai/sysman/common/`` — ``BaseFeatureManager``,
  ``ActionStatus``, ``FeatureConfig``, ``FeatureActionResult``, and the
  host-OS-dispatch helpers (``detect_host_os``,
  ``normalise_override_host_os``) used by the UEFI tier.
- **VPN client management base** (``vpnclientmanagementbase``) — the
  ``VPNClientManagementBase`` cross-OS feature base for Tailscale and
  Twingate, together with its shared types (``VPNClientManagerConfig``,
  ``VPNClientStatus``, ``VPNClientQueryError``, ``VPNActionResult``,
  ``VPNActionStatus``, ``VPNProvider``) that every per-OS sysman package
  imports rather than re-vendors.
- **No public CLI / no runtime services** — the package is pure
  foundation code, consumed as a dependency by every per-OS sysman
  package.

Repository Structure
====================

- ``development/`` - Runtime environment scripts.
- ``repository-setup/`` - Repository homing and setup scripts.
- ``source/packages/`` - Package source code (shared base classes).
- ``source/testroots/testbase/`` - TestBase test roots (scaffolding).
- ``specs/`` - Project specs and the cross-OS feature contracts under
  ``specs/contracts/``.
- ``userguide/`` - Standards, conventions, and documentation.

Environment Setup
=================

When working in a Codex container:

.. code-block:: bash

   ./development/setup-agent-container

For local development:

.. code-block:: bash

   ./repository-setup/rehome-repository
   ./development/setup-environment

Running Tests
=============

Activate the virtual environment and invoke ``testbase`` against the
package's testbase root:

.. code-block:: bash

   source .venv/bin/activate
   testbase testing run \
       --root source/testroots/testbase \
       --output=./.output

Standards and Conventions
=========================

- Naming conventions: ``userguide/10-02-naming-conventions.rst``
- Code organization: ``userguide/10-01-code-organization.rst``
- Coding standards: ``userguide/10-00-coding-standards.rst``

Additional Resources
====================

- User guide entry point: ``userguide/userguide.rst``
- Cross-OS contract index: ``specs/contracts/README.md``
