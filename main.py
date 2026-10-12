"""
Legacy entry point (v0.5 usage): ``python main.py [config.ini]``.

The canonical entry point is ``python -m synphly run CONFIG``; this shim only forwards to it.
CONFIG defaults to ``./config.ini``.
"""
import sys

from synphly.cli import main

if __name__ == '__main__':
    config = sys.argv[1] if len(sys.argv) > 1 else './config.ini'
    sys.exit(main(['run', config]))
