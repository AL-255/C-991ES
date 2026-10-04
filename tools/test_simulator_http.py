#!/usr/bin/env python3
"""Exercise the actual simulator HTTP server and C CLI, without arithmetic mocks."""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


class Checks:
    def __init__(self):
        self.rows = []

    def require(self, condition, name, detail=None):
        self.rows.append({"name": name, "passed": bool(condition), "detail": detail})
        if not condition:
            raise AssertionError(f"{name}: {detail!r}")


class Client:
    def __init__(self, port):
        self.port = port
        self.cookie = None

    def request(self, path, payload=None, *, method=None, headers=None, raw=None):
        method = method or ("POST" if payload is not None or raw is not None else "GET")
        body = raw if raw is not None else (
            json.dumps(payload).encode() if payload is not None else None)
        outgoing = {"Content-Type": "application/json"} if method == "POST" else {}
        if self.cookie:
            outgoing["Cookie"] = self.cookie
        outgoing.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        try:
            connection.request(method, path, body=body, headers=outgoing)
            response = connection.getresponse()
            content = response.read()
            response_headers = dict(response.getheaders())
            if response.getheader("Set-Cookie"):
                self.cookie = response.getheader("Set-Cookie").split(";", 1)[0]
            if int(response.getheader("Content-Length", -1)) != len(content):
                raise AssertionError("HTTP response length does not match its body")
            return response.status, response_headers, content
        finally:
            connection.close()

    def json(self, path, payload=None, **kwargs):
        status, headers, body = self.request(path, payload, **kwargs)
        return status, headers, json.loads(body)


def run_checks(port, cli, checks):
    a, b = Client(port), Client(port)
    status, _, result = a.json("/api/health")
    checks.require(status == 200 and result == {"status": "ok", "engine": "high-level-c"},
                   "health", result)
    for path, filename, mime in (("/", "index.html", "text/html"),
                                 ("/app.js", "app.js", "text/javascript"),
                                 ("/engine.js", "engine.js", "text/javascript"),
                                 ("/styles.css", "styles.css", "text/css")):
        status, headers, body = a.request(path)
        checks.require(status == 200 and body == (ROOT / "simulator/web" / filename).read_bytes()
                       and headers["Content-Type"].startswith(mime)
                       and headers.get("X-Content-Type-Options") == "nosniff",
                       f"asset {filename}", status)
    for path in ("/missing", "/../csrc/CMakeLists.txt", "/%2e%2e/csrc/CMakeLists.txt"):
        checks.require(a.json(path)[0] == 404, f"unknown asset {path}")

    def evaluate(client, expression, **settings):
        status, headers, result = client.json("/api/evaluate", {"expression": expression, **settings})
        checks.require(status == 200, f"evaluate HTTP {expression}", result)
        checks.require(result.get("expression") == expression and
                       result.get("status") in ("ok", "error", "unsupported"),
                       f"response schema {expression}", result)
        checks.require(re.fullmatch(r"[0-9a-fA-F]{768}", result.get("framebuffer", "")) is not None
                       and re.fullmatch(r"[0-9a-fA-F]{20}", result.get("real", "")) is not None
                       and re.fullmatch(r"[0-9a-fA-F]{20}", result.get("imag", "")) is not None,
                       f"native display/records {expression}")
        return result, headers

    result, headers = evaluate(a, "2+3")
    checks.require(result["status"] == "ok" and result["plain"] == "5", "native arithmetic", result)
    checks.require("HttpOnly" in headers.get("Set-Cookie", "") and
                   "SameSite=Strict" in headers.get("Set-Cookie", ""), "session cookie")
    checks.require(evaluate(a, "Ans+2")[0]["plain"] == "7", "retained Ans")
    checks.require(evaluate(b, "Ans")[0]["plain"] == "0", "independent session Ans")
    checks.require(a.cookie != b.cookie, "different session identifiers")
    evaluate(b, "11")
    checks.require(a.json("/api/reset", {})[2] == {"status": "ok"}, "reset response")
    checks.require(evaluate(a, "Ans")[0]["plain"] == "0", "reset clears Ans")
    checks.require(evaluate(b, "Ans")[0]["plain"] == "11", "reset preserves other session")
    checks.require(evaluate(a, "12->A")[0]["status"] == "ok", "store variable")
    checks.require(evaluate(a, "A+1")[0]["plain"] == "13", "retained variable")
    checks.require(evaluate(b, "A")[0]["plain"] == "0", "variable session isolation")
    a.json("/api/reset", {})
    checks.require(evaluate(a, "A")[0]["plain"] == "0", "reset clears variable")
    result, _ = evaluate(a, "sin(30)", angle=0)
    checks.require(result["status"] == "ok" and result["plain"] in ("1/2", "(1)/(2)", "0.5"),
                   "degree setting reaches C", result)
    for expression in ("1/0", "sqrt(-1)"):
        result, _ = evaluate(a, expression)
        checks.require(result["status"] == "error" and isinstance(result.get("native_status"), int),
                       f"native error {expression}", result)
    result, _ = evaluate(a, "1+")
    checks.require(result["status"] in ("error", "unsupported") and result.get("error"),
                   "incomplete expression rejection", result)
    checks.require(evaluate(a, "4+5")[0]["plain"] == "9", "server/engine recover after native errors")
    result, _ = evaluate(a, " " * 4095 + "5")
    checks.require(result["status"] == "ok" and result["plain"] == "5",
                   "4096-byte expression boundary accepted")

    invalid = [b"{", b"[]", b"null", b"\xff", b"", b"{}",
               json.dumps({"expression": "5\x00+7"}).encode(),
               json.dumps({"expression": "\ud800"}).encode(),
               json.dumps({"expression": 5}).encode(),
               json.dumps({"expression": "5", "mode": True}).encode(),
               json.dumps({"expression": "5", "mode": 6}).encode(),
               json.dumps({"expression": "5", "angle": -1}).encode(),
               json.dumps({"expression": "5", "math": 2}).encode(),
               json.dumps({"expression": "x" * 4097}).encode(),
               json.dumps({"expression": "é" * 2049}, ensure_ascii=False).encode(), b" " * 8193]
    for n, body in enumerate(invalid):
        status, _, result = a.json("/api/evaluate", raw=body)
        checks.require(status == 400 and result.get("status") == "error",
                       f"invalid request {n}", result)
    for length in ("invalid", "-1", "0", "8193"):
        status, _, _ = a.json("/api/evaluate", raw=b"{}", headers={"Content-Length": length})
        checks.require(status == 400, f"invalid content length {length}")
    checks.require(a.json("/api/evaluate", {"expression": "5"},
                          headers={"Origin": "http://example.invalid"})[0] == 403,
                   "foreign Origin rejected")
    checks.require(a.json("/api/evaluate", {"expression": "5"},
                          headers={"Origin": "http://["})[0] in (400, 403),
                   "malformed Origin rejected")
    status, _, _ = a.json("/api/evaluate", {"expression": "5"},
                          headers={"Origin": f"http://127.0.0.1:{port}"})
    checks.require(status == 200, "same Origin accepted")
    checks.require(a.json("/api/unknown", {})[0] == 404, "unknown API")
    checks.require(evaluate(a, "Ans")[0]["plain"] == "5", "rejected requests preserve Ans")

    def command(arguments, input_bytes=None):
        return subprocess.run([str(cli), *arguments], input=input_bytes, capture_output=True, timeout=15)

    response = command(["2+3"])
    result = json.loads(response.stdout)
    checks.require(response.returncode == 0 and result["status"] == "ok" and result["plain"] == "5",
                   "CLI expression", result)
    response = command(["--", "--2"])
    checks.require(response.returncode == 0 and json.loads(response.stdout)["plain"] == "2",
                   "CLI option delimiter permits expression", response.stderr.decode())
    response = command(["--angle", "deg", "sin(30)"])
    checks.require(response.returncode == 0 and json.loads(response.stdout)["status"] == "ok",
                   "CLI settings", response.stderr.decode())
    response = command(["1/0"])
    checks.require(response.returncode == 0 and json.loads(response.stdout)["status"] == "error",
                   "CLI native error JSON", response.stderr.decode())
    response = command(["--interactive"], b"\n2+3\nAns+2\n:reset\nAns\n:quit\n999\n")
    rows = [json.loads(line) for line in response.stdout.splitlines()]
    checks.require(response.returncode == 0 and len(rows) == 4 and
                   [rows[0]["plain"], rows[1]["plain"], rows[3]["plain"]] == ["5", "7", "0"]
                   and rows[2] == {"status": "ok", "reset": True},
                   "CLI interactive Ans/reset/quit", rows)
    response = command(["--interactive"], b"x" * 5000 + b"\n2+3\n:quit\n")
    rows = [json.loads(line) for line in response.stdout.splitlines()]
    checks.require(response.returncode == 0 and len(rows) == 2 and rows[0]["status"] == "error"
                   and rows[1]["plain"] == "5", "CLI oversized line recovery", rows)
    response = command(["--interactive"], b"5\x00+7\n2+3\n:quit\n")
    rows = [json.loads(line) for line in response.stdout.splitlines()]
    checks.require(response.returncode == 0 and len(rows) == 2 and rows[0]["status"] == "error"
                   and rows[1]["plain"] == "5", "CLI NUL line rejection preserves next command", rows)
    for arguments in (["--help"], [], ["--mode"], ["--angle"],
                      ["--bogus"], ["--mode", "invalid", "5"], ["--interactive", "5"]):
        response = command(arguments)
        checks.require(response.returncode == (0 if arguments == ["--help"] else 2),
                       f"CLI arguments {arguments}", response.returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "analysis/build/simulator")
    parser.add_argument("--no-build", action="store_true", help="Use a root-frozen, already built engine")
    parser.add_argument("--report", type=Path, help="Optional diagnostic JSON report")
    args = parser.parse_args()
    build_dir = args.build_dir.resolve()
    cli = build_dir / ("fx991sim.exe" if os.name == "nt" else "fx991sim")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    checks = Checks()
    source_paths = [Path(__file__).resolve(), ROOT / "simulator/serve.py", ROOT / "csrc/app/fx991sim.c"]
    source_paths += sorted((ROOT / "simulator/web").glob("*"))
    source_paths += sorted((ROOT / "csrc/app").glob("fx_simulator*"))
    digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    pins = {str(p.relative_to(ROOT)): digest(p) for p in source_paths if p.is_file()}
    artifact_dir = ROOT / "analysis/build/simulator-http"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    error = None
    artifact_pins = {}
    with tempfile.TemporaryFile(dir=artifact_dir) as log:
        command = [sys.executable, str(ROOT / "simulator/serve.py"), "--port", str(port),
                   "--build-dir", str(build_dir)]
        if args.no_build:
            command.append("--no-build")
        process = subprocess.Popen(command, stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Simulator server exited {process.returncode}")
                try:
                    if Client(port).json("/api/health")[0] == 200:
                        break
                except (OSError, http.client.HTTPException):
                    time.sleep(0.05)
            else:
                raise TimeoutError("Simulator server startup timed out")
            artifacts = [cli]
            for name in ("libfx991_simulator.so", "libfx991_simulator.dylib", "fx991_simulator.dll"):
                for directory in (build_dir, build_dir / "Release", build_dir / "Debug"):
                    if (directory / name).is_file():
                        artifacts.append(directory / name)
            artifact_pins = {str(p): digest(p) for p in artifacts}
            run_checks(port, cli, checks)
            checks.require(all(digest(ROOT / p) == expected for p, expected in pins.items()),
                           "transport/engine/UI source pins unchanged")
            checks.require(all(digest(Path(p)) == expected for p, expected in artifact_pins.items()),
                           "actual CLI/library artifacts unchanged")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            log.seek(0)
            server_log = log.read().decode(errors="replace")
    report = {"passed": error is None, "checks": checks.rows, "error": error,
              "source_pins": pins, "build_dir": str(build_dir), "server_log": server_log,
              "artifact_pins": artifact_pins,
              "scope": "Actual HTTP/CLI integration; no mock arithmetic; not full firmware parity"}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    if error:
        print(error, file=sys.stderr)
        print(server_log[-4000:], file=sys.stderr)
        return 1
    print(f"Simulator HTTP/CLI: {len(checks.rows)} actual integration checks PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
