# -*- coding:utf-8 -*-
"""qvdf_selfdemo — the CBI/QVDF turn-key pipeline bundled with a small average-weekday testbed,
shipped inside cbi-plus so the package self-demonstrates (run + dashboards + self-validate) on every
release. The pipeline modules use flat intra-imports; put this package dir on sys.path so they
resolve when imported as `qvdf_selfdemo`."""
import os as _os
import sys as _sys

_HERE = _os.path.dirname(_os.path.abspath(__file__))
if _HERE not in _sys.path:
    _sys.path.insert(0, _HERE)

__all__ = ["selftest"]
