"""End to end test of the embedded startup script.

Builds a throwaway application directory - a copy of the built exe, a copy of
the flat files of an embedded python runtime and a fake app.py - and checks
that the embedded copy of main.py really is the entry point, that the exe is
self contained and that the classic .int script path still wins.

Usage:
    python tools/test_matrix.py [--runtime DIR] [--keep] [-v]

--runtime defaults to $PYSTAND_TEST_RUNTIME, then to a runtime next to this
repository.  Without a usable runtime, or without built exes, the script says
so and exits 0 (build with build/verify_build.bat first).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
WORK = os.path.join(BUILD, "_test")

APP_OK = '''\
import json
import os
import sys


def start():
    here = os.path.dirname(os.path.abspath(__file__))
    info = {
        "frozen": getattr(sys, "frozen", "MISSING"),
        "dont_write_bytecode": getattr(sys, "dont_write_bytecode", "MISSING"),
        "pystand_home": getattr(sys, "PYSTAND_HOME", "MISSING"),
        "pystand_script": getattr(sys, "PYSTAND_SCRIPT", "MISSING"),
        "argv": list(sys.argv),
    }
    with open(os.path.join(here, "probe.json"), "w") as fp:
        json.dump(info, fp)
    print("APP_STARTED")
'''

APP_RAISES = '''\
def start():
    raise RuntimeError("boom_xyz")
'''

INT_SCRIPT = '''\
import os
import sys

home = os.environ["PYSTAND_HOME"]
with open(os.path.join(home, "int_ran.txt"), "w") as fp:
    fp.write("yes")
print("INT_RAN")
sys.exit(7)
'''

RESULTS = []


def check(name, condition, detail=""):
    RESULTS.append((name, bool(condition), detail))
    return bool(condition)


def read_text(path):
    if not os.path.isfile(path):
        return ""
    with open(path, "rb") as fp:
        return fp.read().decode("utf-8", "replace")


def clean_env():
    env = dict(os.environ)
    for key in list(env):
        if key.upper().startswith("PYSTAND"):
            del env[key]
    return env


def run(cmd, cwd, timeout=180):
    """Run a command with stdout/stderr redirected to files (no pipes)."""
    out_path = os.path.join(cwd, "_stdout.txt")
    err_path = os.path.join(cwd, "_stderr.txt")
    with open(out_path, "wb") as out, open(err_path, "wb") as err:
        try:
            proc = subprocess.run(cmd, cwd=cwd, stdout=out, stderr=err,
                                  env=clean_env(), timeout=timeout)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            code = "TIMEOUT"
    return code, read_text(out_path), read_text(err_path)


def find_runtime(explicit):
    candidates = [explicit, os.environ.get("PYSTAND_TEST_RUNTIME"),
                  os.path.join(ROOT, "runtime"),
                  os.path.join(ROOT, "source", "runtime")]
    parent = os.path.dirname(ROOT)
    if os.path.isdir(parent):
        for name in sorted(os.listdir(parent)):
            candidates.append(os.path.join(parent, name, "runtime"))
    for path in candidates:
        if not path:
            continue
        if (os.path.isfile(os.path.join(path, "python3.dll"))
                and os.path.isfile(os.path.join(path, "python.exe"))):
            return os.path.abspath(path)
    return None


def copy_runtime(runtime, target):
    """Flat copy: the root files of the runtime are enough to boot python."""
    os.makedirs(target, exist_ok=True)
    for name in os.listdir(runtime):
        source = os.path.join(runtime, name)
        if os.path.isfile(source):
            shutil.copy2(source, os.path.join(target, name))


def prepare(name, runtime, exe, app_source=APP_OK, exe_name=None):
    """Throwaway application directory: exe + runtime + app.py."""
    home = os.path.join(WORK, name)
    if os.path.isdir(home):
        shutil.rmtree(home)
    os.makedirs(home)
    exe_name = exe_name or os.path.basename(exe)
    shutil.copy2(exe, os.path.join(home, exe_name))
    copy_runtime(runtime, os.path.join(home, "runtime"))
    with open(os.path.join(home, "app.py"), "w") as fp:
        fp.write(app_source)
    return home, os.path.join(home, exe_name)


def has_pycache(home):
    for base, dirs, _ in os.walk(home):
        if "__pycache__" in dirs:
            return os.path.join(base, "__pycache__")
    return None


def probe(home):
    path = os.path.join(home, "probe.json")
    if not os.path.isfile(path):
        return None
    with open(path) as fp:
        return json.load(fp)


def case_console_embedded(runtime, exe, verbose):
    home, target = prepare("console-embedded", runtime, exe)
    code, out, err = run([target, "alpha", "beta"], home)
    info = probe(home)
    check("console/embedded: exit code 0", code == 0, "rc=%r err=%s" % (code, err[-400:]))
    check("console/embedded: app.start() ran", "APP_STARTED" in out, out[-200:])
    check("console/embedded: main.py is not needed next to the exe",
          not os.path.isfile(os.path.join(home, "main.py")))
    if not check("console/embedded: probe.json written", info is not None, err[-400:]):
        return
    check("console/embedded: sys.frozen is True", info["frozen"] is True, repr(info["frozen"]))
    check("console/embedded: dont_write_bytecode is True",
          info["dont_write_bytecode"] is True, repr(info["dont_write_bytecode"]))
    check("console/embedded: PYSTAND_HOME is the exe directory",
          os.path.normcase(info["pystand_home"]) == os.path.normcase(home),
          "%r vs %r" % (info["pystand_home"], home))
    check("console/embedded: sys.argv[0] is <home>\\main.py",
          os.path.normcase(info["argv"][0]) == os.path.normcase(os.path.join(home, "main.py")),
          repr(info["argv"][0]))
    check("console/embedded: arguments are passed through",
          info["argv"][1:] == ["alpha", "beta"], repr(info["argv"][1:]))
    check("console/embedded: no __pycache__ left behind", has_pycache(home) is None)
    if verbose:
        print("   probe:", info)


def case_gui_embedded(runtime, exe, verbose):
    home, target = prepare("gui-embedded", runtime, exe)
    code, out, err = run([target], home)
    info = probe(home)
    check("gui/embedded: exit code 0", code == 0, "rc=%r" % (code,))
    if check("gui/embedded: probe.json written", info is not None):
        check("gui/embedded: sys.frozen is True", info["frozen"] is True, repr(info["frozen"]))
        check("gui/embedded: dont_write_bytecode is True",
              info["dont_write_bytecode"] is True, repr(info["dont_write_bytecode"]))
        check("gui/embedded: no __pycache__ left behind", has_pycache(home) is None)
    if verbose:
        print("   probe:", info)


def case_script_wins(runtime, exe, verbose):
    home, target = prepare("script-wins", runtime, exe)
    stem = os.path.splitext(target)[0]
    with open(stem + ".int", "w") as fp:
        fp.write(INT_SCRIPT)
    code, out, err = run([target], home)
    check("script/.int wins: its exit code is kept", code == 7, "rc=%r err=%s" % (code, err[-300:]))
    check("script/.int wins: the .int script ran",
          os.path.isfile(os.path.join(home, "int_ran.txt")), out[-200:])
    check("script/.int wins: the embedded main.py did not run",
          not os.path.isfile(os.path.join(home, "probe.json")))


def case_error_path(runtime, exe, verbose):
    home, target = prepare("error-path", runtime, exe, app_source=APP_RAISES)
    code, out, err = run([target], home)
    check("console/error: exit code 1", code == 1, "rc=%r" % (code,))
    check("console/error: traceback reaches stderr",
          "Traceback" in err and "boom_xyz" in err, err[-300:])


def case_standalone(runtime, verbose):
    home = os.path.join(WORK, "standalone")
    if os.path.isdir(home):
        shutil.rmtree(home)
    os.makedirs(home)
    shutil.copy2(os.path.join(ROOT, "main.py"), os.path.join(home, "main.py"))
    with open(os.path.join(home, "app.py"), "w") as fp:
        fp.write(APP_OK)
    code, out, err = run([os.path.join(runtime, "python.exe"), "main.py"], home)
    info = probe(home)
    check("standalone/main.py: exit code 0", code == 0, "rc=%r err=%s" % (code, err[-400:]))
    if check("standalone/main.py: probe.json written", info is not None, err[-400:]):
        check("standalone/main.py: runs without PyStand",
              info["frozen"] == "MISSING", repr(info["frozen"]))
        check("standalone/main.py: dont_write_bytecode is True",
              info["dont_write_bytecode"] is True, repr(info["dont_write_bytecode"]))
    if verbose:
        print("   probe:", info)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", help="embedded python runtime directory")
    parser.add_argument("--keep", action="store_true", help="keep the test directories")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    exes = [os.path.join(BUILD, "PyStand-console.exe"), os.path.join(BUILD, "PyStand.exe")]
    missing = [path for path in exes if not os.path.isfile(path)]
    if missing:
        print("SKIPPED: build the exes first (build\\verify_build.bat); missing: %s"
              % ", ".join(os.path.basename(p) for p in missing))
        return 0
    runtime = find_runtime(args.runtime)
    if not runtime:
        print("SKIPPED: no embedded python runtime found (use --runtime DIR)")
        return 0
    print("runtime: %s" % runtime)
    print("exes   : %s\n" % ", ".join(os.path.basename(p) for p in exes))

    os.makedirs(WORK, exist_ok=True)
    try:
        case_console_embedded(runtime, exes[0], args.verbose)
        case_gui_embedded(runtime, exes[1], args.verbose)
        case_script_wins(runtime, exes[0], args.verbose)
        case_error_path(runtime, exes[0], args.verbose)
        case_standalone(runtime, args.verbose)
    finally:
        if not args.keep:
            shutil.rmtree(WORK, ignore_errors=True)

    failed = 0
    for name, ok, detail in RESULTS:
        if not ok:
            failed += 1
        print("%s %s%s" % ("PASS" if ok else "FAIL", name,
                           "" if ok or not detail else "   [%s]" % detail))
    print("\n%d checks, %d failed" % (len(RESULTS), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
