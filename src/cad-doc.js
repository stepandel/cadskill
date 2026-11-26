// The document: an ordered list of modeling steps (the history) and the kernel
// shapes they produce (the parts). Shapes stay alive in the kernel between
// steps, so a later step, a measurement or an export can work on the exact
// geometry instead of a discarded mesh.
//
// The saved form is only the step list (plus the text of any imported STEP
// file, kept separately). Shapes are rebuilt from it, and every step's result
// is cached by its inputs so editing step N only recomputes N and what follows.
import { importStep, meshOut, meshStats, IDENTITY } from './cad-core.js';

export const DOC_VERSION = 1;
const CACHE_SPARE = 24;      // results kept beyond those the current history uses (makes undo instant)
const UNDO_LIMIT = 100;

// Step types. `target` steps change an existing part; the others create parts.
// `params` drives both validation defaults and the sliders in the page.
export const OPS = {
  box: {
    label: 'Box',
    params: [
      { key: 'length', label: 'Length', min: 1, max: 200, step: 0.5, value: 40 },
      { key: 'width', label: 'Width', min: 1, max: 200, step: 0.5, value: 24 },
      { key: 'height', label: 'Thickness', min: 0.5, max: 200, step: 0.5, value: 6 },
    ],
  },
  cylinder: {
    label: 'Cylinder',
    params: [
      { key: 'diameter', label: 'Diameter', min: 1, max: 200, step: 0.5, value: 20 },
      { key: 'height', label: 'Height', min: 0.5, max: 200, step: 0.5, value: 20 },
    ],
  },
  fillet: {
    label: 'Round corners',
    target: true,
    params: [{ key: 'radius', label: 'Corner radius', min: 0, max: 25, step: 0.5, value: 4 }],
  },
  hole: {
    label: 'Hole',
    target: true,
    params: [
      { key: 'diameter', label: 'Hole Ø', min: 0, max: 50, step: 0.5, value: 8 },
      { key: 'x', label: 'X', min: -100, max: 100, step: 0.5, value: 0 },
      { key: 'y', label: 'Y', min: -100, max: 100, step: 0.5, value: 0 },
    ],
  },
  move: {
    label: 'Move',
    target: true,
    params: [
      { key: 'dx', label: 'X', min: -200, max: 200, step: 0.5, value: 0 },
      { key: 'dy', label: 'Y', min: -200, max: 200, step: 0.5, value: 0 },
      { key: 'dz', label: 'Z', min: -200, max: 200, step: 0.5, value: 10 },
    ],
  },
  import: { label: 'Import', params: [] },
};

export function samplePlate() {
  return [
    { op: 'box', name: 'Mounting plate', params: { length: 40, width: 24, height: 6 } },
    { op: 'fillet', params: { radius: 4 }, targetPrev: true },
    { op: 'hole', params: { diameter: 8, x: 0, y: 0 }, targetPrev: true },
  ];
}

// cyrb53: a small, well-distributed string hash. Keys only need to be unique within one session.
function hash(str) {
  let h1 = 0xdeadbeef, h2 = 0x41c6ce57;
  for (let i = 0; i < str.length; i++) {
    const c = str.charCodeAt(i);
    h1 = Math.imul(h1 ^ c, 2654435761);
    h2 = Math.imul(h2 ^ c, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (h2 >>> 0).toString(16).padStart(8, '0') + (h1 >>> 0).toString(16).padStart(8, '0');
}

const num = (v, what) => {
  const n = Number(v);
  if (!Number.isFinite(n)) throw new Error(what + ' is not a number.');
  return n;
};

// Runs fn with a scratch list; every handle passed through t() is released afterwards.
function withTemps(kernel, fn) {
  const temps = [];
  const t = (s) => { temps.push(s); return s; };
  try { return fn(t); } finally {
    for (const s of temps) { try { kernel.release(s); } catch (e) { /* already gone */ } }
  }
}

// Each returns the new shape handle for the step. Inputs are never released here.
const BUILD = {
  box(k, p) {
    const L = num(p.length, 'Length'), W = num(p.width, 'Width'), H = num(p.height, 'Thickness');
    if (L <= 0 || W <= 0 || H <= 0) throw new Error('A box needs a positive length, width and thickness.');
    return withTemps(k, (t) => k.translate(t(k.makeBox(L, W, H)), -L / 2, -W / 2, 0));   // centred on the origin in X and Y
  },
  cylinder(k, p) {
    const d = num(p.diameter, 'Diameter'), h = num(p.height, 'Height');
    if (d <= 0 || h <= 0) throw new Error('A cylinder needs a positive diameter and height.');
    return k.makeCylinder(d / 2, h);
  },
  fillet(k, p, shape) {
    const b = k.getBoundingBox(shape);
    const r = Math.min(num(p.radius, 'Corner radius'), Math.min(b.xmax - b.xmin, b.ymax - b.ymin) / 2 - 0.05);
    if (r <= 0.05) return k.located(shape, IDENTITY);
    return withTemps(k, (t) => {
      const vertical = k.getSubShapes(shape, 'edge').map(t).filter((e) => {
        const eb = k.getBoundingBox(e);
        return eb.zmax - eb.zmin > 1e-6 && eb.xmax - eb.xmin < 1e-6 && eb.ymax - eb.ymin < 1e-6;
      });
      if (vertical.length === 0) throw new Error('This part has no straight vertical edges to round.');
      return k.fillet(shape, vertical, r);
    });
  },
  hole(k, p, shape) {
    const r = num(p.diameter, 'Hole diameter') / 2;
    if (r <= 0.05) return k.located(shape, IDENTITY);
    const b = k.getBoundingBox(shape);
    return withTemps(k, (t) => {
      const drill = t(k.translate(t(k.makeCylinder(r, b.zmax - b.zmin + 2)), num(p.x, 'X'), num(p.y, 'Y'), b.zmin - 1));
      return k.cut(shape, drill);
    });
  },
  move(k, p, shape) {
    return k.translate(shape, num(p.dx, 'X'), num(p.dy, 'Y'), num(p.dz, 'Z'));
  },
};

export class Model {
  constructor(kernel) {
    this.kernel = kernel;
    this.features = [];        // { id, op, name?, params }
    this.cursor = 0;           // steps [0, cursor) are applied; the rest are rolled back
    this.nextId = 1;
    this.blobs = new Map();    // blob id -> STEP text, for import steps
    this.cache = new Map();    // result key -> { out: [body], tick }
    this.tick = 0;
    this.state = new Map();    // part id -> body { id, key, name, path, color, shape, exact, stats? }
    this.madeBy = new Map();   // part id -> id of the last step that touched it
    this.errors = new Map();   // step id -> message
    this.undoStack = [];
    this.redoStack = [];
    this.lastMerge = null;
  }

  /* ---------- saved form ---------- */
  toJSON() {
    return { version: DOC_VERSION, nextId: this.nextId, cursor: this.cursor, features: structuredClone(this.features) };
  }
  restore(doc) {
    if (!doc || doc.version !== DOC_VERSION || !Array.isArray(doc.features)) throw new Error('This saved model is from a version this page cannot read.');
    for (const f of doc.features) if (!OPS[f.op] || typeof f.id !== 'string') throw new Error('This saved model has a step this page does not know.');
    this.features = structuredClone(doc.features);
    this.cursor = Math.max(0, Math.min(doc.cursor ?? this.features.length, this.features.length));
    this.nextId = doc.nextId || this.features.length + 1;
  }
  blobIds() { return this.features.filter((f) => f.op === 'import').map((f) => f.params.blob); }

  /* ---------- commands ---------- */
  // Applies one command and rebuilds. Throws (leaving the document as it was) if the command cannot be applied.
  exec(cmd, onProgress) {
    const before = JSON.stringify(this.toJSON());
    const record = () => {
      if (cmd.merge && cmd.merge === this.lastMerge) return;   // one undo entry per slider drag
      if (this.features.length === 0) return;                  // nothing to go back to
      this.undoStack.push(before);
      if (this.undoStack.length > UNDO_LIMIT) this.undoStack.shift();
      this.redoStack.length = 0;
    };
    let strict = null;   // ids of steps that must build, or the command is refused
    switch (cmd.type) {
      case 'sample': record(); this.features = []; this.cursor = 0; strict = this.#append(samplePlate()); break;
      case 'open': {
        if (typeof cmd.text !== 'string' || !cmd.blob) throw new Error('No file contents were given.');
        record(); this.blobs.set(cmd.blob, cmd.text);
        this.features = []; this.cursor = 0;
        strict = this.#append([{ op: 'import', name: cmd.name, params: { blob: cmd.blob } }]);
        break;
      }
      case 'add': {
        const def = OPS[cmd.op];
        if (!def || cmd.op === 'import') throw new Error('Unknown step type.');
        const params = Object.fromEntries(def.params.map((d) => [d.key, d.value]));
        Object.assign(params, cmd.params);
        if (def.target && !this.state.has(params.body)) throw new Error('Select a part for this step first.');
        record(); strict = this.#append([{ op: cmd.op, name: cmd.name, params }]);
        break;
      }
      case 'update': {
        const f = this.features.find((x) => x.id === cmd.id);
        if (!f) throw new Error('That step no longer exists.');
        record(); Object.assign(f.params, cmd.params);
        break;
      }
      case 'remove': {
        const i = this.features.findIndex((x) => x.id === cmd.id);
        if (i < 0) throw new Error('That step no longer exists.');
        record(); this.features.splice(i, 1);
        if (i < this.cursor) this.cursor--;
        break;
      }
      case 'roll': this.cursor = Math.max(0, Math.min(Math.round(num(cmd.cursor, 'Step')), this.features.length)); break;
      case 'undo': case 'redo': {
        const from = cmd.type === 'undo' ? this.undoStack : this.redoStack;
        const to = cmd.type === 'undo' ? this.redoStack : this.undoStack;
        if (from.length === 0) throw new Error(cmd.type === 'undo' ? 'Nothing to undo.' : 'Nothing to redo.');
        to.push(before); this.restore(JSON.parse(from.pop()));
        break;
      }
      case 'load': {
        this.restore(cmd.doc);
        for (const [id, text] of Object.entries(cmd.blobs || {})) this.blobs.set(id, text);
        this.undoStack.length = 0; this.redoStack.length = 0;
        break;
      }
      default: throw new Error('Unknown command.');
    }
    this.lastMerge = cmd.merge || null;
    this.rebuild(onProgress);
    const failed = strict && strict.find((id) => this.errors.has(id));
    if (failed) {
      const message = this.errors.get(failed);
      this.restore(JSON.parse(before)); this.undoStack.pop(); this.lastMerge = null;
      this.rebuild();
      throw new Error(message);
    }
  }

  // Inserts steps at the rollback point. `targetPrev` wires a step to the part made just before it.
  #append(list) {
    const ids = [];
    let prev = null;
    for (const s of list) {
      const id = 'f' + this.nextId++;
      const params = { ...s.params };
      if (s.targetPrev) params.body = prev;
      const f = { id, op: s.op, params };
      if (s.name) f.name = s.name;
      this.features.splice(this.cursor++, 0, f);
      if (!OPS[s.op].target) prev = id;
      ids.push(id);
    }
    return ids;
  }

  /* ---------- evaluation ---------- */
  rebuild(onProgress) {
    const k = this.kernel;
    this.tick++;
    this.state = new Map(); this.madeBy = new Map(); this.errors = new Map();
    for (let i = 0; i < this.cursor; i++) {
      const f = this.features[i], def = OPS[f.op];
      try {
        const target = def.target ? this.state.get(f.params.body) : null;
        if (def.target && !target) throw new Error('The part this step works on no longer exists.');
        const key = hash(JSON.stringify(def.target ? [f.op, f.params, target.key] : [f.op, f.id, f.name, f.params]));
        let entry = this.cache.get(key);
        if (!entry) {
          let out;
          if (f.op === 'import') {
            const text = this.blobs.get(f.params.blob);
            if (text == null) throw new Error('The file this step imported is no longer stored on this device.');
            out = importStep(k, text, onProgress).map((p, n) => ({ ...p, id: f.id + '.' + n, exact: false, quality: 0.05 }));
            if (out.length === 0) throw new Error('This file has no solid or surface geometry the kernel could read.');
          } else if (def.target) {
            out = [{ ...target, stats: null, shape: BUILD[f.op](k, f.params, target.shape) }];
          } else {
            out = [{ id: f.id, name: f.name || def.label, path: [], color: null, exact: true, quality: 0.03, shape: BUILD[f.op](k, f.params) }];
          }
          for (const b of out) b.key = key + '#' + b.id;
          entry = { out };
          this.cache.set(key, entry);
        }
        entry.tick = this.tick;
        for (const b of entry.out) { this.state.set(b.id, b); this.madeBy.set(b.id, f.id); }
      } catch (e) {
        this.errors.set(f.id, String(e && e.message ? e.message : e));
      }
    }
    this.#evict();
  }

  // Shapes not used by the current history are kept for a while (so undo is instant), then released.
  #evict() {
    const idle = [...this.cache].filter(([, e]) => e.tick !== this.tick).sort((a, b) => b[1].tick - a[1].tick);
    for (const [key, entry] of idle.slice(CACHE_SPARE)) {
      for (const b of entry.out) { try { this.kernel.release(b.shape); } catch (e) { /* already gone */ } }
      this.cache.delete(key);
    }
  }

  /* ---------- output ---------- */
  // The kernel shape of a part, for measuring or exporting. Valid until the history changes.
  shapeOf(partId) { return this.state.get(partId)?.shape ?? null; }

  // Parts for display. A part whose key is in `have` is sent without a mesh: the viewer already holds it.
  parts(have = new Set()) {
    const k = this.kernel, list = [];
    for (const b of this.state.values()) {
      const part = { id: b.id, key: b.key, step: this.madeBy.get(b.id), name: b.name, path: b.path, color: b.color };
      if (!have.has(b.key) || !b.stats) {
        const mesh = meshOut(k, b.shape, b.quality);
        if (!b.stats) {
          b.stats = { triangles: mesh.triangles, ...meshStats(mesh) };
          if (b.exact) {
            try {
              const v = k.getVolume(b.shape);
              if (Number.isFinite(v) && v > 1e-9) { b.stats.volume = v; b.stats.approx = false; }
            } catch (e) { /* keep the mesh figure */ }
          }
        }
        if (!have.has(b.key)) Object.assign(part, mesh);
      }
      list.push(Object.assign(part, b.stats));
    }
    return list;
  }

  summary() {
    return {
      doc: this.toJSON(),
      errors: Object.fromEntries(this.errors),
      canUndo: this.undoStack.length > 0,
      canRedo: this.redoStack.length > 0,
      shapes: this.kernel.shapeCount,
    };
  }
}
