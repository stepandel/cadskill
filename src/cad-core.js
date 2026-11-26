// Geometry logic shared by the worker (browser) and the Node test.
// Everything here runs against an occt-wasm kernel instance.

export const IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0];

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

export function meshOut(kernel, shape, quality) {
  const m = kernel.tessellate(shape, { linearDeflection: quality, angularDeflection: 0.3 });
  return {
    positions: new Float32Array(m.positions),
    normals: new Float32Array(m.normals),
    indices: new Uint32Array(m.indices),
    triangles: m.triangleCount,
  };
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

// Import a STEP file, walk its assembly tree and return one kernel shape per
// placed part: { name, path, color, shape }. The caller owns the shapes.
//
// Each part is placed with the kernel's exact transform before anything meshes
// it: some files keep geometry far from the origin, and moving 32-bit mesh
// vertices afterwards would lose precision.
export function importStep(kernel, text, onPart) {
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
      const shape = kernel.located(pinfo.shapeHandle, here);
      if (kernel.subShapeCount(shape, 'face') === 0) { kernel.release(shape); return; }
      parts.push({ name, path, color: pinfo.hasColor ? pinfo.color : info.hasColor ? info.color : null, shape });
      if (onPart) onPart(parts.length);
    };
    for (const root of doc.getRoots()) walk(root, IDENTITY, []);
  } catch (e) {
    for (const p of parts) { try { kernel.release(p.shape); } catch (e2) { /* already gone */ } }
    throw e;
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
