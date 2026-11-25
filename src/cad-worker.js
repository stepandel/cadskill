// Runs the OpenCASCADE kernel off the main thread so the page stays responsive.
import { OcctKernel } from './vendor/occt/index.js';
import { loadStep, buildPlate } from './cad-core.js';

// The kernel binary ships in two pieces (each under the artifact file-size limit) and is joined here.
const WASM_PARTS = ['./vendor/occt/kernel-0.wasm', './vendor/occt/kernel-1.wasm'].map((p) => new URL(p, import.meta.url));
const WASM_BYTES = 21413105;
let kernel = null;

async function fetchKernel() {
  const bytes = new Uint8Array(WASM_BYTES);
  let loaded = 0;
  for (const url of WASM_PARTS) {
    const res = await fetch(url);
    if (!res.ok) throw new Error('The geometry kernel file did not load (HTTP ' + res.status + ').');
    if (!res.body) {
      const buf = new Uint8Array(await res.arrayBuffer());
      bytes.set(buf, loaded); loaded += buf.length;
      postMessage({ type: 'boot', loaded, total: WASM_BYTES });
      continue;
    }
    const reader = res.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (loaded + value.length > WASM_BYTES) throw new Error('The geometry kernel file is larger than expected.');
      bytes.set(value, loaded); loaded += value.length;
      postMessage({ type: 'boot', loaded, total: WASM_BYTES });
    }
  }
  if (loaded !== WASM_BYTES) throw new Error('The geometry kernel file is incomplete (' + loaded + ' of ' + WASM_BYTES + ' bytes).');
  return bytes;
}

const booting = (async () => {
  const t0 = performance.now();
  const bytes = await fetchKernel();
  kernel = await OcctKernel.init({ wasm: bytes });
  postMessage({ type: 'ready', ms: Math.round(performance.now() - t0), bytes: bytes.length });
})().catch((e) => {
  postMessage({ type: 'fatal', message: String(e && e.message ? e.message : e) });
  throw e;
});

function send(id, kind, parts, t0) {
  const transfer = [];
  for (const p of parts) transfer.push(p.positions.buffer, p.normals.buffer, p.indices.buffer);
  postMessage({ type: 'result', id, kind, parts, ms: Math.round(performance.now() - t0) }, transfer);
}

onmessage = async (ev) => {
  const msg = ev.data;
  try {
    await booting;
    const t0 = performance.now();
    if (msg.type === 'plate') {
      send(msg.id, 'plate', [buildPlate(kernel, msg.params)], t0);
    } else if (msg.type === 'step') {
      postMessage({ type: 'progress', id: msg.id, stage: 'reading' });
      const parts = loadStep(kernel, msg.text, 0.05, (n) => postMessage({ type: 'progress', id: msg.id, stage: 'meshing', parts: n }));
      if (parts.length === 0) throw new Error('This file has no solid or surface geometry the kernel could mesh.');
      send(msg.id, 'step', parts, t0);
    }
  } catch (e) {
    postMessage({ type: 'error', id: msg.id, message: String(e && e.message ? e.message : e) });
  }
};
