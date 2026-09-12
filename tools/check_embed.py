"""Verify that the startup script embedded in PyStand.cpp really is main.py.

Three checks, all read only:

  1. the region between the BEGIN/END markers equals main.py, byte for byte
     after newline normalisation, and contains ASCII only;
  2. that region compiles on its own;
  3. the complete embedded script - bootstrap + main.py - compiles for both the
     windowed and the console build (the #ifndef PYSTAND_CONSOLE branches).

Exit code 0 when everything matches, 1 otherwise, so it can guard a build.
"""

import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CPP_FILE = os.path.join(ROOT, "PyStand.cpp")
MAIN_FILE = os.path.join(ROOT, "main.py")

MARK_BEGIN = "// >>> BEGIN main.py"
MARK_END = "// <<< END main.py"

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}
QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')


def normalize(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def c_unescape(text):
    out = []
    i = 0
    while i < len(text):
        char = text[i]
        if char == "\\":
            if i + 1 >= len(text):
                raise SystemExit("ERROR: dangling backslash in literal")
            nxt = text[i + 1]
            if nxt not in ESCAPES:
                raise SystemExit("ERROR: unsupported escape \\%s in literal" % nxt)
            out.append(ESCAPES[nxt])
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out)


def read_cpp():
    return io.open(CPP_FILE, "rb").read().decode("latin-1")


def startup_body(cpp):
    anchor = cpp.index("const char *startup_script =")
    end = cpp.index('"";', anchor) + len('"";')
    return cpp[cpp.index("=", anchor) + 1:end]


def marked_region(cpp):
    begin = cpp.index(MARK_BEGIN)
    begin = cpp.index("\n", begin) + 1
    end = cpp.index(MARK_END)
    end = cpp.rfind("\n", 0, end) + 1
    return cpp[begin:end]


def embedded_main(cpp):
    text = "".join(c_unescape(lit) for lit in QUOTED.findall(marked_region(cpp)))
    return normalize(text)


def statements(cpp):
    """Line stream of the literal: ('py', text) or ('cpp', directive)."""
    stream = []
    for line in startup_body(cpp).split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            stream.append(("cpp", stripped))
            continue
        for lit in QUOTED.findall(stripped):
            stream.append(("py", c_unescape(lit)))
    return stream


def build(stream, console):
    """Resolve #ifdef/#ifndef/#else/#endif for one build flavour."""
    out = []
    stack = []
    active = True
    for kind, text in stream:
        if kind == "py":
            if active:
                out.append(text)
            continue
        parts = text.split()
        directive = parts[0]
        if directive in ("#ifdef", "#ifndef"):
            target = len(parts) > 1 and parts[1] == "PYSTAND_CONSOLE"
            cond = console if directive == "#ifdef" else not console
            stack.append((active, cond))
            active = active and cond
        elif directive == "#else":
            if not stack:
                raise SystemExit("ERROR: #else without #if")
            parent, cond = stack[-1]
            stack[-1] = (parent, not cond)
            active = parent and not cond
        elif directive == "#endif":
            if not stack:
                raise SystemExit("ERROR: #endif without #if")
            parent, _ = stack.pop()
            active = parent
        else:
            raise SystemExit("ERROR: unexpected directive %s" % directive)
    if stack:
        raise SystemExit("ERROR: unterminated #if in the embedded script")
    return "".join(out)


def main():
    failures = []

    cpp = read_cpp()
    wanted = normalize(io.open(MAIN_FILE, "rb").read().decode("ascii"))
    got = embedded_main(cpp)

    if got != wanted:
        failures.append("embedded region differs from main.py (%d vs %d chars)"
                        % (len(got), len(wanted)))
        for number, (a, b) in enumerate(zip(got.split("\n"), wanted.split("\n")), 1):
            if a != b:
                failures.append("  first difference on line %d:\n    cpp: %s\n    py : %s"
                                % (number, a, b))
                break
        else:
            failures.append("  the region equals main.py up to the shorter text; "
                            "the remainder differs")
    else:
        print("MATCH: marked region == main.py (%d lines)" % (len(wanted.split("\n"))))

    if any(byte > 0x7f for byte in got.encode("latin-1")):
        failures.append("embedded region contains non-ASCII characters")

    stream = statements(cpp)
    for label, console in (("gui", False), ("console", True)):
        source = build(stream, console)
        try:
            compile(source, "<embedded:%s>" % label, "exec")
        except SyntaxError as exc:
            failures.append("%s build does not compile: %s" % (label, exc))
            continue
        print("COMPILE_OK: %s build, %d chars, %d lines"
              % (label, len(source), source.count("\n")))

    if failures:
        for line in failures:
            print(line)
        return 1
    print("CHECK_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
