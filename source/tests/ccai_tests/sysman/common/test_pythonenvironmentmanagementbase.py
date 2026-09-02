"""
    Legacy ``unittest`` mirror of the testbase module
    ``ccai.tests.sysman.common.test_pythonenvironmentmanagementbase``.

    The testbase module is the authored suite for the
    python-environment-management base (it was written after the Phase 7
    shift began).  This module keeps the legacy ``unittest`` gate green
    by binding every module-level ``test_*`` function from the testbase
    module onto a ``TestCase`` so both suites run the same assertions.
    The testbase root is resolved relative to this file so no
    ``PYTHONPATH`` change is required.
"""

import importlib
import os
import sys
import unittest


_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_SOURCE_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", "..", ".."))
_TESTBASE_ROOT = os.path.join(_SOURCE_DIR, "testroots", "testbase")

if _TESTBASE_ROOT not in sys.path:
    sys.path.insert(0, _TESTBASE_ROOT)

_AUTHORED = importlib.import_module(
    "ccai.tests.sysman.common.test_pythonenvironmentmanagementbase"
)


class PythonEnvironmentManagementBaseTests(unittest.TestCase):
    """
        One ``TestCase`` method per authored testbase function.
    """
    pass


def _bind(name: str) -> None:
    authored = getattr(_AUTHORED, name)

    def _method(self: unittest.TestCase, _authored=authored) -> None:
        _authored()
        return

    _method.__name__ = name
    _method.__doc__ = authored.__doc__
    setattr(PythonEnvironmentManagementBaseTests, name, _method)
    return


for _name in dir(_AUTHORED):
    if _name.startswith("test_") and callable(getattr(_AUTHORED, _name)):
        _bind(_name)


if __name__ == "__main__":
    unittest.main()
