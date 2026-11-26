// Packs the plugin for upload (Customize > Plugins > Add > Upload plugin): the
// manifest, the skill and the server, without tests, caches or the virtual
// environment. Run `npm run build` first so the viewer inside is current.
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out = path.join(root, 'dist', 'cadskill-plugin.zip');
if (!fs.existsSync(path.join(root, 'server/cadskill_mcp/static/viewer.html'))) {
  console.error('The viewer has not been built. Run "npm run build" first.');
  process.exit(1);
}
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.rmSync(out, { force: true });
execFileSync('zip', ['-r', '-q', out, '.claude-plugin', 'skills', 'server/pyproject.toml', 'server/uv.lock', 'server/cadskill_mcp',
  '-x', '*/__pycache__/*', '*.pyc', '*.DS_Store'], { cwd: root, stdio: 'inherit' });
console.log(`${path.relative(root, out)} ready: ${(fs.statSync(out).size / 1024).toFixed(0)} KB`);
