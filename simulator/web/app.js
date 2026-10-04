'use strict';

import { request } from './engine.js';

(() => {
  const $ = (id) => document.getElementById(id);
  const input = $('expression');
  const canvas = $('lcd');
  const context = canvas.getContext('2d');
  const mode = $('mode');
  const angle = $('angle');
  const math = $('math');
  const history = [];
  let busy = false;
  let lastNative = null;

  const settings = () => ({ mode: Number(mode.value), angle: Number(angle.value), math: math.checked ? 1 : 0 });
  const selectedLabel = (select) => select.options[select.selectedIndex].text;
  const examples = {
    surds: { expression: '(sqrt(998)-sqrt(997))/99', mode: 0, angle: 0, math: 1 },
    sine: { expression: 'sin(30)', mode: 0, angle: 0, math: 1 },
    arcsine: { expression: 'asin(0.5)', mode: 0, angle: 1, math: 1 },
  };

  function showStatus(kind, title, message) {
    document.querySelector('.result-info').className = `result-info ${kind}`;
    $('status-title').textContent = title;
    $('status-message').textContent = message;
  }

  function drawBlank() {
    context.fillStyle = '#b8c6aa';
    context.fillRect(0, 0, 96, 32);
    canvas.setAttribute('aria-label', 'Native calculator LCD, ready for an expression');
  }

  function drawFramebuffer(hex) {
    if (typeof hex !== 'string' || !/^[0-9a-f]{768}$/i.test(hex)) {
      throw new Error('The engine returned an invalid 96 × 32 framebuffer.');
    }
    const frame = Uint8Array.from(hex.match(/../g), (byte) => parseInt(byte, 16));
    drawBlank();
    context.fillStyle = '#303e2b';
    for (let y = 0; y < 32; y += 1) {
      for (let x = 0; x < 96; x += 1) {
        if (frame[y * 12 + (x >> 3)] & (0x80 >> (x & 7))) context.fillRect(x, y, 1, 1);
      }
    }
  }

  function refreshSettings() {
    $('screen-mode').textContent = selectedLabel(mode);
    $('screen-angle').textContent = selectedLabel(angle);
    $('screen-math').textContent = math.checked ? 'MATH' : 'LINEAR';
    $('base-help').hidden = mode.value !== '5';
  }

  function setBusy(value) {
    busy = value;
    document.querySelectorAll('button, select, #math').forEach((control) => { control.disabled = value; });
    input.readOnly = value;
    document.querySelector('.calculator').setAttribute('aria-busy', String(value));
  }

  function inspectResult(result) {
    $('raw-status').textContent = `${result.status}${Number.isInteger(result.native_status) ? ` · native ${result.native_status}` : ''}`;
    $('raw-real').textContent = result.real || '—';
    $('raw-imag').textContent = result.imag || '—';
    $('raw-tokens').textContent = result.tokens || '—';
  }

  function sourceLocation(byteOffset) {
    if (!Number.isInteger(byteOffset) || byteOffset < 0) return null;
    const encoder = new TextEncoder();
    let bytes = 0;
    let index = 0;
    let position = 1;
    for (const character of input.value) {
      if (bytes === byteOffset) return { start: index, end: index + character.length, position };
      bytes += encoder.encode(character).length;
      index += character.length;
      position += 1;
    }
    return bytes === byteOffset ? { start: index, end: index, position } : null;
  }

  function renderHistory() {
    $('history').replaceChildren();
    $('history-empty').hidden = history.length > 0;
    history.forEach((entry) => {
      const item = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `history-entry${entry.status === 'ok' ? '' : ' is-error'}`;
      button.title = `Recall ${entry.expression}`;
      const expression = document.createElement('code');
      expression.textContent = entry.expression;
      const label = document.createElement('small');
      label.textContent = entry.status === 'ok' ? entry.label : entry.status.toUpperCase();
      button.append(expression, label);
      button.addEventListener('click', () => {
        input.value = entry.expression;
        mode.value = String(entry.mode);
        angle.value = String(entry.angle);
        math.checked = entry.math === 1;
        refreshSettings();
        input.focus();
        input.setSelectionRange(input.value.length, input.value.length);
        showStatus('', 'Expression recalled', 'Press Enter or = to evaluate with these settings.');
      });
      item.append(button);
      $('history').append(item);
    });
  }

  async function evaluate() {
    if (busy) return;
    const expression = input.value;
    if (!expression.trim()) {
      showStatus('', 'Enter an expression', 'Choose an example or use the keypad to begin.');
      input.focus();
      return;
    }
    const calculation = { expression, ...settings() };
    setBusy(true);
    showStatus('busy', 'Evaluating in C', 'Waiting for the native engine…');
    $('display-state').textContent = 'WORKING';
    try {
      const result = await request('/api/evaluate', calculation);
      if (!['ok', 'error', 'unsupported'].includes(result.status)) throw new Error('The engine returned an unknown result status.');
      if ((result.width !== undefined && result.width !== 96) || (result.height !== undefined && result.height !== 32)) throw new Error('The engine returned unexpected LCD dimensions.');
      if (result.status === 'ok' && !result.framebuffer) throw new Error('The engine did not return its result framebuffer.');
      lastNative = result;
      inspectResult(result);
      if (result.framebuffer) drawFramebuffer(result.framebuffer);
      const label = `${selectedLabel(mode)} · ${selectedLabel(angle)}`;
      history.unshift({ ...calculation, status: result.status, label });
      if (history.length > 20) history.pop();
      renderHistory();
      $('display-state').textContent = result.status === 'ok' ? 'RESULT' : result.status.toUpperCase();
      $('display-caption').textContent = label;
      if (result.status === 'ok') {
        showStatus('success', 'Native result', result.plain || 'The LCD shows the C engine’s result. Exact display follows the selected mode.');
        canvas.setAttribute('aria-label', result.plain ? `Native calculator result: ${result.plain}` : `Native calculator result for ${expression}; inspect result records below.`);
      } else {
        const source = result.error_position_kind === 'ascii-byte' ? sourceLocation(result.error_position) : null;
        const location = source ? ` At character ${source.position}.` : '';
        const message = result.error || (result.status === 'unsupported' ? 'This expression is outside the implemented engine scope.' : `Native calculation failed${Number.isInteger(result.native_status) ? ` with status ${result.native_status}` : ''}.`);
        showStatus('error', result.status === 'unsupported' ? 'Not supported by the engine' : 'Expression error', message + location);
        canvas.setAttribute('aria-label', `Native engine ${result.status}: ${message}`);
        if (source) input.setSelectionRange(source.start, source.end);
      }
    } catch (error) {
      $('display-state').textContent = 'ERROR';
      $('display-caption').textContent = lastNative ? 'Previous native result' : 'No native result';
      showStatus('error', 'Could not evaluate', error.message || 'The native engine could not be reached.');
    } finally {
      setBusy(false);
      input.focus();
    }
  }

  function insert(text, caretOffset = 0) {
    if (busy) return;
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? start;
    input.setRangeText(text, start, end, 'end');
    const caret = start + text.length + caretOffset;
    input.setSelectionRange(caret, caret);
    input.focus();
  }

  function clearExpression() {
    if (busy) return;
    input.value = '';
    drawBlank();
    $('display-state').textContent = 'READY';
    $('display-caption').textContent = 'Native result pixels';
    showStatus('', 'Expression cleared', 'Calculator memory is retained. Reset clears the native state.');
    input.focus();
  }

  document.querySelectorAll('[data-insert]').forEach((button) => {
    button.addEventListener('click', () => insert(button.dataset.insert, Number(button.dataset.caret || 0)));
  });
  document.querySelectorAll('[data-action]').forEach((button) => {
    button.addEventListener('click', () => {
      if (button.dataset.action === 'evaluate') evaluate();
      if (button.dataset.action === 'clear') clearExpression();
      if (button.dataset.action === 'delete') {
        let start = input.selectionStart ?? input.value.length;
        const end = input.selectionEnd ?? start;
        if (start === end && start > 0) start -= 1;
        input.setRangeText('', start, end, 'end');
        input.focus();
      }
    });
  });
  document.querySelectorAll('[data-example]').forEach((button) => {
    button.addEventListener('click', () => {
      const example = examples[button.dataset.example];
      input.value = example.expression;
      mode.value = String(example.mode);
      angle.value = String(example.angle);
      math.checked = example.math === 1;
      refreshSettings();
      evaluate();
    });
  });
  $('expression-form').addEventListener('submit', (event) => { event.preventDefault(); evaluate(); });
  [mode, angle, math].forEach((control) => control.addEventListener('change', () => {
    refreshSettings();
    if (lastNative) showStatus('', 'Settings changed', 'Evaluate again to update the displayed result.');
  }));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !busy) { event.preventDefault(); clearExpression(); }
  });
  $('clear-history').addEventListener('click', () => { history.length = 0; renderHistory(); });
  $('reset').addEventListener('click', async () => {
    if (busy) return;
    setBusy(true);
    showStatus('busy', 'Resetting calculator', 'Clearing native calculator state…');
    try {
      const result = await request('/api/reset', {});
      if (result.status !== 'ok') throw new Error(result.error || 'The native state could not be reset.');
      lastNative = null;
      history.length = 0;
      renderHistory();
      mode.value = '0'; angle.value = '0'; math.checked = true;
      refreshSettings();
      input.value = '';
      drawBlank();
      $('display-state').textContent = 'READY';
      $('display-caption').textContent = 'Native result pixels';
      ['raw-status', 'raw-real', 'raw-imag', 'raw-tokens'].forEach((id) => { $(id).textContent = '—'; });
      showStatus('success', 'Calculator reset', 'Native memory and session history have been cleared.');
    } catch (error) { showStatus('error', 'Reset failed', error.message); }
    finally { setBusy(false); input.focus(); }
  });
  refreshSettings();
  drawBlank();
  renderHistory();
})();
