"""Embed main.py verbatim into the startup_script literal of PyStand.cpp.

main.py is the single source of truth for application startup.  Its text is
copied byte for byte into the marked region of PyStand.cpp, behind a small
bootstrap that only supplies what python cannot know by itself (PYSTAND_*
constants, os.MessageBox, stdout/stderr, sys.path).  PyStand.exe therefore
stays a self contained executable: no .int script and no main.py has to be
shipped next to it.

Usage:
    python tools/gen_embed.py           rewrite PyStand.cpp (idempotent)
    python tools/gen_embed.py --check   report drift without writing anything

PyStand.cpp is handled as raw bytes (latin-1 round trip) because its comments
use the ANSI code page, while main.py must stay ASCII - gen_embed refuses to
embed anything else, because PyStand converts the embedded C string with CP_ACP.
"""

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CPP_FILE = os.path.join(ROOT, "PyStand.cpp")
MAIN_FILE = os.path.join(ROOT, "main.py")

BEGIN = "// ==== BEGIN GENERATED startup_script (tools/gen_embed.py) ===="
END = "// ==== END GENERATED startup_script ===="
MARK_BEGIN = ("\t// >>> BEGIN main.py (embedded verbatim - edit main.py, then re-run "
              "tools/gen_embed.py) >>>")
MARK_END = "\t// <<< END main.py <<<"

# The bootstrap runs before main.py and must never contain application logic.
# Lines starting with '@' are C++ preprocessor directives emitted verbatim,
# everything else is python (including '#' comments) folded into the string
# literal.
BOOTSTRAP = """\
import sys
import os
import site
PYSTAND = os.environ.get('PYSTAND', '')
PYSTAND_HOME = os.environ['PYSTAND_HOME']
PYSTAND_RUNTIME = os.environ.get('PYSTAND_RUNTIME', '')
PYSTAND_SCRIPT = os.environ.get('PYSTAND_SCRIPT') or os.path.join(PYSTAND_HOME, 'main.py')
sys.PYSTAND = PYSTAND
sys.PYSTAND_HOME = PYSTAND_HOME
sys.PYSTAND_SCRIPT = PYSTAND_SCRIPT
sys.path_origin = [n for n in sys.path]
def MessageBox(msg, info = 'Message'):
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, str(msg), str(info), 0)
    return 0
os.MessageBox = MessageBox
# attach to the console of the parent process when there is one; a windowed
# build without a console still needs working stdout/stderr, so send them to nul
@#ifndef PYSTAND_CONSOLE
try:
    fd = os.open('CONOUT$', os.O_RDWR | os.O_BINARY)
    fp = os.fdopen(fd, 'w')
    sys.stdout = fp
    sys.stderr = fp
    attached = True
except Exception:
    attached = False
    try:
        fp = open(os.devnull, 'w', errors='ignore')
        sys.stdout = fp
        sys.stderr = fp
    except Exception:
        pass
@#else
attached = True
@#endif
# an unhandled error must never disappear: print it when a console is attached,
# otherwise put it into a message box
def _pystand_excepthook(t, v, tb):
    if attached:
        sys.__excepthook__(t, v, tb)
        return
    import traceback, io
    sio = io.StringIO()
    traceback.print_exception(t, v, tb, file = sio)
    os.MessageBox(sio.getvalue(), 'Error')
sys.excepthook = _pystand_excepthook
# the application directory and the usual sub directories must be importable
for n in ['.', 'lib', 'site-packages', 'runtime']:
    test = os.path.abspath(os.path.join(PYSTAND_HOME, n))
    if os.path.exists(test):
        site.addsitedir(test)
# argv[0] is the startup script, just like for a .py/.pyw script on the command line
sys.argv = [PYSTAND_SCRIPT] + sys.argv[1:]
"""

HEADER = """\
//---------------------------------------------------------------------
// embedded startup script: used when there is no <exe name>.int/.py/.pyw
// next to the executable.
//
// The bootstrap below only supplies what python cannot know by itself:
// PYSTAND_* constants, os.MessageBox, stdout/stderr and sys.path.  Every bit
// of application startup logic lives in main.py, whose text is embedded
// verbatim between the two markers, which is what keeps PyStand.exe a single
// self contained executable.
//
// Never edit the marked region by hand: edit main.py and run
//     python tools/gen_embed.py
// tools/check_embed.py reports any drift between this file and main.py.
//---------------------------------------------------------------------
const char *startup_script =
"""


def normalize(text):
    """Universal newlines, no trailing blank line."""
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def cpp_literal(text):
    """One C++ string literal per source line; '@' lines stay preprocessor."""
    out = []
    for line in normalize(text).split("\n"):
        if line.startswith("@"):
            out.append("\t" + line[1:])
            continue
        escaped = line.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t")
        out.append('\t"%s\\n"' % escaped)
    return out


def read_main():
    data = io.open(MAIN_FILE, "rb").read()
    if any(byte > 0x7f for byte in data):
        raise SystemExit(
            "ERROR: main.py contains non-ASCII bytes; PyStand converts the "
            "embedded script with the ANSI code page, so please keep it ASCII")
    return normalize(data.decode("ascii"))


def build_region(main_text):
    lines = [HEADER.replace("\n", "\r\n")]
    lines.append("\r\n".join(cpp_literal(BOOTSTRAP)) + "\r\n")
    lines.append(MARK_BEGIN + "\r\n")
    lines.append("\r\n".join(cpp_literal(main_text)) + "\r\n")
    lines.append(MARK_END + "\r\n")
    lines.append('\t"";\r\n')
    body = "".join(lines)
    return BEGIN + "\r\n" + body + END + "\r\n"


REGION_RE = re.compile(
    re.escape(BEGIN) + r".*?" + re.escape(END) + r"\r?\n", re.S)


def find_handwritten_span(cpp):
    """Span of the block to take over on the very first run."""
    if "const char *startup_script =" not in cpp:
        raise SystemExit("ERROR: 'const char *startup_script =' not found in PyStand.cpp")
    anchor = cpp.index("const char *startup_script =")
    start = cpp.rfind("\n", 0, anchor) + 1
    while start > 0:
        prev_start = cpp.rfind("\n", 0, start - 1) + 1
        prev = cpp[prev_start:start].strip()
        if not prev.startswith("//"):
            break
        start = prev_start
    end = cpp.index('"";', anchor) + len('"";')
    eol = cpp.find("\n", end)
    end = len(cpp) if eol < 0 else eol + 1
    return start, end


def main():
    check = "--check" in sys.argv[1:]
    main_text = read_main()
    region = build_region(main_text)

    cpp = io.open(CPP_FILE, "rb").read().decode("latin-1")
    match = REGION_RE.search(cpp)
    if match:
        updated = cpp[:match.start()] + region + cpp[match.end():]
    else:
        start, end = find_handwritten_span(cpp)
        updated = cpp[:start] + region + cpp[end:]

    if updated == cpp:
        print("UP_TO_DATE: PyStand.cpp already embeds main.py (%d lines)"
              % (main_text.count("\n") + 1))
        return 0
    if check:
        print("DRIFT: PyStand.cpp does not match main.py - run tools/gen_embed.py")
        return 1
    io.open(CPP_FILE, "wb").write(updated.encode("latin-1"))
    print("GENERATED_OK: embedded %d lines of main.py into PyStand.cpp"
          % (main_text.count("\n") + 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
