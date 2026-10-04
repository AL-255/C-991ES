/* Transport only. Arithmetic, state, formatting and pixels belong to C. */
const RESPONSE_BYTES = 32768;
let backendPromise;
let wasmPromise;

function staticSite() {
  return typeof document !== 'undefined'
    && document.querySelector('meta[name="fxsim-backend"]')?.content === 'wasm';
}

async function chooseBackend() {
  if (staticSite()) return 'wasm';
  const host = typeof location === 'undefined' ? '' : location.hostname;
  // Built static pages carry the explicit marker above. The native local
  // service keeps HTTP transport even while another evaluation occupies it.
  if (['localhost', '127.0.0.1', '[::1]'].includes(host)) return 'http';
  return 'wasm';
}

async function wasmSession() {
  if (!wasmPromise) {
    wasmPromise = (async () => {
      const moduleURL = new URL('./fx991sim.js', import.meta.url);
      const {default: createModule} = await import(moduleURL.href);
      const module = await createModule({locateFile: (name) => new URL(name, moduleURL).href});
      const pointer = module._fxsim_create();
      if (!pointer) throw new Error('Unable to create a C calculator session.');
      const session = {module, pointer};
      if (typeof window !== 'undefined') {
        window.addEventListener('pagehide', (event) => {
          if (!event.persisted && session.pointer) {
            module._fxsim_destroy(session.pointer);
            session.pointer = 0;
          }
        });
      }
      return session;
    })();
    wasmPromise.catch(() => { wasmPromise = undefined; });
  }
  return wasmPromise;
}

function evaluateInC(session, body) {
  if (!body || typeof body.expression !== 'string' || body.expression.includes('\0')) {
    throw new Error('Expression must be text without NUL characters.');
  }
  const encoded = new TextEncoder().encode(body.expression);
  if (encoded.length > 4096) throw new Error('Expression is too long.');
  const settings = [];
  for (const [name, fallback, maximum] of [['mode', 0, 5], ['angle', 0, 2], ['math', 1, 1]]) {
    const value = body[name] === undefined ? fallback : body[name];
    if (!Number.isInteger(value) || value < 0 || value > maximum) throw new Error(`Invalid ${name} setting.`);
    settings.push(value);
  }
  const {module} = session;
  if (!session.pointer) throw new Error('The calculator session has closed.');
  const input = module._malloc(encoded.length + 1);
  if (!input) throw new Error('Unable to allocate C input memory.');
  let output = 0;
  try {
    output = module._malloc(RESPONSE_BYTES);
    if (!output) throw new Error('Unable to allocate C output memory.');
    // Allocation/C execution may grow memory: use the current exported view.
    module.HEAPU8.set(encoded, input);
    module.HEAPU8[input + encoded.length] = 0;
    const status = module._fxsim_evaluate(session.pointer, input, ...settings, output, RESPONSE_BYTES);
    if (status !== 0) throw new Error('C engine rejected the request.');
    const result = JSON.parse(module.UTF8ToString(output));
    if (!result || typeof result !== 'object' || Array.isArray(result)) throw new Error('Invalid response from C engine.');
    result.expression = body.expression;
    return result;
  } finally {
    if (output) module._free(output);
    module._free(input);
  }
}

async function httpRequest(path, body) {
  const response = await fetch(path, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  let result;
  try { result = await response.json(); } catch (_) {
    throw new Error(`The server returned an unreadable response (HTTP ${response.status}).`);
  }
  if (!response.ok) throw new Error(result.error || result.message || `Server error (HTTP ${response.status}).`);
  return result;
}

export async function request(path, body) {
  if (path !== '/api/evaluate' && path !== '/api/reset') throw new Error('Unknown calculator request.');
  if (!backendPromise) backendPromise = chooseBackend();
  const backend = await backendPromise;
  let result;
  if (backend === 'http') result = await httpRequest(path, body);
  else {
    const session = await wasmSession();
    if (path === '/api/reset') {
      if (!session.pointer) throw new Error('The calculator session has closed.');
      session.module._fxsim_reset(session.pointer);
      result = {status: 'ok'};
    } else result = evaluateInC(session, body);
  }
  // Read-only diagnostics report the real response for browser verification.
  if (typeof document !== 'undefined' && typeof CustomEvent !== 'undefined') {
    document.dispatchEvent(new CustomEvent('fxsim:engine-response', {detail: {path, body, result, backend}}));
  }
  return result;
}
