"""Sandbox child process: exec untrusted extractor code under lockdown, emit JSON.

Never imported by the parent — launched as `python -m app.sandbox.child` so a crash,
OOM-kill, or timeout takes down only this process. Reads a JSON job on stdin
({"code", "html"}) and writes a JSON result on stdout ({"ok", "records"|"error"}).

Defence in depth, weakest to strongest:
1. An import guard that denies the network / subprocess / native-code / filesystem
   roots (below), plus `open` neutralised. This is a *blocklist*, not a whitelist:
   selectolax is Cython-built and transitively imports large swathes of the stdlib
   (typing -> collections -> sys, logging -> os/threading, ...), so a whitelist is
   unworkable. The guard stops naive escape attempts; it is NOT a hard boundary —
   in-process Python sandboxes are bypassable (e.g. object-graph gadgets).
2. POSIX resource limits (parent's preexec_fn): no forks (RLIMIT_NPROC=0), no file
   bytes written (RLIMIT_FSIZE=0), address-space + CPU caps. This is what actually
   stops fork bombs and file writes on the Linux worker.
3. A separate, killable process with a hard wall-clock timeout enforced by the parent.
In production the worker container also has no network egress, which is the real
network boundary; the import guard is only the first line.
"""

import builtins
import json
import sys

# Roots that grant network, subprocess/exec, native code, or arbitrary filesystem
# access. None of these are needed by selectolax's import chain or by the safe libs
# an extractor uses (re, json, datetime, collections, urllib.parse, html, ...), so
# denying them costs the extractor nothing.
_BLOCKED_ROOTS = frozenset({
    # networking, every layer
    "socket", "_socket", "ssl", "_ssl", "select", "selectors", "asyncio",
    "http", "ftplib", "smtplib", "poplib", "imaplib", "telnetlib", "nntplib",
    "xmlrpc", "socketserver", "requests", "httpx", "aiohttp", "urllib3",
    "websocket", "websockets", "pycurl", "paramiko",
    # subprocess / exec / native code
    "subprocess", "_posixsubprocess", "_winapi", "ctypes", "_ctypes", "cffi",
    "multiprocessing", "_multiprocessing", "pty", "tty", "termios",
    # filesystem writes / arbitrary paths
    "shutil", "tempfile", "pathlib", "glob", "fileinput", "mmap", "fcntl",
    "pickle", "_pickle", "shelve", "dbm", "sqlite3",
    # host / packaging / misc escape surface
    "winreg", "msvcrt", "webbrowser", "ensurepip", "pip", "setuptools",
    "distutils", "ptrace",
})

# urllib.parse is safe and used by extractors; only its network submodules are denied.
_BLOCKED_NAMES = frozenset({
    "urllib.request", "urllib.error", "urllib.response", "urllib.robotparser",
})

_real_import = builtins.__import__


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0]
    if name in _BLOCKED_NAMES or name in _BLOCKED_ROOTS or root in _BLOCKED_ROOTS:
        raise ImportError(f"import of {name!r} is blocked in the sandbox")
    return _real_import(name, globals, locals, fromlist, level)


def _blocked_open(*args, **kwargs):
    raise PermissionError("file access is blocked in the sandbox")


def _install_lockdown() -> None:
    builtins.__import__ = _guarded_import
    builtins.open = _blocked_open


def main() -> None:
    raw = sys.stdin.read()
    try:
        job = json.loads(raw)
        code = job["code"]
        html = job["html"]
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"bad sandbox input: {exc}"}))
        return

    _install_lockdown()

    sandbox_globals: dict = {"__builtins__": builtins}
    try:
        compiled = compile(code, "<extractor>", "exec")
    except SyntaxError as exc:
        print(json.dumps({"ok": False, "error": f"SyntaxError: {exc}"}))
        return

    try:
        exec(compiled, sandbox_globals)  # noqa: S102 — the whole point of the sandbox
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return

    extract = sandbox_globals.get("extract")
    if not callable(extract):
        print(json.dumps({"ok": False, "error": "no callable extract(html) found"}))
        return

    try:
        records = extract(html)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}))
        return

    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        print(json.dumps({"ok": False, "error": "extract() must return list[dict]"}))
        return

    try:
        serialised = json.dumps({"ok": True, "records": records})
    except (TypeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": f"records are not JSON-serialisable: {exc}"}))
        return
    print(serialised)


if __name__ == "__main__":
    main()
