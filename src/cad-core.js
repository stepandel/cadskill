// Geometry logic shared by the worker (browser) and the Node test.
// Everything here runs against an occt-wasm kernel instance.

const IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0];

// 3x4 row-major affine matrices: result = a * b
export function compose(a, b) {
  const r = new Array(12);
  for (let i = 0; i < 3; i++) {
    for (let j = 0; j < 4; j++) {
      r[i * 4 + j] =
        a[i * 4] * b[j] + a[i * 4 + 1] * b[4 + j] + a[i * 4 + 2] * b[8 + j] + (j === 3 ? a[i * 4 + 3] : 0);
    }
  }
  return r;
}

function meshOut(kernel, shape, quality) {
  const m = kernel.tessellate(shape, { linearDeflection: quality, angularDeflection: 0.3 });
  return {
    positions: new Float32Array(m.positions),
    normals: new Float32Array(m.normals),
    indices: new Uint32Array(m.indices),
    triangles: m.triangleCount,
  };
}

function measure(kernel, shape) {
  const out = {};
  try {
    const b = kernel.getBoundingBox(shape);
    out.size = [b.xmax - b.xmin, b.ymax - b.ymin, b.zmax - b.zmin];
  } catch (e) { /* leave size out */ }
  try {
    const v = kernel.getVolume(shape);
    if (Number.isFinite(v) && v > 1e-9) out.volume = v;
  } catch (e) { /* surfaces have no volume */ }
  return out;
}

// Size and volume straight from the triangles. Exact kernel measurement is far
// slower on real parts, and the mesh is within a fraction of a percent.
export function meshStats(m) {
  const p = m.positions, ix = m.indices;
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (let i = 0; i < p.length; i += 3) {
    for (let k = 0; k < 3; k++) {
      const v = p[i + k];
      if (v < lo[k]) lo[k] = v;
      if (v > hi[k]) hi[k] = v;
    }
  }
  const c = [(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2];
  let vol = 0;
  for (let i = 0; i < ix.length; i += 3) {
    const a = ix[i] * 3, b = ix[i + 1] * 3, d = ix[i + 2] * 3;
    const ax = p[a] - c[0], ay = p[a + 1] - c[1], az = p[a + 2] - c[2];
    const bx = p[b] - c[0], by = p[b + 1] - c[1], bz = p[b + 2] - c[2];
    const dx = p[d] - c[0], dy = p[d + 1] - c[1], dz = p[d + 2] - c[2];
    vol += ax * (by * dz - bz * dy) - ay * (bx * dz - bz * dx) + az * (bx * dy - by * dx);
  }
  return { size: [hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]], volume: Math.abs(vol) / 6, approx: true };
}

// Import a STEP file, walk its assembly tree and return one mesh per placed part.
export function loadStep(kernel, text, quality = 0.05, onPart) {
  const doc = kernel.importXCAFFromSTEP(text);
  const parts = [];
  try {
    const walk = (label, world, path) => {
      const info = doc.getLabelInfo(label);
      const proto = doc.getReferredLabel(label) ?? label;
      const pinfo = proto === label ? info : doc.getLabelInfo(proto);
      const here = info.isComponent ? compose(world, doc.getLocation(label)) : world;
      const name = cleanName(info.name) || cleanName(pinfo.name) || 'Part';
      const kids = doc.getChildren(proto);
      if (kids.length > 0) {
        for (const k of kids) walk(k, here, path.concat(name));
        return;
      }
      if (pinfo.shapeHandle == null) return;
      const placed = kernel.located(pinfo.shapeHandle, here);
      const mesh = meshOut(kernel, placed, quality);
      kernel.release(placed);
      if (mesh.triangles === 0) return;
      const part = {
        name,
        path,
        color: pinfo.hasColor ? pinfo.color : info.hasColor ? info.color : null,
        ...meshStats(mesh),
        ...mesh,
      };
      parts.push(part);
      if (onPart) onPart(parts.length);
    };
    for (const root of doc.getRoots()) walk(root, IDENTITY, []);
  } finally {
    doc.close();
  }
  return parts;
}

function cleanName(n) {
  if (!n) return '';
  if (n.startsWith('=>')) return '';
  return n;
}

// The built-in sample: a mounting plate rebuilt from five numbers.
// This is the "history as parameters" idea in its smallest form.
export function buildPlate(kernel, p, quality = 0.03) {
  const made = [];
  const keep = (s) => { made.push(s); return s; };
  try {
    let body = keep(kernel.makeBox(p.length, p.width, p.thickness));
    const r = Math.min(p.corner, Math.min(p.length, p.width) / 2 - 0.05);
    if (r > 0.05) {
      const vertical = kernel.getSubShapes(body, 'edge').filter((e) => {
        const b = kernel.getBoundingBox(e);
        return b.zmax - b.zmin > p.thickness * 0.9 && b.xmax - b.xmin < 1e-6 && b.ymax - b.ymin < 1e-6;
      });
      body = keep(kernel.fillet(body, vertical, r));
    }
    const hr = Math.min(p.hole / 2, Math.min(p.length, p.width) / 2 - 1);
    if (hr > 0.1) {
      const drill = keep(kernel.translate(keep(kernel.makeCylinder(hr, p.thickness + 2)), p.length / 2, p.width / 2, -1));
      body = keep(kernel.cut(body, drill));
    }
    const centred = keep(kernel.translate(body, -p.length / 2, -p.width / 2, 0));
    const part = { name: 'Mounting plate', path: [], color: null, ...measure(kernel, centred), approx: false, ...meshOut(kernel, centred, quality) };
    return part;
  } finally {
    for (const s of made) { try { kernel.release(s); } catch (e) { /* already gone */ } }
  }
}
