// Where models come from. Inside a Claude conversation the page is an MCP App:
// the host tells it which model version a tool just built, and it asks the
// server for that version's meshes. Opened as a plain local page, it polls the
// server instead. Either way the rest of the page just receives parts.
import { App } from '@modelcontextprotocol/ext-apps';

const POLL_MS = 1000;
const HOST_WAIT_MS = 4000;

function bytes(b64) {
  const bin = atob(b64), out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out.buffer;
}
// The server sends each mesh as base64 text; the viewer wants typed arrays.
function decode(data) {
  return {
    model: data.model,
    version: data.version,
    parts: data.parts.map((p) => ({
      ...p,
      path: [],
      positions: new Float32Array(bytes(p.positions)),
      normals: new Float32Array(bytes(p.normals)),
      indices: new Uint32Array(bytes(p.indices)),
    })),
  };
}

// handlers: latest(model, version)              the server built (or restored) a version
//           status(text, bad)                   something to tell the person
//           theme('light' | 'dark')             the host's colour scheme
// Returns { mesh(model, version), history(model) } for the page to load any version.
export async function connect(handlers) {
  let latest = '';
  const follow = (model, version) => {
    const id = model + '@' + version;
    if (!model || !version || id === latest) return;
    latest = id;
    handlers.latest(model, version);
  };

  if (window.parent !== window) {
    const app = new App({ name: 'CAD Bench viewer', version: '0.1.0' });
    const call = async (name, args) => {
      const res = await app.callServerTool({ name, arguments: args });
      const text = res.content && res.content.find((c) => c.type === 'text');
      if (res.isError || !text) throw new Error(text ? text.text : 'no data');
      return JSON.parse(text.text);
    };
    const api = {
      mesh: async (model, version) => decode(await call('get_mesh', { model, version })),
      history: (model) => call('get_history', { model }),
    };
    app.ontoolresult = (result) => {
      const built = result.structuredContent;
      if (built && built.model) follow(built.model, built.version);
      else if (result.isError) handlers.status('That change failed; the model is unchanged.', true);
    };
    app.onhostcontextchanged = (ctx) => { if (ctx && ctx.theme) handlers.theme(ctx.theme); };
    try {
      await Promise.race([app.connect(), new Promise((_, no) => setTimeout(() => no(new Error('no host answered')), HOST_WAIT_MS))]);
      const ctx = app.getHostContext();
      if (ctx && ctx.theme) handlers.theme(ctx.theme);
      return api;
    } catch (e) { /* framed by something that is not an MCP host: fall through to polling */ }
  }

  const get = async (path) => {
    const res = await fetch(path);
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  };
  const api = {
    mesh: async (model, version) => decode(await get('./mesh?model=' + encodeURIComponent(model) + '&version=' + version)),
    history: (model) => get('./history?model=' + encodeURIComponent(model)),
  };
  const poll = async () => {
    try {
      const state = await get('./state');
      if (state.model) follow(state.model, state.version);
      else handlers.status('No model yet. Ask Claude to build one.');
    } catch (e) {
      handlers.status('The CAD Bench server is not running.', true);
    }
    setTimeout(poll, POLL_MS);
  };
  poll();
  return api;
}
