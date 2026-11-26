// Builds the viewer into one self-contained HTML file that the MCP server
// hands to the host: the page, its modules, Three.js and the MCP Apps SDK,
// with nothing left to fetch. The result is committed, so an installed plugin
// needs Python only, not Node.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const out = path.join(root, 'server/cadbench_mcp/static/viewer.html');
const TAG = '<script type="module" src="./ui/app.js"></script>';

const bundle = await build({
  entryPoints: [path.join(root, 'src/ui/app.js')],
  bundle: true,
  format: 'esm',
  minify: true,
  target: 'es2022',
  legalComments: 'none',
  write: false,
});
const html = fs.readFileSync(path.join(root, 'src/index.html'), 'utf8');
if (!html.includes(TAG)) {
  console.error(`src/index.html no longer contains ${TAG}; update scripts/build.mjs.`);
  process.exit(1);
}
// A literal "</script" inside the bundle would end the inline script early.
const code = bundle.outputFiles[0].text.replace(/<\/script/gi, '<\\/script');
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, html.replace(TAG, () => `<script type="module">\n${code}</script>`));
console.log(`viewer.html ready: ${(fs.statSync(out).size / 1024).toFixed(0)} KB`);
