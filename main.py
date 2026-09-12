"""PyStand application entry script.

This is the only place where application startup logic lives.  It runs inside
the embedded Python of PyStand.exe and is equally runnable on its own:

    PyStand.exe            -> the embedded startup script execs this file
    python main.py         -> same thing without PyStand

`import app` must resolve to the application module sitting next to this file,
so that directory is put in front of sys.path (guarded, because a missing or
odd __file__ must never stop the application from starting).
"""

import os
import sys

sys.dont_write_bytecode = True                  # keep __pycache__ out of the install dir

if os.environ.get("PYSTAND"):                   # running inside PyStand.exe
    if not getattr(sys, "frozen", False):
        sys.frozen = True
    try:
        import multiprocessing
        multiprocessing.freeze_support()        # no-op unless a frozen child spawns
    except Exception:
        pass

try:
    base = os.path.dirname(os.path.abspath(__file__))
    if base and base not in sys.path:
        sys.path.insert(0, base)
except NameError:
    pass

import app

if __name__ == "__main__":
    app.start()
