// Runs the document model against the real kernel in Node.
// Usage: npm test            (sample plate, history, STEP round trip)
//        npm test -- part.step   (also loads a STEP file)
import fs from 'node:fs';
import assert from 'node:assert/strict';
import { OcctKernel } from 'occt-wasm';
import { compose } from '../src/cad-core.js';
import { Model } from '../src/cad-doc.js';

const kernel = await OcctKernel.init();
const model = new Model(kernel);
const near = (a, b, what) => assert.ok(Math.abs(a - b) < 1e-6 * Math.abs(b), `${what}: ${a} != ${b}`);
const plateVolume = (p) => (p.length * p.width - (4 - Math.PI) * p.corner ** 2 - Math.PI * (p.hole / 2) ** 2) * p.thickness;

// The sample plate is three steps and one part.
model.exec({ type: 'sample' });
let [plate] = model.parts();
assert.equal(model.features.length, 3);
near(plate.volume, plateVolume({ length: 40, width: 24, thickness: 6, hole: 8, corner: 4 }), 'plate volume');
assert.deepEqual(plate.size.map((v) => Math.round(v * 1000) / 1000), [40, 24, 6]);
assert.ok(plate.triangles > 0 && plate.positions.length > 0);
assert.ok(kernel.isValid(model.shapeOf(plate.id)), 'the kernel shape is kept after meshing');
console.log(`plate ok: volume ${plate.volume.toFixed(3)} mm3, ${plate.triangles} triangles`);

// A part the viewer already holds is sent without its mesh.
assert.equal(model.parts(new Set([plate.key]))[0].positions, undefined);

// Editing a step recomputes; undo and redo return to the exact earlier results.
const [box, , hole] = model.features;
const key0 = plate.key;
model.exec({ type: 'update', id: box.id, params: { length: 60 }, merge: 'drag1' });
model.exec({ type: 'update', id: box.id, params: { length: 50 }, merge: 'drag1' });
near(model.parts()[0].volume, plateVolume({ length: 50, width: 24, thickness: 6, hole: 8, corner: 4 }), 'edited volume');
model.exec({ type: 'undo' });
assert.equal(model.parts()[0].key, key0, 'one undo steps back over a whole drag');
model.exec({ type: 'redo' });
assert.equal(model.features[0].params.length, 50);
model.exec({ type: 'undo' });

// Rolling back shows an earlier state without losing the later steps.
model.exec({ type: 'roll', cursor: 1 });
near(model.parts()[0].volume, 40 * 24 * 6, 'rolled-back volume');
model.exec({ type: 'roll', cursor: 3 });
assert.equal(model.parts()[0].key, key0);

// A step that cannot build is refused and leaves the document alone; a broken edit is reported on its step.
assert.throws(() => model.exec({ type: 'add', op: 'hole', params: { body: 'nope' } }), /Select a part/);
assert.equal(model.features.length, 3);
model.exec({ type: 'remove', id: box.id });
assert.match(model.errors.get(hole.id), /no longer exists/);
assert.equal(model.parts().length, 0);
model.exec({ type: 'undo' });
assert.equal(model.parts()[0].key, key0);

// The saved form rebuilds the same part in a fresh model, and the kernel does not leak handles.
const saved = JSON.parse(JSON.stringify(model.toJSON()));
const again = new Model(kernel);
again.exec({ type: 'load', doc: saved });
near(again.parts()[0].volume, plate.volume, 'reloaded volume');
const count = kernel.shapeCount;
for (let i = 0; i < 60; i++) model.exec({ type: 'update', id: box.id, params: { length: 30 + i }, merge: 'drag2' });
assert.ok(kernel.shapeCount <= count + 30, `kernel handles grew from ${count} to ${kernel.shapeCount}`);
console.log(`history ok: ${model.features.length} steps, undo/redo, rollback, reload; ${kernel.shapeCount} shapes held`);

// STEP: export the plate, open it as a new document, then drill the imported part.
const step = kernel.exportStep(model.shapeOf(plate.id));
const m2 = new Model(kernel);
m2.exec({ type: 'open', blob: 'b1', text: step, name: 'plate.step' });
const [imported] = m2.parts();
assert.ok(imported.approx && Math.abs(imported.volume - model.parts()[0].volume) < 0.01 * imported.volume);
m2.exec({ type: 'add', op: 'hole', params: { body: imported.id, diameter: 4, x: 12, y: 0 } });
assert.ok(m2.parts()[0].volume < imported.volume, 'an imported part can be edited');
const m3 = new Model(kernel);
m3.exec({ type: 'load', doc: m2.toJSON(), blobs: { b1: step } });
assert.equal(m3.parts()[0].triangles, m2.parts()[0].triangles);
assert.throws(() => new Model(kernel).exec({ type: 'open', blob: 'b2', text: 'not a step file', name: 'x.step' }));
console.log('step ok: export, import, edit, reload');

const shift = [1, 0, 0, 5, 0, 1, 0, 6, 0, 0, 1, 7];
assert.deepEqual(compose(shift, shift), [1, 0, 0, 10, 0, 1, 0, 12, 0, 0, 1, 14]);
console.log('matrix compose ok');

const file = process.argv[2];
if (file) {
  const t0 = performance.now();
  const m = new Model(kernel);
  m.exec({ type: 'open', blob: 'file', text: fs.readFileSync(file, 'utf8'), name: file });
  const parts = m.parts();
  const tris = parts.reduce((a, b) => a + b.triangles, 0);
  console.log(`${file}: ${parts.length} parts, ${tris} triangles, ${((performance.now() - t0) / 1000).toFixed(1)} s`);
}
