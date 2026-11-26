// The 3D view: scene, camera, the drawn parts, and which one is selected.
// It owns `view.parts` and `view.selected`; the rest of the page reads them and
// is told about selection changes through onSelect.
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { $, css } from './dom.js';

// parts: { id, key, step, name, path, size, volume, approx, triangles, mesh, lines, base, box }
export const view = { parts: [], selected: null };

const stage = $('stage');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
stage.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 10000);
camera.up.set(0, 0, 1);                       // CAD convention: Z is up
camera.position.set(90, -120, 80);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = false;
scene.add(new THREE.HemisphereLight(0xffffff, 0x5a6470, 1.1));
const key = new THREE.DirectionalLight(0xffffff, 1.6);
camera.add(key); key.position.set(-0.6, 0.9, 1);
scene.add(camera);
const model = new THREE.Group();
scene.add(model);

let queued = false;
export function draw() { if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; renderer.render(scene, camera); }); }
controls.addEventListener('change', draw);
function resize() {
  const w = stage.clientWidth, h = stage.clientHeight;
  if (!w || !h) return;
  renderer.setSize(w, h, false);
  camera.aspect = w / h; camera.updateProjectionMatrix();
  draw();
}
new ResizeObserver(resize).observe(stage);

function paint(p) {
  p.mesh.material.color.copy(p === view.selected ? new THREE.Color(css('--accent')) : p.base);
}
function applyTheme() {
  scene.background = new THREE.Color(css('--paper'));
  const edge = new THREE.Color(css('--ink'));
  for (const p of view.parts) { p.lines.material.color.copy(edge); paint(p); }
  draw();
}
new MutationObserver(applyTheme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);

function dispose(p) { p.mesh.geometry.dispose(); p.mesh.material.dispose(); p.lines.geometry.dispose(); p.lines.material.dispose(); }

function makePart(d) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(d.positions, 3));
  g.setAttribute('normal', new THREE.BufferAttribute(d.normals, 3));
  g.setIndex(new THREE.BufferAttribute(d.indices, 1));
  g.computeBoundingBox();
  const base = d.color ? new THREE.Color().setRGB(d.color[0], d.color[1], d.color[2], THREE.SRGBColorSpace) : new THREE.Color(css('--model'));
  const mesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: base, metalness: 0.1, roughness: 0.62, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 }));
  const lines = new THREE.LineSegments(new THREE.EdgesGeometry(g, 28), new THREE.LineBasicMaterial({ color: css('--ink'), transparent: true, opacity: 0.55 }));
  mesh.add(lines);
  const p = { id: d.id, key: d.key, mesh, lines, base, box: g.boundingBox };
  mesh.userData.part = p;
  return p;
}

// Replaces the drawn parts with the worker's list. A part whose key is already
// drawn is reused (the worker sends no mesh for it).
// The selection is cleared: the caller re-selects once the page is redrawn.
// Returns true if the set of parts changed.
export function setParts(list) {
  const old = new Map(view.parts.map((p) => [p.key, p]));
  const before = view.parts.map((p) => p.id).join();
  const next = [];
  model.clear();
  for (const d of list) {
    let p = old.get(d.key);
    if (p) old.delete(d.key); else if (d.positions) p = makePart(d); else continue;
    Object.assign(p, { step: d.step, name: d.name, path: d.path, size: d.size, volume: d.volume, approx: d.approx, triangles: d.triangles });
    paint(p);
    model.add(p.mesh); next.push(p);
  }
  for (const p of old.values()) dispose(p);
  view.parts = next; view.selected = null;
  draw();
  return before !== next.map((p) => p.id).join();
}

const selectListeners = [];
export function onSelect(fn) { selectListeners.push(fn); }     // fn(part or null)

export function select(p) {
  const prev = view.selected; view.selected = p;
  if (prev) paint(prev);
  if (p) paint(p);
  for (const fn of selectListeners) fn(p);
  draw();
}

function bounds() {
  const box = new THREE.Box3();
  for (const p of view.parts) box.union(p.box);
  return box;
}
// Overall size of everything drawn, as [x, y, z] in mm, or null when there is nothing.
export function modelSize() {
  const box = bounds();
  if (box.isEmpty()) return null;
  const s = box.getSize(new THREE.Vector3());
  return [s.x, s.y, s.z];
}

export function fit() {
  const box = bounds();
  if (box.isEmpty()) return;
  const s = box.getBoundingSphere(new THREE.Sphere());
  const dir = camera.position.clone().sub(controls.target).normalize();
  const half = THREE.MathUtils.degToRad(camera.fov) / 2;                       // vertical half-angle
  const narrow = Math.min(half, Math.atan(Math.tan(half) * camera.aspect));   // the tighter of vertical and horizontal, so tall windows fit too
  const dist = s.radius / Math.sin(narrow) * 1.08;
  controls.target.copy(s.center);
  camera.position.copy(s.center).addScaledVector(dir, dist);
  camera.near = Math.max(dist / 500, 0.01); camera.far = dist * 20; camera.updateProjectionMatrix();
  controls.update(); draw();
}

// A click (not a drag) on the model selects the part under the pointer.
const ray = new THREE.Raycaster();
let down = null;
renderer.domElement.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
renderer.domElement.addEventListener('pointerup', (e) => {
  if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return;
  const r = renderer.domElement.getBoundingClientRect();
  ray.setFromCamera(new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1), camera);
  const hit = ray.intersectObjects(view.parts.map((p) => p.mesh), false)[0];
  select(hit ? hit.object.userData.part : null);
});

applyTheme(); resize();
