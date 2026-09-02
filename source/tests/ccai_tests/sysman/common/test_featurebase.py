"""
    Legacy ``unittest`` mirror of the testbase module
    ``ccai.tests.sysman.common.test_featurebase``.  Binds every authored
    module-level ``test_*`` function onto a ``TestCase`` so both suites run
    the same assertions.
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

_AUTHORED = importlib.import_module("ccai.tests.sysman.common.test_featurebase")


class FeatureBaseTests(unittest.TestCase):
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
    setattr(FeatureBaseTests, name, _method)
    return


for _name in dir(_AUTHORED):
    if _name.startswith("test_") and callable(getattr(_AUTHORED, _name)):
        _bind(_name)


if __name__ == "__main__":
    unittest.main()
