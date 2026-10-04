#!/usr/bin/env python3
"""Test the local C simulator UI in fresh disposable desktop/mobile browsers.

The actual C server or compiled C WebAssembly owns arithmetic. This checks UI
requests, returned pixels, editing and state controls; it never manufactures
numerical API or engine responses.
Requires Playwright for Python and an installed Chrome/Chromium executable.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_SHA256 = "8578435bfa9f7683e887a2254db31349d2b1d85b9d329f54d2618df83ff005c7"
ENGINE_ASSETS = ("index.html", "app.js", "styles.css", "engine.js", "fx991sim.js", "fx991sim.wasm")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_pins() -> dict[str, str]:
    paths = [ROOT / "simulator/serve.py", ROOT / "simulator/build_web.py", Path(__file__).resolve(), ROOT / "csrc/CMakeLists.txt"]
    paths += list((ROOT / "simulator/web").glob("*"))
    paths += list((ROOT / "csrc").rglob("*.c")) + list((ROOT / "csrc").rglob("*.h"))
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(paths)) if p.is_file()}


class BrowserChecks:
    def __init__(self, output: Path, backend="http", expected_artifacts=None):
        self.output = output
        self.backend = backend
        self.expected_artifacts = expected_artifacts
        self.rows: list[dict] = []
        self.exchanges: list[dict] = []
        self.screenshots: list[dict] = []

    def transact(self, page, path, action, label):
        before = page.evaluate("window.__fxsim_test_responses.length")
        response = None
        if self.backend == "http":
            with page.expect_response(lambda value: urlsplit(value.url).path == path
                                      and value.request.method == "POST") as pending:
                action()
            response = pending.value
        else:
            action()
        page.wait_for_function("([n,path]) => window.__fxsim_test_responses.slice(n).some(row=>row.path===path)",
                               arg=[before, path])
        detail = page.evaluate("([n,path]) => window.__fxsim_test_responses.slice(n).find(row=>row.path===path)",
                               [before, path])
        self.require(detail["backend"] == self.backend, f"{label}: actual requested engine backend", detail["backend"])
        if response is not None:
            self.require(response.status == 200, f"{label}: actual HTTP response", response.status)
            self.require(detail["result"] == response.json() and detail["body"] == response.request.post_data_json,
                         f"{label}: facade observation equals actual HTTP exchange")
        return detail

    def require(self, condition, name, detail=None):
        self.rows.append({"name": name, "passed": bool(condition), "detail": detail})
        if not condition:
            raise AssertionError(f"{name}: {detail!r}")

    def layout(self, page, label):
        bounds = page.evaluate("""() => ({
          viewport: window.innerWidth,
          document: document.documentElement.scrollWidth,
          body: document.body.scrollWidth,
          calculator: (() => { const r=document.querySelector('.calculator').getBoundingClientRect();
            return {left:r.left,right:r.right}; })()
        })""")
        self.require(bounds["document"] <= bounds["viewport"] and bounds["body"] <= bounds["viewport"],
                     f"{label}: no horizontal overflow", bounds)
        self.require(bounds["calculator"]["left"] >= 0 and bounds["calculator"]["right"] <= bounds["viewport"],
                     f"{label}: calculator fits viewport", bounds)

    def screenshot(self, page, name):
        path = self.output / name
        page.screenshot(path=str(path), full_page=True, animations="disabled")
        self.screenshots.append({"path": str(path.relative_to(ROOT)), "sha256": digest(path),
                                 "viewport": page.viewport_size})

    def canvas(self, page, result, label):
        hex_frame = result.get("framebuffer", "")
        self.require(len(hex_frame) == 768 and result.get("width") == 96 and result.get("height") == 32,
                     f"{label}: native framebuffer schema")
        native = bytes.fromhex(hex_frame)
        observed = page.locator("#lcd").evaluate("""canvas => ({width:canvas.width,height:canvas.height,
          rgba:Array.from(canvas.getContext('2d').getImageData(0,0,96,32).data)})""")
        self.require(observed["width"] == 96 and observed["height"] == 32,
                     f"{label}: canvas dimensions")
        actual = bytes(observed["rgba"])
        packed = bytearray(384)
        for y in range(32):
            for x in range(96):
                offset = 4 * (96 * y + x)
                pixel = actual[offset:offset + 4]
                if pixel == bytes((0x30, 0x3e, 0x2b, 255)):
                    packed[12 * y + x // 8] |= 0x80 >> (x % 8)
                elif pixel != bytes((0xb8, 0xc6, 0xaa, 255)):
                    raise AssertionError(f"{label}: unexpected canvas pixel at{x},{y}: {pixel.hex()}")
        self.require(bytes(packed) == native, f"{label}: all3072 canvas pixels equal native API",
                     {"native_sha256": hashlib.sha256(native).hexdigest(),
                      "canvas_packed_sha256": hashlib.sha256(packed).hexdigest(),
                      "rgba_sha256": hashlib.sha256(actual).hexdigest()})

    def evaluate(self, page, action, label, expected_request=None):
        detail = self.transact(page, "/api/evaluate", action, label)
        result, request = detail["result"], detail["body"]
        self.require(result.get("expression") == request["expression"],
                     f"{label}: C facade retains exact submitted expression")
        if expected_request is not None:
            self.require(request == expected_request, f"{label}: authored input/settings reach C", request)
        page.wait_for_function("document.querySelector('.calculator').getAttribute('aria-busy') === 'false'")
        self.require(result.get("status") in ("ok", "error", "unsupported"), f"{label}: native status schema")
        expect(page.locator("#raw-status")).to_contain_text(result["status"])
        expect(page.locator("#raw-real")).to_have_text(result.get("real") or "—")
        expect(page.locator("#raw-imag")).to_have_text(result.get("imag") or "—")
        expect(page.locator("#raw-tokens")).to_have_text(result.get("tokens") or "—")
        self.canvas(page, result, label)
        if result["status"] == "ok":
            expect(page.locator(".result-info")).to_have_class("result-info success")
            expect(page.locator("#display-state")).to_have_text("RESULT")
        else:
            expect(page.locator(".result-info")).to_have_class("result-info error")
            self.require(bool(result.get("error")), f"{label}: native error message retained")
            expect(page.locator("#status-message")).to_contain_text(result["error"])
            if result.get("error_position_kind") == "native-token":
                self.require("At character" not in page.locator("#status-message").inner_text(),
                             f"{label}: native token index is not a source character index")
        self.exchanges.append({"label": label, "backend": detail["backend"], "request": request, "response": result})
        return result


def instrument_context(context):
    """Observe real facade responses without changing requests or calculations."""
    requests = []
    responses = []
    context.on("request", lambda request: requests.append(request.url))
    context.on("response", lambda response: responses.append(response))
    context._fxsim_test_loaded_responses = responses
    context.add_init_script("""(() => {
      window.__fxsim_test_responses=[];
      const seen=new WeakSet();
      const observe=event=>{if(!seen.has(event)){seen.add(event);
        window.__fxsim_test_responses.push(JSON.parse(JSON.stringify(event.detail)));}};
      window.addEventListener('fxsim:engine-response',observe);
      document.addEventListener('fxsim:engine-response',observe);
    })()""")
    return requests


def static_requests(checks, requests, url, label):
    if checks.backend != "wasm":
        return
    prefix = urlsplit(url).path
    checks.require(prefix not in ("", "/") and prefix.endswith("/"), f"{label}: project subpath exercised", prefix)
    api = [request for request in requests if "/api/" in urlsplit(request).path]
    checks.require(not api, f"{label}: static WebAssembly makes no API requests", api)
    for name in ("app.js", "styles.css", "engine.js", "fx991sim.js", "fx991sim.wasm"):
        paths = [urlsplit(request).path for request in requests if urlsplit(request).path.endswith("/" + name)]
        checks.require(bool(paths) and all(path.startswith(prefix) for path in paths),
                       f"{label}: project-relative asset{name}", paths)


def served_asset_pins(context, url, backend):
    """Hash actual served bytes, rather than trusting adjacent local build files."""
    names = ENGINE_ASSETS if backend == "wasm" else ENGINE_ASSETS[:4]
    result = {}
    for name in names:
        address = urljoin(url.rstrip("/") + "/", name)
        response = context.request.get(address, headers={"Cache-Control": "no-cache"})
        if response.status != 200:
            raise AssertionError(f"Served artifact{name}: HTTP{response.status}")
        body = response.body()
        result[name] = {"url": address, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    return result


def loaded_asset_pins(context, url, backend):
    """Hash bodies of responses the actual page loaded, including the WASM."""
    names = ENGINE_ASSETS if backend == "wasm" else ENGINE_ASSETS[:4]
    prefix = urlsplit(url).path.rstrip("/") + "/"
    result = {}
    for response in context._fxsim_test_loaded_responses:
        path = urlsplit(response.url).path
        name = "index.html" if path == prefix else path.rsplit("/", 1)[-1]
        if name not in names:
            continue
        body = response.body()
        result[name] = {"url": response.url, "status": response.status, "bytes": len(body),
                        "sha256": hashlib.sha256(body).hexdigest()}
    if set(result) != set(names):
        raise AssertionError(f"The actual page did not load the full selected artifact set: {set(result)}")
    return result


def artifact_bytes_match(left, right):
    return set(left) == set(right) and all(left[name]["sha256"] == right[name]["sha256"]
                                          and left[name]["bytes"] == right[name]["bytes"] for name in left)


def selected_dist_pins(dist):
    if dist is None:
        return None
    return {name: {"sha256": digest(Path(dist) / name), "bytes": (Path(dist) / name).stat().st_size}
            for name in ENGINE_ASSETS}


def collect_wasm_fixture(browser, url, fixture, output, *, dist=None):
    """Collect actual C-WASM results from authored inputs; no oracle data is read.

    This helper is importable by the independent WASM parity verifier. Each
    fixture session starts with an observed reset, followed by its exact ordered
    steps; reset_each requests an observed reset before every step.
    """
    fixture = Path(fixture).resolve()
    fixture_before = digest(fixture)
    if fixture_before != FIXTURE_SHA256:
        raise ValueError("The default authored55 fixture differs from its pinned inventory")
    recipes = json.loads(fixture.read_text())
    if sum(len(session["steps"]) for session in recipes["sessions"]) != 55:
        raise ValueError("Expected the complete authored55 input inventory")
    source_before = source_pins()
    dist_before = selected_dist_pins(dist)
    context = browser.new_context(viewport={"width": 1440, "height": 1100})
    requests = instrument_context(context)
    errors = []
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        served_before = served_asset_pins(context, url, "wasm")
        page.goto(url, wait_until="networkidle")
        rows = []
        resets = []

        def call(path, body):
            before = page.evaluate("window.__fxsim_test_responses.length")
            result = page.evaluate("""async ({path,body}) => {
              const engine = await import(new URL('./engine.js', location.href).href);
              return await engine.request(path,body);
            }""", {"path": path, "body": body})
            detail = page.evaluate("n => window.__fxsim_test_responses[n]", before)
            if detail is None or detail["backend"] != "wasm" or detail["path"] != path or detail["body"] != body or detail["result"] != result:
                raise AssertionError("Direct fixture call lacks its exact actual-WASM facade observation")
            return result

        for session in recipes["sessions"]:
            reset = call("/api/reset", {})
            if reset != {"status": "ok"}:
                raise AssertionError("Fixture session-start reset did not complete")
            resets.append({"session": session["label"], "before_step": None, "result": reset})
            for step in session["steps"]:
                if session["reset_each"]:
                    reset = call("/api/reset", {})
                    if reset != {"status": "ok"}:
                        raise AssertionError("Fixture per-step reset did not complete")
                    resets.append({"session": session["label"], "before_step": step["label"], "result": reset})
                body = {"expression": step["text"], **{name: step[name] for name in ("mode", "angle", "math")}}
                rows.append({"index": len(rows), "session": session["label"], "input": step,
                             "request": body, "actual": call("/api/evaluate", body)})
        served_after = served_asset_pins(context, url, "wasm")
        loaded = loaded_asset_pins(context, url, "wasm")
        api_requests = [request for request in requests if "/api/" in urlsplit(request).path]
        source_after = source_pins()
        fixture_after = digest(fixture)
        dist_after = selected_dist_pins(dist)
        passed = len(rows) == 55 and not api_requests and not errors and served_before == served_after and artifact_bytes_match(loaded, served_before) and source_before == source_after and fixture_before == fixture_after and dist_before == dist_after and (dist_before is None or artifact_bytes_match(loaded, dist_before))
        report = {
            "schema": 1, "completed_utc": datetime.now(timezone.utc).isoformat(), "url": url,
            "scope": "Actual served C-WASM facade execution of the exact55 authored input recipes; no saved native/expected output data is read or fed into execution.",
            "fixture": str(fixture.relative_to(ROOT)), "fixture_sha256_pre": fixture_before,
            "fixture_sha256_post": fixture_after, "source_sha256_pre": source_before,
            "source_sha256_post": source_after, "served_artifacts_pre": served_before,
            "served_artifacts_post": served_after, "loaded_response_artifacts": loaded,
            "selected_dist": str(Path(dist).resolve()) if dist else None,
            "selected_dist_artifacts_pre": dist_before, "selected_dist_artifacts_post": dist_after,
            "resets": resets, "rows": rows,
            "api_requests": api_requests, "browser_errors": errors, "pass": passed,
        }
        output = Path(output)
        output.write_text(json.dumps(report, indent=2) + "\n")
        if not passed:
            raise AssertionError("WASM fixture collection failed currentness, reset or no-API guards")
        return report
    finally:
        context.close()


def exercise_desktop(browser, url, checks):
    context = browser.new_context(viewport={"width": 1440, "height": 1100}, device_scale_factor=1)
    requests = instrument_context(context)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        served_before = served_asset_pins(context, url, checks.backend)
        page.goto(url, wait_until="networkidle")
        expect(page.locator("#status-title")).to_have_text("Ready to calculate")
        checks.layout(page, "desktop1440")
        cases = [
            ("surds", "(sqrt(998)-sqrt(997))/99", 0),
            ("sine", "sin(30)", 0),
            ("arcsine", "asin(0.5)", 1),
        ]
        for name, expression, angle in cases:
            result = checks.evaluate(page, lambda name=name: page.locator(f'[data-example="{name}"]').click(),
                                     f"desktop example{name}", {"expression": expression, "mode": 0, "angle": angle, "math": 1})
            checks.require(result["status"] == "ok", f"desktop example{name}: C success")
            if name == "surds":
                checks.require(result["real"] == "89970199099801990106", "requested two-surd exact record")
                checks.screenshot(page, "desktop-two-surds.png")
            if name == "arcsine":
                checks.require(result["tokens"].endswith("82"), "radian arcsine: native pi display token")
                checks.screenshot(page, "desktop-pi-sixth.png")
        expect(page.locator("#history li")).to_have_count(3)
        page.locator(".history-entry").last.click()
        expect(page.locator("#expression")).to_have_value("(sqrt(998)-sqrt(997))/99")
        expect(page.locator("#angle")).to_have_value("0")
        expect(page.locator("#status-title")).to_have_text("Expression recalled")
        page.locator('[data-action="clear"]').click()
        expect(page.locator("#expression")).to_have_value("")
        for text in ("2", "+", "3"):
            page.locator(f'.keypad [data-insert="{text}"]').click()
        expect(page.locator("#expression")).to_have_value("2+3")
        page.locator('[data-action="delete"]').click()
        expect(page.locator("#expression")).to_have_value("2+")
        page.locator('.keypad [data-insert="3"]').click()
        result = checks.evaluate(page, lambda: page.locator('[data-action="evaluate"]').click(), "desktop keypad",
                                 {"expression": "2+3", "mode": 0, "angle": 0, "math": 1})
        checks.require(result["status"] == "ok", "keypad calculation C success")
        page.locator("#expression").fill("")
        page.locator('.function-row [data-insert="sin()"] ').click()
        page.locator("#expression").press("3")
        page.locator("#expression").press("0")
        expect(page.locator("#expression")).to_have_value("sin(30)")
        checks.evaluate(page, lambda: page.locator("#expression").press("Enter"), "desktop scientific insertion",
                        {"expression": "sin(30)", "mode": 0, "angle": 0, "math": 1})
        page.locator("#math").uncheck()
        checks.evaluate(page, lambda: page.locator("#expression").press("Enter"), "desktop linear display",
                        {"expression": "sin(30)", "mode": 0, "angle": 0, "math": 0})
        expect(page.locator("#screen-math")).to_have_text("LINEAR")
        page.locator("#math").check()
        for mode, expression in ((1, "1+2i"), (2, "101+1"), (3, "7+1"), (4, "10+1"), (5, "A+5")):
            page.locator("#mode").select_option(str(mode))
            page.locator("#expression").fill(expression)
            result = checks.evaluate(page, lambda: page.locator("#expression").press("Enter"), f"desktop mode{mode}",
                                     {"expression": expression, "mode": mode, "angle": 0, "math": 1})
            checks.require(result["status"] == "ok", f"desktop mode{mode}: C success")
        page.locator("#mode").select_option("0")
        page.locator("#angle").select_option("2")
        page.locator("#expression").fill("sin(100)")
        checks.evaluate(page, lambda: page.locator("#expression").press("Enter"), "desktop gradian setting",
                        {"expression": "sin(100)", "mode": 0, "angle": 2, "math": 1})
        page.locator("#angle").select_option("0")
        for expression in ("1/0", "1+", "unknown(1)", "  unknown(1)"):
            page.locator("#expression").fill(expression)
            result = checks.evaluate(page, lambda: page.locator("#expression").press("Enter"), f"desktop error{expression}",
                                     {"expression": expression, "mode": 0, "angle": 0, "math": 1})
            checks.require(result["status"] != "ok", f"error{expression}: no fabricated success")
            if result.get("error_position_kind") == "ascii-byte":
                expect(page.locator("#status-message")).to_contain_text(f"At character {result['error_position'] + 1}")
        page.locator("#expression").fill("   sin(30)")
        checks.evaluate(page, lambda: page.locator("#expression").press("Enter"), "desktop leading whitespace retained",
                        {"expression": "   sin(30)", "mode": 0, "angle": 0, "math": 1})
        reset = checks.transact(page, "/api/reset", lambda: page.locator("#reset").click(), "desktop reset")
        checks.require(reset["result"] == {"status": "ok"}, "reset reaches actual C engine")
        expect(page.locator("#status-title")).to_have_text("Calculator reset")
        expect(page.locator("#history li")).to_have_count(0)
        expect(page.locator("#expression")).to_have_value("")
        page.locator("#expression").fill("Ans")
        result = checks.evaluate(page, lambda: page.locator("#expression").press("Enter"), "desktop post-reset Ans")
        checks.require(result["plain"] == "0", "browser reset actually clears native Ans")
        page.locator("#clear-history").click()
        expect(page.locator("#history li")).to_have_count(0)
        expect(page.locator("#history-empty")).to_be_visible()
        page.locator("#expression").press("Escape")
        expect(page.locator("#expression")).to_have_value("")
        checks.require(not errors, "desktop: no uncaught browser errors", errors)
        static_requests(checks, requests, url, "desktop")
        checks.require(served_before == served_asset_pins(context, url, checks.backend),
                       "desktop: actual served artifacts unchanged pre/post", served_before)
        loaded = loaded_asset_pins(context, url, checks.backend)
        checks.require(artifact_bytes_match(loaded, served_before),
                       "desktop: actual loaded page/engine bytes equal witnessed served artifacts", loaded)
        if checks.expected_artifacts is not None:
            checks.require(artifact_bytes_match(loaded, checks.expected_artifacts),
                           "desktop: actual loaded bytes match selected build provenance")
    finally:
        context.close()


def exercise_mobile(browser, url, checks):
    context = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1,
                                  is_mobile=True, has_touch=True)
    requests = instrument_context(context)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        served_before = served_asset_pins(context, url, checks.backend)
        page.goto(url, wait_until="networkidle")
        checks.layout(page, "mobile390")
        checks.require(page.locator('.intro h2').inner_text() == 'See the math take shape.',
                       'mobile: hidden line break retains word spacing')
        checks.evaluate(page, lambda: page.locator('[data-example="surds"]').click(), "mobile two-surds",
                        {"expression": "(sqrt(998)-sqrt(997))/99", "mode": 0, "angle": 0, "math": 1})
        checks.screenshot(page, "mobile-two-surds.png")
        checks.evaluate(page, lambda: page.locator('[data-example="sine"]').click(), "mobile sine",
                        {"expression": "sin(30)", "mode": 0, "angle": 0, "math": 1})
        checks.screenshot(page, "mobile-sine-half.png")
        page.set_viewport_size({"width": 320, "height": 700})
        checks.layout(page, "mobile320")
        page.locator('[data-action="clear"]').click()
        page.locator('.keypad [data-insert="9"]').click()
        checks.evaluate(page, lambda: page.locator('[data-action="evaluate"]').click(), "mobile keypad9",
                        {"expression": "9", "mode": 0, "angle": 0, "math": 1})
        checks.screenshot(page, "mobile320-keypad.png")
        checks.require(not errors, "mobile: no uncaught browser errors", errors)
        static_requests(checks, requests, url, "mobile")
        checks.require(served_before == served_asset_pins(context, url, checks.backend),
                       "mobile: actual served artifacts unchanged pre/post", served_before)
        loaded = loaded_asset_pins(context, url, checks.backend)
        checks.require(artifact_bytes_match(loaded, served_before),
                       "mobile: actual loaded page/engine bytes equal witnessed served artifacts", loaded)
        if checks.expected_artifacts is not None:
            checks.require(artifact_bytes_match(loaded, checks.expected_artifacts),
                           "mobile: actual loaded bytes match selected build provenance")
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9910")
    parser.add_argument("--chrome", type=Path, default=Path("/usr/bin/google-chrome"))
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--backend", choices=("http", "wasm"), default="http")
    parser.add_argument("--collect-fixture", type=Path,
                        help="Collect the pinned authored55 fixture using actual served WebAssembly")
    parser.add_argument("--build-report", type=Path,
                        help="Optional current WASM build provenance report to bind by hash")
    parser.add_argument("--static-dist", type=Path,
                        help="Bind actually loaded WASM55 artifacts to this selected build directory")
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    local = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
    public = args.backend == "wasm" and parsed.scheme == "https" and parsed.netloc == "al-255.github.io" and parsed.path == "/casio-explore/"
    if (not local and not public) or parsed.username or parsed.password:
        parser.error("Use the local simulator or the explicitly authorized Casio Explore Pages URL")
    if args.collect_fixture and args.backend != "wasm":
        parser.error("Fixture collection requires the WebAssembly backend")
    output = args.output_dir or ROOT / "analysis/build/simulator-browser" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    pins = source_pins()
    expected_artifacts = None
    if args.build_report:
        if args.backend != "wasm":
            parser.error("A static build provenance report requires the WebAssembly backend")
        built = json.loads(args.build_report.read_text())
        expected_artifacts = {name: built["artifacts"][name] for name in ENGINE_ASSETS}
    checks = BrowserChecks(output, args.backend, expected_artifacts)
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "url": args.url,
              "backend": args.backend, "source_sha256_pre": pins,
              "build_report_sha256_pre": digest(args.build_report) if args.build_report else None,
              "scope": "Fresh disposable browser contexts against actual native C or compiled C-WASM. No existing user profile, mocked arithmetic, manufactured engine result or firmware corpus rerun."}
    failure = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(args.chrome), headless=True,
                                                  args=["--disable-dev-shm-usage"])
            report["browser_version"] = browser.version
            try:
                exercise_desktop(browser, args.url, checks)
                exercise_mobile(browser, args.url, checks)
                if args.collect_fixture:
                    collection = collect_wasm_fixture(browser, args.url, args.collect_fixture, output / "wasm55-collected.json", dist=args.static_dist)
                    report["fixture_collection"] = {"path": str((output / "wasm55-collected.json").relative_to(ROOT)),
                                                    "sha256": digest(output / "wasm55-collected.json"), "rows": len(collection["rows"])}
            finally:
                browser.close()
    except Exception as error:
        failure = f"{type(error).__name__}: {error}"
    after = source_pins()
    build_after = digest(args.build_report) if args.build_report else None
    build_drift = build_after != report["build_report_sha256_pre"]
    report.update({"completed_utc": datetime.now(timezone.utc).isoformat(), "checks": checks.rows,
                   "exchanges": checks.exchanges, "screenshots": checks.screenshots,
                   "source_sha256_post": after, "source_drift": pins != after,
                   "build_report_sha256_post": build_after, "build_report_drift": build_drift,
                   "failure": failure, "pass": failure is None and pins == after and not build_drift and all(row["passed"] for row in checks.rows)})
    (output / "browser-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(output), "checks": len(checks.rows), "api_exchanges": len(checks.exchanges),
                      "screenshots": len(checks.screenshots), "pass": report["pass"], "failure": failure}, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
