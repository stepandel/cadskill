// Minimal static server for dist/, for local testing. No dependencies.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const dist = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'dist');
const port = Number(process.env.PORT) || 8765;
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.wasm': 'application/wasm', '.json': 'application/json' };

if (!fs.existsSync(path.join(dist, 'index.html'))) {
  console.error('dist/ is missing. Run "npm run build" first.');
  process.exit(1);
}

http.createServer((req, res) => {
  const rel = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  const file = path.join(dist, rel === '/' ? 'index.html' : rel);
  if (!file.startsWith(dist + path.sep) && file !== path.join(dist, 'index.html')) { res.writeHead(403).end(); return; }
  fs.readFile(file, (err, data) => {
    if (err) { res.writeHead(404, { 'content-type': 'text/plain' }).end('Not found'); return; }
    res.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream', 'content-length': data.length });
    res.end(data);
  });
}).listen(port, '127.0.0.1', () => console.log(`CAD Bench at http://127.0.0.1:${port}/`));
