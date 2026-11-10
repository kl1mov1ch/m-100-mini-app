import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

const source = await readFile(new URL('../frontend/src/lib/telegram.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText;
const properties = new Map();
const handlers = new Map();
const links = [];
let expanded = false;
let requestedScript = false;
globalThis.location = { hash: '' };
globalThis.window = { innerHeight: 852 };
globalThis.document = { documentElement: { dataset: {}, style: { setProperty: (key, value) => properties.set(key, value) } }, createElement: () => { requestedScript = true; } };
const telegram = await import('data:text/javascript;base64,' + Buffer.from(compiled).toString('base64'));
await telegram.initializeTelegram();
assert.equal(requestedScript, false);
window.Telegram = { WebApp: {
  initData: 'verified-by-server', viewportHeight: 800,
  safeAreaInset: { top: 24, bottom: 20, left: 0, right: 0 },
  contentSafeAreaInset: { top: 32, bottom: 0, left: 0, right: 0 },
  isVersionAtLeast: () => true,
  onEvent: (name, callback) => handlers.set(name, callback),
  setHeaderColor: () => {}, setBackgroundColor: () => {}, setBottomBarColor: () => {},
  expand: () => { expanded = true; },
  openLink: (url) => links.push(url),
} };
telegram.configureTelegram();
assert.equal(expanded, true);
assert.equal(properties.get('--app-height'), '800px');
assert.equal(properties.get('--app-safe-top'), '56px');
assert.equal(properties.get('--app-safe-bottom'), '20px');
window.Telegram.WebApp.viewportHeight = 420;
handlers.get('viewportChanged')();
assert.equal(properties.get('--app-height'), '420px');
let prevented = false;
telegram.openExternalLink({ preventDefault: () => { prevented = true; } }, 'https://example.com');
assert.equal(prevented, true);
assert.deepEqual(links, ['https://example.com']);
console.log('Telegram viewport, safe area, external links and browser fallback passed');
