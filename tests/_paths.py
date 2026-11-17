import os
import sys

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)

for path in (ROOT, os.path.join(ROOT, "libs")):
    if os.path.isdir(path) and path not in sys.path:
        sys.path.insert(0, path)
