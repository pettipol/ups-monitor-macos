#!/usr/bin/env python3
"""Qualify one explicit upsc binary using only ephemeral synthetic loopback data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading


def exercise(binary: Path, libraries: Path, mode: str) -> dict[str, object]:
    commands: list[str] = []
    errors: list[str] = []
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(5)
    port = server.getsockname()[1]

    def serve() -> None:
        try:
            with server:
                connection, _ = server.accept()
                with connection:
                    connection.settimeout(3)
                    reader = connection.makefile("rb")
                    for _ in range(4):
                        line = reader.readline(257)
                        if not line:
                            return
                        command = line.decode("ascii").strip()
                        commands.append(command)
                        if command == "STARTTLS":
                            connection.sendall(b"ERR FEATURE-NOT-SUPPORTED\n")
                        elif command == "LIST VAR fixture":
                            connection.sendall(
                                b"BEGIN LIST VAR fixture\n"
                                b'VAR fixture ups.status "OL"\n'
                                b'VAR fixture battery.charge "73"\n'
                            )
                            if mode == "complete":
                                connection.sendall(b"END LIST VAR fixture\n")
                            elif mode == "error":
                                connection.sendall(b"ERR DATA-STALE\n")
                            elif mode == "wrong-end":
                                connection.sendall(b"END LIST VAR another-fixture\n")
                            elif mode == "short-end":
                                connection.sendall(b"END LIST\n")
                            elif mode == "extra-end":
                                connection.sendall(b"END LIST VAR fixture unexpected\n")
                            return
                        else:
                            errors.append("unexpected-command")
                            return
        except (OSError, UnicodeError):
            errors.append("fixture-server-error")

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    with tempfile.TemporaryDirectory(prefix="upsc-fixture-") as home:
        environment = {
            "PATH": "/usr/bin:/bin",
            "HOME": home,
            "LC_ALL": "C",
            "NUT_DEBUG_LEVEL": "0",
            "DYLD_LIBRARY_PATH": str(libraries),
        }
        try:
            result = subprocess.run(
                [str(binary), "-j", "-A", "none", "-W", "2",
                 f"fixture@127.0.0.1:{port}"],
                env=environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=4,
                check=False,
            )
        finally:
            thread.join(timeout=6)
    if thread.is_alive() or errors:
        raise RuntimeError("Synthetic fixture did not complete cleanly")
    if not commands or commands[-1] != "LIST VAR fixture":
        raise RuntimeError("Client did not request the synthetic fixture")
    try:
        payload = json.loads(result.stdout)
    except (ValueError, UnicodeError):
        payload = None
    accepted = result.returncode == 0 and isinstance(payload, dict) and "error" not in payload
    return {
        "scenario": mode,
        "exit_code": result.returncode,
        "accepted_as_complete": accepted,
        "expected_acceptance": mode == "complete",
        "commands": commands,
        "stdout_bytes": len(result.stdout),
        "stderr_bytes": len(result.stderr),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--libraries", required=True, type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    libraries = args.libraries.resolve(strict=True)
    scenarios = ("complete", "truncated", "error", "wrong-end", "short-end", "extra-end")
    results = [exercise(binary, libraries, mode) for mode in scenarios]
    print(json.dumps({"synthetic_only": True, "results": results}, indent=2))
    return 0 if all(r["accepted_as_complete"] == r["expected_acceptance"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
