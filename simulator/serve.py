#!/usr/bin/env python3
"""Serve the C-991ES UI and carry requests to the high-level C engine."""
from __future__ import annotations

import argparse
import atexit
import ctypes
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
WEB = Path(__file__).resolve().parent / "dist"
RESPONSE_BYTES = 32768


def build_engine(build_dir: Path) -> None:
    scratch = build_dir.resolve() / "compiler-tmp"
    scratch.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, TMPDIR=str(scratch))
    subprocess.run(["cmake", "-S", str(ROOT / "csrc"), "-B", str(build_dir),
                    "-DCMAKE_BUILD_TYPE=Release", "-DBUILD_TESTING=OFF"],
                   env=environment, check=True)
    subprocess.run(["cmake", "--build", str(build_dir), "--target",
                    "fx991_simulator", "fx991sim", "--parallel", "4"],
                   env=environment, check=True)


def find_library(build_dir: Path) -> Path:
    for name in ("libfx991_simulator.so", "libfx991_simulator.dylib",
                 "fx991_simulator.dll"):
        for directory in (build_dir, build_dir / "Release", build_dir / "Debug"):
            candidate = directory / name
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(f"C simulator library is absent in {build_dir}; run without --no-build")


class Engine:
    """Transport only: C owns arithmetic, state, formatting and LCD pixels."""

    def __init__(self, library: Path):
        self.native = ctypes.CDLL(str(library.resolve()))
        self.native.fxsim_create.argtypes = []
        self.native.fxsim_create.restype = ctypes.c_void_p
        self.native.fxsim_destroy.argtypes = [ctypes.c_void_p]
        self.native.fxsim_destroy.restype = None
        self.native.fxsim_reset.argtypes = [ctypes.c_void_p]
        self.native.fxsim_reset.restype = None
        self.native.fxsim_evaluate.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                             ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                                             ctypes.c_char_p, ctypes.c_size_t]
        self.native.fxsim_evaluate.restype = ctypes.c_int
        self.sessions: dict[str, tuple[int, float]] = {}
        atexit.register(self.close)

    def close(self) -> None:
        for pointer, _ in self.sessions.values():
            self.native.fxsim_destroy(pointer)
        self.sessions.clear()

    def session(self, cookie: str | None) -> tuple[str, int]:
        now = time.monotonic()
        expired = [key for key, (_, seen) in self.sessions.items() if now - seen > 3600]
        for key in expired:
            pointer, _ = self.sessions.pop(key)
            self.native.fxsim_destroy(pointer)
        token = None
        if cookie:
            parsed = SimpleCookie()
            try:
                parsed.load(cookie)
                if "fxsim" in parsed:
                    token = parsed["fxsim"].value
            except Exception:
                token = None
        if token not in self.sessions:
            if len(self.sessions) >= 64:
                oldest = min(self.sessions, key=lambda key: self.sessions[key][1])
                pointer, _ = self.sessions.pop(oldest)
                self.native.fxsim_destroy(pointer)
            pointer = self.native.fxsim_create()
            if not pointer:
                raise MemoryError("Unable to create a calculator session")
            token = secrets.token_hex(16)
        else:
            pointer, _ = self.sessions[token]
        self.sessions[token] = pointer, now
        return token, pointer

    def evaluate(self, pointer: int, request: dict) -> dict:
        expression = request.get("expression")
        if not isinstance(expression, str) or "\x00" in expression:
            raise ValueError("Expression must be text without NUL characters")
        encoded = expression.encode("utf-8")
        if len(encoded) > 4096:
            raise ValueError("Expression is too long")
        values = []
        for key, default, maximum in (("mode", 0, 5), ("angle", 0, 2), ("math", 1, 1)):
            value = request.get(key, default)
            if type(value) is not int or not 0 <= value <= maximum:
                raise ValueError(f"Invalid {key} setting")
            values.append(value)
        output = ctypes.create_string_buffer(RESPONSE_BYTES)
        status = self.native.fxsim_evaluate(pointer, encoded, *values, output, len(output))
        if status != 0:
            raise RuntimeError("C engine rejected the request")
        result = json.loads(output.value)
        if not isinstance(result, dict):
            raise RuntimeError("Invalid response from C engine")
        result["expression"] = expression
        return result


def handler_for(engine: Engine):
    class Handler(BaseHTTPRequestHandler):
        server_version = "C-991ES/1"

        def reply(self, status: int, content: bytes, mime: str, token: str | None = None):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if token:
                self.send_header("Set-Cookie", f"fxsim={token}; Path=/; HttpOnly; SameSite=Strict")
            self.end_headers()
            self.wfile.write(content)

        def json_reply(self, status: int, value: dict, token: str | None = None):
            self.reply(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", token)

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/api/health":
                self.json_reply(200, {"status": "ok", "engine": "high-level-c"})
                return
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/index.html": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/engine.js": ("engine.js", "text/javascript; charset=utf-8"),
                     "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                     "/fx991sim.js": ("fx991sim.js", "text/javascript; charset=utf-8"),
                     "/fx991sim.wasm": ("fx991sim.wasm", "application/wasm"),
                     "/device/": ("device/index.html", "text/html; charset=utf-8"),
                     "/device/index.html": ("device/index.html", "text/html; charset=utf-8"),
                     "/device/app.js": ("device/app.js", "text/javascript; charset=utf-8"),
                     "/device/lcd-indicators.js": ("device/lcd-indicators.js", "text/javascript; charset=utf-8"),
                     "/device/styles.css": ("device/styles.css", "text/css; charset=utf-8"),
                     "/device/calculator-face.svg": ("device/calculator-face.svg", "image/svg+xml")}
            item = files.get(path)
            if not item:
                self.json_reply(404, {"error": "Not found"})
                return
            name, mime = item
            try:
                self.reply(200, (WEB / name).read_bytes(), mime)
            except FileNotFoundError:
                self.json_reply(503, {"error": "Build the virtual calculator first: python3 simulator/build_web.py"})

        def do_POST(self):
            path = urlsplit(self.path).path
            if path not in ("/api/evaluate", "/api/reset"):
                self.json_reply(404, {"error": "Not found"})
                return
            try:
                origin = self.headers.get("Origin")
                if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                    self.json_reply(403, {"error": "Use the simulator's own page"})
                    return
                count = int(self.headers.get("Content-Length", "0"))
                if not 0 < count <= 8192:
                    raise ValueError("Invalid request size")
                request = json.loads(self.rfile.read(count))
                if not isinstance(request, dict):
                    raise ValueError("Request must be a JSON object")
                token, pointer = engine.session(self.headers.get("Cookie"))
                if path == "/api/reset":
                    engine.native.fxsim_reset(pointer)
                    result = {"status": "ok"}
                else:
                    result = engine.evaluate(pointer, request)
                self.json_reply(200, result, token)
            except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
                self.json_reply(400, {"status": "error", "error": str(exc)})
            except (RuntimeError, MemoryError) as exc:
                self.json_reply(500, {"status": "error", "error": str(exc)})

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9910)
    parser.add_argument("--build-dir", type=Path, default=ROOT / "analysis/build/simulator")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        if not args.no_build:
            build_engine(args.build_dir)
        engine = Engine(find_library(args.build_dir))
        server = HTTPServer(("127.0.0.1", args.port), handler_for(engine))
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Simulator startup failed: {exc}", file=sys.stderr)
        return 1
    print(f"C-991ES simulator: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
