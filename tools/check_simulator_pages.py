#!/usr/bin/env python3
"""Read-only HTTP checks for the static C/WASM simulator deployment.

This checks delivery, MIME types, relative asset references and optional exact
build artifacts. It does not execute calculator code or prove browser parity.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


RESOURCES = {
    "index.html": {"text/html"},
    "app.js": {"application/javascript", "text/javascript"},
    "engine.js": {"application/javascript", "text/javascript"},
    "styles.css": {"text/css"},
    "fx991sim.js": {"application/javascript", "text/javascript"},
    "fx991sim.wasm": {"application/wasm"},
}
MAX_BYTES = 16 * 1024 * 1024


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.wasm_markers = 0
        self.modules = []
        self.styles = []
        self.has_base = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("name") == "fxsim-backend" and attrs.get("content") == "wasm":
            self.wasm_markers += 1
        if tag == "script" and attrs.get("type") == "module":
            self.modules.append(attrs.get("src"))
        if tag == "link" and "stylesheet" in attrs.get("rel", "").split():
            self.styles.append(attrs.get("href"))
        if tag == "base":
            self.has_base = True


def check(url, timeout, expected=None):
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError("URL must be an HTTP(S) site root without query or fragment")
    if not parsed.path.endswith("/"):
        raise ValueError("Site URL must end in / to preserve the deployment base path")
    if parsed.username or parsed.password:
        raise ValueError("Credentials in site URLs are not supported")
    observations = {}
    bodies = {}
    failures = []
    for name, allowed_mimes in RESOURCES.items():
        target = url if name == "index.html" else urljoin(url, name)
        try:
            request = Request(target, headers={"User-Agent": "casio-explore-deployment-smoke/1", "Cache-Control": "no-cache"})
            with urlopen(request, timeout=timeout) as response:
                payload = response.read(MAX_BYTES + 1)
                observed = {"url": target, "final_url": response.url, "status": response.status,
                            "content_type": response.headers.get_content_type(),
                            "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
            observations[name] = observed
            if observed["status"] != 200:
                failures.append(f"{name}: expected HTTP 200")
            if not payload or len(payload) > MAX_BYTES:
                failures.append(f"{name}: empty or oversized response")
            if observed["content_type"] not in allowed_mimes:
                failures.append(f"{name}: unexpected MIME {observed['content_type']}")
            if observed["final_url"] != target:
                failures.append(f"{name}: unexpected redirect to {observed['final_url']}")
            if expected is not None:
                artifact = expected.get(name)
                if not isinstance(artifact, dict) or artifact.get("sha256") != observed["sha256"] or artifact.get("bytes") != observed["bytes"]:
                    failures.append(f"{name}: does not match the supplied build report")
            bodies[name] = payload
        except (HTTPError, URLError, OSError, ValueError) as error:
            failures.append(f"{name}: {error}")
    if "index.html" in bodies:
        try:
            page = Page()
            page.feed(bodies["index.html"].decode("utf-8"))
            if page.wasm_markers != 1 or page.has_base:
                failures.append("index.html: expected one WASM backend marker and no base override")
            if page.modules != ["./app.js"] or page.styles != ["./styles.css"]:
                failures.append("index.html: expected project-relative module and stylesheet")
        except UnicodeError as error:
            failures.append(f"index.html: invalid UTF-8: {error}")
    if "fx991sim.wasm" in bodies and bodies["fx991sim.wasm"][:8] != b"\x00asm\x01\x00\x00\x00":
        failures.append("fx991sim.wasm: invalid WASM magic or version")
    return {"schema": 1, "timestamp_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "site_url": url, "status": "pass" if not failures else "fail", "resources": observations,
            "build_report_comparison": expected is not None, "failures": failures,
            "scope": "HTTP delivery only; does not establish calculator execution, browser behavior or numerical parity."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Published site root, including its trailing slash")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--build-report", type=Path, help="Optional report from the EXACT deployed build")
    parser.add_argument("--output", type=Path, help="Optional private JSON observation file")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        expected = None
        if args.build_report:
            expected = json.loads(args.build_report.read_text())["artifacts"]
            if not isinstance(expected, dict):
                raise ValueError("Build report artifacts must be an object")
        result = check(args.url, args.timeout, expected)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
