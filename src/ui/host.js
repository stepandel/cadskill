// Where models come from. Inside a Claude conversation the page is an MCP App:
// the host tells it which model version a tool just built, and it asks the
// server for that version's meshes. Opened as a plain local page, it polls the
// server instead. A page exported as one file has the model embedded and needs
// no server. Either way the rest of the page just receives parts.
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
// Returns { mesh(model, version), history(model) } for the page to load any version;
// history is null when there is no server to ask (an exported page).
export async function connect(handlers) {
  let latest = '';
  const follow = (model, version) => {
    const id = model + '@' + version;
    if (!model || !version || id === latest) return;
    latest = id;
    queueMicrotask(() => handlers.latest(model, version));   // never before connect() has returned its API
  };

  // A page written by `export html` carries its model with it and talks to nobody.
  // There is no history to read, so history is null.
  if (window.CADSKILL_MODEL) {
    const data = decode(window.CADSKILL_MODEL);
    follow(data.model, data.version);
    return { mesh: async () => data, history: null };
  }

  if (window.parent !== window) {
    const app = new App({ name: 'CadSkill viewer', version: '0.1.2' });
    const call = async (name, args) => {
      const res = await app.callServerTool({ name, arguments: args });
      const text = res.content && res.content.find((c) => c.type === 'text');
      if (res.isError || !text) throw new Error(text ? text.text : 'no data');
      return JSON.parse(text.text);
    };
    const api = {
      mesh: async (model, version) => decode(await call('get_mesh', { model, version })),
      history: (model) => call('get_history', { model }),
      openSteps: async (model, version) => {
        const res = await app.callServerTool({ name: 'open_build_steps', arguments: { model, version } });
        if (res.isError || !res.structuredContent?.url) {
          throw new Error(res.content?.find((c) => c.type === 'text')?.text || 'Could not open build steps.');
        }
        await app.openLink({ url: res.structuredContent.url });
      },
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
    steps: (model, version) => get('./build-steps?model=' + encodeURIComponent(model) + '&version=' + version),
  };
  const model = new URLSearchParams(window.location.search).get('model');
  const statePath = './state' + (model ? '?model=' + encodeURIComponent(model) : '');
  const poll = async () => {
    try {
      const state = await get(statePath);
      if (state.model) follow(state.model, state.version);
      else handlers.status('No model yet. Ask Claude to build one.');
    } catch (e) {
      handlers.status('The CadSkill server is not running.', true);
    }
    setTimeout(poll, POLL_MS);
  };
  poll();
  return api;
}
