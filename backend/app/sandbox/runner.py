"""Parent side of the sandbox: launch the child, feed it a job, enforce a wall clock.

On POSIX we additionally clamp the child with `resource` limits via preexec_fn
(CPU seconds, address space, no forks). On Windows those aren't available, so we
rely on the import whitelist + blocked open + hard wall-clock timeout; this keeps
local dev on Windows working while production (Linux worker container) gets the
full treatment. Either way the untrusted code runs in a separate process that we
kill on timeout — never `exec` in the worker itself.

The child is launched as `python -m app.sandbox.child`, so it must be able to
import the `app` package. We do NOT use `-I`/`-E` (isolated mode strips the import
path and ignores PYTHONPATH); instead we set an explicit `cwd` and `PYTHONPATH`
pointing at the backend root, and scrub credentials out of the child's env.
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_IS_POSIX = sys.platform != "win32"

# runner.py -> sandbox -> app -> backend
_BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Never hand the untrusted child our API keys or other secrets via the environment.
_SECRET_HINTS = ("GROQ", "GEMINI", "LAZARUS", "SECRET", "TOKEN", "PASSWORD", "API_KEY")


@dataclass
class SandboxResult:
    ok: bool
    records: list[dict] | None
    error: str | None


def _child_env() -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if not any(hint in k.upper() for hint in _SECRET_HINTS)
    }
    env["PYTHONPATH"] = str(_BACKEND_ROOT)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _posix_limits(memory_mb: int, cpu_seconds: int):
    import resource

    def _apply() -> None:
        mem = memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
        resource.setrlimit(resource.RLIMIT_NPROC, (0, 0))  # no forks/threads-via-fork
        resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))  # cannot write file bytes

    return _apply


def run_extractor(
    code: str, html: str, *, timeout: int = 10, memory_mb: int = 1024
) -> SandboxResult:
    job = json.dumps({"code": code, "html": html})
    popen_kwargs: dict = {}
    if _IS_POSIX:
        # CPU limit sits ABOVE the wall clock so the wall-clock timeout wins for a
        # busy loop (giving a deterministic "timed out"); the CPU cap is a backstop.
        popen_kwargs["preexec_fn"] = _posix_limits(memory_mb, timeout + 5)

    try:
        proc = subprocess.run(
            # -B: no .pyc writes (RLIMIT_FSIZE=0 would SIGXFSZ on a bytecode write).
            # -s: skip the user site dir. NOT -I/-E, so PYTHONPATH below is honoured.
            [sys.executable, "-B", "-s", "-m", "app.sandbox.child"],
            input=job,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_BACKEND_ROOT),
            env=_child_env(),
            **popen_kwargs,
        )
    except subprocess.TimeoutExpired:
        return SandboxResult(ok=False, records=None, error=f"timed out after {timeout}s")

    if proc.returncode != 0 and not proc.stdout.strip():
        detail = proc.stderr.strip()[-300:] or f"exit code {proc.returncode}"
        return SandboxResult(ok=False, records=None, error=f"sandbox crashed: {detail}")

    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return SandboxResult(
            ok=False, records=None, error=f"unreadable sandbox output: {proc.stdout[:200]!r}"
        )

    if payload.get("ok"):
        return SandboxResult(ok=True, records=payload["records"], error=None)
    return SandboxResult(ok=False, records=None, error=payload.get("error", "unknown error"))
