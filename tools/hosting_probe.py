"""Hosting probe (SPEC §7.1): what really works on the shared host. Standard library only; run on the host:

    python3.11 hosting_probe.py > probe.md

Creates and removes a temporary virtualenv under ~/tmp. Building packages from source is bounded by a timeout,
heavy pipeline libraries are only checked for binary wheels (the host must not be loaded with long compilations).
"""

from __future__ import annotations

import json
import os
import platform
import resource
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WEB_PACKAGES = ["flask", "jinja2", "requests", "redis", "geoip2", "boto3"]
WHEEL_ONLY_CHECK = ["numpy", "pandas", "pyarrow", "markupsafe", "maxminddb"]
TIMEOUT_S = 600


def run(cmd: list[str], timeout: int = TIMEOUT_S, **kw) -> tuple[int, str, float]:
    t = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
        return p.returncode, (p.stdout + p.stderr)[-3000:], time.time() - t
    except subprocess.TimeoutExpired:
        return -1, f"timeout after {timeout} s", time.time() - t
    except FileNotFoundError as e:
        return -2, str(e), 0.0


def section(title: str) -> None:
    print(f"\n## {title}\n")


def main() -> None:
    print("# Hosting probe")
    print(f"\nhost: {socket.gethostname()}, {platform.platform()}, probe python {sys.version.split()[0]}")

    section("Python interpreters")
    for v in ("3.8", "3.9", "3.10", "3.11", "3.12", "3.13"):
        exe = shutil.which(f"python{v}")
        if exe:
            code, out, _ = run([exe, "-c", "import sys; print(sys.version.split()[0])"])
            print(f"- python{v}: {exe} -> {out.strip()}")

    section("Limits")
    for name in ("RLIMIT_CPU", "RLIMIT_AS", "RLIMIT_DATA", "RLIMIT_NPROC", "RLIMIT_NOFILE"):
        if hasattr(resource, name):
            soft, hard = resource.getrlimit(getattr(resource, name))
            print(f"- {name}: soft={soft} hard={hard}")
    code, out, _ = run(["bash", "-c", "ulimit -a"])
    print("\n```\n" + out.strip() + "\n```")
    usage = shutil.disk_usage(Path.home())
    print(f"\n- home filesystem free: {usage.free / 1e9:.0f} GB (account quota: see `devil info account`)")
    code, out, _ = run(["devil", "info", "account"])
    if code == 0:
        print("\n```\n" + out.strip() + "\n```")

    section("Tools")
    for tool in ("git", "redis-cli", "redis-server", "memcached", "cc", "gcc", "clang", "make", "cmake", "rustc"):
        print(f"- {tool}: {shutil.which(tool) or 'not found'}")
    code, out, _ = run(["devil", "redis"], timeout=30)
    print(f"- `devil redis`: exit {code}: {out.strip()[:300]}")

    section("pip in a fresh virtualenv (python3.11)")
    py = shutil.which("python3.11") or sys.executable
    base = Path.home() / "tmp"
    base.mkdir(exist_ok=True)
    venv = Path(tempfile.mkdtemp(prefix="lp_probe_", dir=base))
    try:
        code, out, secs = run([py, "-m", "venv", str(venv)])
        print(f"- venv: exit {code} ({secs:.0f} s)")
        pip = str(venv / "bin" / "pip")
        run([pip, "install", "-q", "--upgrade", "pip"])
        results = {}
        for pkg in WEB_PACKAGES:
            code, out, secs = run([pip, "install", "-q", pkg])
            results[pkg] = (code, secs)
            print(f"- install {pkg}: {'OK' if code == 0 else 'FAIL'} ({secs:.0f} s)")
            if code != 0:
                print("\n```\n" + out[-1500:] + "\n```\n")
        code, out, _ = run([pip, "list", "--format=json"])
        if code == 0:
            pkgs = {p["name"].lower(): p["version"] for p in json.loads(out[out.index("[") :])}
            print(f"- installed: {', '.join(f'{k}=={v}' for k, v in sorted(pkgs.items()))}")
        code, out, _ = run([str(venv / "bin" / "python"), "-c", "import markupsafe._speedups"])
        print(f"- markupsafe C speedups: {'yes' if code == 0 else 'no (pure Python fallback)'}")

        section("Binary wheels available (no source builds attempted)")
        tmpd = venv / "dl"
        for pkg in WHEEL_ONLY_CHECK:
            code, out, secs = run(
                [pip, "download", "-q", "--only-binary", ":all:", "--no-deps", "-d", str(tmpd), pkg], timeout=120
            )
            print(f"- {pkg}: {'wheel available' if code == 0 else 'no wheel (would compile from source)'}")

        section("CPU timing (blend of 5 models x 168 h x 6 variables, pure Python)")
        code, out, secs = run(
            [
                str(venv / "bin" / "python"),
                "-c",
                "import random,time;t=time.time()\n"
                "m=[[random.random() for _ in range(168*6)] for _ in range(5)];w=[0.2]*5\n"
                "for _ in range(100): [sum(w[k]*m[k][i] for k in range(5)) for i in range(168*6)]\n"
                "print(round((time.time()-t)/100*1000,2))",
            ]
        )
        print(f"- one blend: {out.strip()} ms")
    finally:
        shutil.rmtree(venv, ignore_errors=True)

    section("Environment")
    print(f"- PATH: {os.environ.get('PATH')}")
    print(f"- HOME: {Path.home()}")


if __name__ == "__main__":
    main()
