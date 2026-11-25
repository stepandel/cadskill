// Runs the geometry module against the real kernel in Node.
// Usage: npm test            (sample plate only)
//        npm test -- part.step   (also loads a STEP file)
import fs from 'node:fs';
import assert from 'node:assert/strict';
import { OcctKernel } from 'occt-wasm';
import { buildPlate, loadStep, compose } from '../src/cad-core.js';

const kernel = await OcctKernel.init();

const p = { length: 40, width: 24, thickness: 6, hole: 8, corner: 4 };
const plate = buildPlate(kernel, p);
const expected = (p.length * p.width - (4 * p.corner ** 2 - Math.PI * p.corner ** 2) - Math.PI * (p.hole / 2) ** 2) * p.thickness;
assert.ok(Math.abs(plate.volume - expected) < 1e-6 * expected, `plate volume ${plate.volume} != ${expected}`);
assert.deepEqual(plate.size.map((v) => Math.round(v * 1000) / 1000), [40, 24, 6]);
assert.ok(plate.triangles > 0);
console.log(`plate ok: volume ${plate.volume.toFixed(3)} mm3, ${plate.triangles} triangles`);

const shift = [1, 0, 0, 5, 0, 1, 0, 6, 0, 0, 1, 7];
assert.deepEqual(compose(shift, shift), [1, 0, 0, 10, 0, 1, 0, 12, 0, 0, 1, 14]);
console.log('matrix compose ok');

const file = process.argv[2];
if (file) {
  const t0 = performance.now();
  const parts = loadStep(kernel, fs.readFileSync(file, 'utf8'));
  assert.ok(parts.length > 0, 'no parts found');
  const tris = parts.reduce((a, b) => a + b.triangles, 0);
  console.log(`${file}: ${parts.length} parts, ${tris} triangles, ${((performance.now() - t0) / 1000).toFixed(1)} s`);
}
