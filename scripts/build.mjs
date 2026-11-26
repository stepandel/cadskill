// Assembles dist/: the source files plus the vendored libraries the page loads.
// The artifact host caps each file at 20 MiB, so the kernel binary is split into
// equal-sized pieces that src/cad-worker.js joins again at load time.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dist = path.join(root, 'dist');
const occt = path.join(root, 'node_modules/occt-wasm/dist');
const three = path.join(root, 'node_modules/three');

const PART_BYTES = 11_000_000;
const OCCT_SCRIPTS = ['index.js', 'types.js', 'raw-types.js', 'xcaf-document.js', 'svg.js', 'png.js', 'views.js', 'font5x7.js', 'occt-wasm.js'];
const THREE_FILES = [['build/three.module.js', 'three.module.js'], ['build/three.core.js', 'three.core.js'], ['examples/jsm/controls/OrbitControls.js', 'OrbitControls.js']];

fs.rmSync(dist, { recursive: true, force: true });
fs.mkdirSync(path.join(dist, 'vendor/occt'), { recursive: true });
fs.mkdirSync(path.join(dist, 'vendor/three'), { recursive: true });

for (const f of ['index.html', 'cad-core.js', 'cad-doc.js', 'cad-store.js', 'cad-worker.js']) fs.copyFileSync(path.join(root, 'src', f), path.join(dist, f));

// Library scripts are copied as published, minus their source-map pointers (the maps are not shipped).
for (const f of OCCT_SCRIPTS) {
  const text = fs.readFileSync(path.join(occt, f), 'utf8').replace(/^\/\/# sourceMappingURL=.*$\n?/gm, '');
  fs.writeFileSync(path.join(dist, 'vendor/occt', f), text);
}
for (const [from, to] of THREE_FILES) fs.copyFileSync(path.join(three, from), path.join(dist, 'vendor/three', to));

const wasm = fs.readFileSync(path.join(occt, 'occt-wasm.wasm'));
const parts = Math.ceil(wasm.length / PART_BYTES);
for (let i = 0; i < parts; i++) fs.writeFileSync(path.join(dist, 'vendor/occt', `kernel-${i}.wasm`), wasm.subarray(i * PART_BYTES, (i + 1) * PART_BYTES));

// The worker hard-codes the piece count and total size; fail loudly if a library upgrade changes them.
const worker = fs.readFileSync(path.join(dist, 'cad-worker.js'), 'utf8');
const declared = Number((worker.match(/WASM_BYTES = (\d+)/) || [])[1]);
const declaredParts = (worker.match(/kernel-\d+\.wasm/g) || []).length;
if (declared !== wasm.length || declaredParts !== parts) {
  console.error(`Kernel binary is ${wasm.length} bytes in ${parts} pieces, but src/cad-worker.js expects ${declared} bytes in ${declaredParts}. Update WASM_BYTES and WASM_PARTS there.`);
  process.exit(1);
}

let total = 0, count = 0;
const walk = (d) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, e.name); if (e.isDirectory()) walk(p); else { total += fs.statSync(p).size; count++; } } };
walk(dist);
console.log(`dist/ ready: ${count} files, ${(total / 1048576).toFixed(1)} MB (kernel ${wasm.length} bytes in ${parts} pieces)`);
