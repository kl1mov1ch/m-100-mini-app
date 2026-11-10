import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

const source=await readFile(new URL('../frontend/src/lib/input-visibility.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText;
const {inputScrollDistance,installInputVisibility}=await import('data:text/javascript;base64,'+Buffer.from(compiled).toString('base64'));
assert.equal(inputScrollDistance(100,146,0,500),0);
assert.equal(inputScrollDistance(600,646,0,500),166);
assert.equal(inputScrollDistance(80,126,120,620),-60);
assert.equal(inputScrollDistance(300,900,0,420),280);

const listeners=new Map();
const properties=new Map();
let scroll=0;
class Element {
  matches(){return true;}
  getBoundingClientRect(){return {top:700-scroll,bottom:746-scroll,height:46};}
}
globalThis.HTMLElement=Element;
const input=new Element();
const container={scrollHeight:1000,clientHeight:400,parentElement:null,scrollBy:({top})=>{scroll+=top;}};
input.parentElement=container;
const root={dataset:{},style:{setProperty:(key,value)=>properties.set(key,value)}};
globalThis.document={documentElement:root,body:{},activeElement:null,addEventListener:(name,callback)=>listeners.set(name,callback),removeEventListener:(name)=>listeners.delete(name)};
const viewport={height:852,offsetTop:0,addEventListener:(name,callback)=>listeners.set('viewport-'+name,callback),removeEventListener:(name)=>listeners.delete('viewport-'+name)};
globalThis.window={innerHeight:852,innerWidth:394,visualViewport:viewport,addEventListener:(name,callback)=>listeners.set('window-'+name,callback),removeEventListener:(name)=>listeners.delete('window-'+name),scrollBy:()=>{throw new Error('Внутри окна нужно прокручивать его содержимое');}};
globalThis.requestAnimationFrame=callback=>{callback();return 1;};
globalThis.cancelAnimationFrame=()=>{};
globalThis.getComputedStyle=()=>({overflowY:'auto'});
const uninstall=installInputVisibility();
document.activeElement=input;
viewport.height=520;
listeners.get('viewport-resize')();
assert.equal(root.dataset.keyboardOpen,'true');
assert.equal(properties.get('--visible-height'),'520px');
assert.equal(scroll,246);
assert.equal(input.getBoundingClientRect().bottom,500);
document.activeElement=null;
viewport.height=852;
listeners.get('viewport-resize')();
assert.equal(root.dataset.keyboardOpen,'false');
uninstall();
assert.equal(listeners.size,0);
console.log('Keyboard visibility and nested input scrolling passed');
