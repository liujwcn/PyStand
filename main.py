"""PyStand startup script - the entry point of the application.

The text of this file is embedded verbatim into PyStand.cpp, so PyStand.exe
stays one self-contained executable that needs no .int script beside it.  It
is ordinary Python as well, so it runs unchanged under a normal interpreter
while developing:

    PyStand.exe     -> the embedded copy of this file
    python main.py  -> this file

Rules that keep the embedding working:
  * keep this file ASCII only - PyStand converts the embedded C string with the
    ANSI code page, so non-ASCII characters here would come out mangled;
  * after editing, run "python tools/gen_embed.py" to refresh the embedded
    copy inside PyStand.cpp - "python tools/check_embed.py" fails when the two
    ever drift apart.
"""

import os
import sys

# Keep __pycache__ out of the installation directory: it is often read-only
# (Program Files) and must not be littered with build artifacts.
sys.dont_write_bytecode = True

# PyStand.exe exports PYSTAND; a plain interpreter does not.
if os.environ.get("PYSTAND"):
    sys.frozen = True
    try:
        import multiprocessing
        multiprocessing.freeze_support()
    except Exception:
        pass

# The application module (app.py) sits next to this file.  Inside PyStand.exe
# there is no __file__ and PYSTAND_HOME - the directory of the executable -
# takes its place; the directory is already on sys.path by then, but putting it
# first makes the application win over any same-named site-packages module.
try:
    base = os.path.dirname(os.path.abspath(__file__))
except NameError:
    base = os.environ.get("PYSTAND_HOME") or os.getcwd()
if base and base not in sys.path:
    sys.path.insert(0, base)

import app

if __name__ == "__main__":
    app.start()
