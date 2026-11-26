// Runs the OpenCASCADE kernel off the main thread so the page stays responsive.
import { OcctKernel } from './vendor/occt/index.js';
import { Model } from './cad-doc.js';

// The kernel binary ships in two pieces (each under the artifact file-size limit) and is joined here.
const WASM_PARTS = ['./vendor/occt/kernel-0.wasm', './vendor/occt/kernel-1.wasm'].map((p) => new URL(p, import.meta.url));
const WASM_BYTES = 21413105;
let kernel = null;
let model = null;
let shown = new Set();   // keys of the part meshes the page currently holds

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
  model = new Model(kernel);
  postMessage({ type: 'ready', ms: Math.round(performance.now() - t0), bytes: bytes.length });
})().catch((e) => {
  postMessage({ type: 'fatal', message: String(e && e.message ? e.message : e) });
  throw e;
});

// Every request is one command against the document. The answer is the whole
// document state: the step list to save, and the parts to draw. Parts the page
// already holds (same key) travel without their mesh.
onmessage = async (ev) => {
  const { id, cmd } = ev.data;
  try {
    await booting;
    const t0 = performance.now();
    if (cmd.type === 'open' || cmd.type === 'load') postMessage({ type: 'progress', id, stage: 'reading' });
    model.exec(cmd, (n) => postMessage({ type: 'progress', id, stage: 'meshing', parts: n }));
    const parts = model.parts(shown);
    shown = new Set(parts.map((p) => p.key));
    const transfer = [];
    for (const p of parts) if (p.positions) transfer.push(p.positions.buffer, p.normals.buffer, p.indices.buffer);
    postMessage({ type: 'result', id, kind: cmd.type, parts, ...model.summary(), ms: Math.round(performance.now() - t0) }, transfer);
  } catch (e) {
    postMessage({ type: 'error', id, kind: cmd.type, message: String(e && e.message ? e.message : e) });
  }
};
