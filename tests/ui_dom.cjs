/* Minimal DOM model for plain-Node behavior checks; not a browser or layout engine. */
const assert = require('node:assert/strict');
const decode = text => text.replace(/&(amp|lt|gt|quot|#39);/g, (_, name) => ({amp:'&', lt:'<', gt:'>', quot:'"', '#39':"'"}[name]));
const camel = name => name.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
const domError = message => Object.assign(new Error(message), {name: 'NotFoundError'});
class Element {
  constructor(tag='div', attrs={}) {
    this.tag = tag; this.tagName=tag.toUpperCase(); this.attrs = attrs; this.dataset = {}; this.children = [];
    this.style = {setProperty: () => {}}; this.textContent = ''; this.value = attrs.value || ''; this.id=attrs.id||'';
    this.disabled = Object.hasOwn(attrs, 'disabled'); this.isConnected = true;
    this.checked = Object.hasOwn(attrs, 'checked'); this.readOnly = Object.hasOwn(attrs, 'readonly');
    for (const [key, value] of Object.entries(attrs)) if (key.startsWith('data-')) this.dataset[camel(key.slice(5))] = value;
    const classes = new Set((attrs.class || '').split(/\s+/));
    const sync=()=>{this.attrs.class=[...classes].join(' ')};
    this.classList = {add: name => {classes.add(name);sync()}, remove: name => {classes.delete(name);sync()},
      contains: name => classes.has(name),
      toggle: (name, enabled) => {enabled ? classes.add(name) : classes.delete(name);sync()}};
  }
  /* Browser behaviour (D16): removing the focused element fires `focusout` (relatedTarget null) synchronously, before the
     removal completes; when a listener replaced this container's children meanwhile, the removal fails like Chromium's
     `NotFoundError: ... The node to be removed is no longer a child of this node`. */
  _detach(operation) {
    const old = this.children, focused = document.activeElement;
    if (focused && old.some(child => child.contains(focused))) {
      document.activeElement = null;
      fire('focusout', {target: focused, relatedTarget: null});
      if (this.children !== old) throw domError(`Failed to ${operation}: The node to be removed is no longer a child of this node. Perhaps it was moved in a 'blur' event handler?`);
    }
    old.forEach(child => { child.parentNode = null; });
    this.children = [];
  }
  set innerHTML(html) { this._detach("set the 'innerHTML' property on 'Element'"); this._parse(html); }
  replaceChildren(...nodes) {
    this._detach("execute 'replaceChildren' on 'Element'");
    nodes.forEach(node => { node.parentNode = this; this.children.push(node); });
  }
  removeChild(child) {
    const operation = "Failed to execute 'removeChild' on 'Node': The node to be removed is";
    if (child.parentNode !== this) throw domError(`${operation} not a child of this node.`);
    const focused = document.activeElement;
    if (focused && child.contains(focused)) { document.activeElement = null; fire('focusout', {target: focused, relatedTarget: null}); }
    if (child.parentNode !== this) throw domError(`${operation} no longer a child of this node. Perhaps it was moved in a 'blur' event handler?`);
    this.children = this.children.filter(other => other !== child); child.parentNode = null; return child;
  }
  _parse(html) {
    this.html = html; this.children = [];
    const stack = [this];
    for (const match of html.matchAll(/<(\/?)([a-z][\w-]*)([^>]*)>/gi)) {
      const [, closing, tag, rest] = match;
      if (closing) { if (stack.length > 1) stack.pop(); continue; }
      const attrs = {};
      for (const attr of rest.matchAll(/([\w-]+)(?:="([^"]*)")?/g)) attrs[attr[1]] = decode(attr[2] || '');
      const element = new Element(tag, attrs), parent = stack.at(-1);
      element.parentNode = parent; parent.children.push(element);
      if (!['input', 'meta', 'br', 'hr', 'img'].includes(tag)) stack.push(element);
    }
    for (const select of this.querySelectorAll('select')) {
      const options = select.querySelectorAll('option'); // also inside <optgroup>
      select.value = (options.find(option => Object.hasOwn(option.attrs, 'selected')) || options[0] || {value:''}).value;
    }
  }
  get innerHTML() { return this.html || ''; }
  matches(selector) {
    const match = selector.match(/^(\w+)?(?:\.([\w-]+))?(?:\[([\w-]+)(?:="([^"]*)")?\])?$/);
    if (!match) return false;
    const [, tag, cls, attr, value] = match;
    return (!tag || this.tag === tag) && (!cls || (this.attrs.class || '').split(/\s+/).includes(cls)) &&
      (!attr || Object.hasOwn(this.attrs, attr) && (value === undefined || this.attrs[attr] === value));
  }
  querySelectorAll(selector) {
    return this.children.flatMap(child => [...(child.matches(selector) ? [child] : []), ...child.querySelectorAll(selector)]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  contains(other) { for (let node = other; node; node = node.parentNode) if (node === this) return true; return false; }
  focus() { const previous = document.activeElement; document.activeElement = this;
    if (previous && previous !== this) fire('focusout', {target: previous, relatedTarget: this}); }
  blur() { const previous = document.activeElement; document.activeElement = null;
    if (previous) fire('focusout', {target: previous, relatedTarget: null}); }
  closest(selector) { for (let node = this; node; node = node.parentNode) if (node.matches && node.matches(selector)) return node; return null; }
  setAttribute(name, value) {
    this.attrs[name] = String(value);
    if (name.startsWith('data-')) this.dataset[camel(name.slice(5))] = String(value);
  }
  getAttribute(name) { return Object.hasOwn(this.attrs, name) ? this.attrs[name] : null; }
  removeAttribute(name) { delete this.attrs[name]; }
  /* Geometry is not modelled: a test gives an element a box with `el.rect = {left, top, width, height}` or installs
     `document.layout = el => box|null` that is asked for every element (so boxes survive re-renders). */
  getBoundingClientRect() {
    const box = this.rect || (document.layout && document.layout(this)) || {left: 0, top: 0, width: 0, height: 0};
    return {...box, right: box.left + box.width, bottom: box.top + box.height, x: box.left, y: box.top};
  }
  /* Like Element.replaceWith for one node: the node takes this element's place (it is detached from its old parent first). */
  replaceWith(node) {
    const parent = this.parentNode;
    if (node.parentNode) node.parentNode.children = node.parentNode.children.filter(other => other !== node);
    parent.children = parent.children.map(child => child === this ? node : child);
    node.parentNode = parent; this.parentNode = null;
  }
  setPointerCapture() {} // no-op in the model: pointer events go to the document listeners and to `onpointer…` handlers
  releasePointerCapture() {}
  hasPointerCapture() { return false; }
  /* Unlike the innerHTML setter, a real insertAdjacentHTML keeps the existing children (and the focus). */
  insertAdjacentHTML(where, html) { this._parse(where === 'afterbegin' ? html + this.innerHTML : this.innerHTML + html); }
}
const elements = new Map();
const document = {
  documentElement: new Element('html'),
  getElementById: id => {
    for(const root of elements.values()){
      const child=root.querySelectorAll('[id]').find(el=>el.id===id);if(child)return child;
    }
    if (!elements.has(id)) elements.set(id, new Element('div',{id})); return elements.get(id);
  },
  querySelectorAll: selector => [...elements.values()].flatMap(el => el.querySelectorAll(selector)),
  activeElement: null,
  addEventListener: (type, fn) => { if (!docListeners.has(type)) docListeners.set(type, []); docListeners.get(type).push(fn); }
};
/* The topmost element (last in document order) whose box contains the point; elements without a box are never hit. */
document.elementFromPoint = (x, y) => {
  const all = [], seen = new Set();
  const walk = el => { all.push(el); el.children.forEach(walk); };
  for (const root of elements.values()) if (!seen.has(root)) { seen.add(root); walk(root); }
  let hit = null;
  for (const el of all) {
    const box = el.getBoundingClientRect();
    if (box.width > 0 && box.height > 0 && x >= box.left && x < box.right && y >= box.top && y < box.bottom) hit = el;
  }
  return hit;
};
const docListeners = new Map();
const fire = (type, event) => (docListeners.get(type) || []).forEach(fn => fn(event));
/* Pointer input (round 3, section 7): events carry coordinates and bubble from the element under the point (or `target`) through
   its parents' `on<type>` properties to the document listeners, like the browser's pointer events. `buttons` is 1 while the
   pointer is down. `click` is sent by the test after pointerup, like the browser does when both happen on one element. */
const pointer = {
  pointerId: 1,
  send(type, x, y, buttons, target, extra = {}) {
    const hit = target || document.elementFromPoint(x, y) || document.documentElement;
    const event = {type, target: hit, clientX: x, clientY: y, pointerId: this.pointerId, pointerType: 'mouse', isPrimary: true,
      button: 0, buttons, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; }, stopPropagation() {}, ...extra};
    for (let node = hit; node; node = node.parentNode) {
      event.currentTarget = node;
      if (typeof node['on' + type] === 'function') node['on' + type](event);
    }
    fire(type, event);
    return event;
  },
  down(x, y, target, extra) { return this.send('pointerdown', x, y, 1, target, extra); },
  move(x, y) { return this.send('pointermove', x, y, 1); },
  up(x, y) { return this.send('pointerup', x, y, 0); },
  cancel(x, y) { return this.send('pointercancel', x, y, 0); },
  click(x, y, target) { return this.send('click', x, y, 0, target); },
  key(key) {
    const hit = document.activeElement || document.documentElement;
    const event = {type: 'keydown', key, target: hit, preventDefault() {}};
    for (let node = hit; node; node = node.parentNode) if (typeof node.onkeydown === 'function') node.onkeydown(event);
    fire('keydown', event);
  }
};
// Timers never run on their own: tests fire them by hand (`timers.splice(0).forEach(fn => fn())`).
const timers = [];
const setTimeout = (fn, ms = 0) => { timers.push(Object.assign(() => fn(), {ms})); return timers.length; };
// `flushZeroTimers()` runs only the `setTimeout(…, 0)` entries (the focus flush), also those scheduled while flushing;
// longer timers (expiry, disarm) stay queued.
const flushZeroTimers = () => { for (let i = 0; i < 100; i++) {
  const due = timers.filter(fn => fn.ms === 0); if (!due.length) return;
  due.forEach(fn => timers.splice(timers.indexOf(fn), 1)); due.forEach(fn => fn()); } };
const messages = [], listeners = new Map();
const window = {addEventListener: (type, fn) => listeners.set(type, fn), postMessage: message => messages.push(message)};
window.parent = window;
const location = {search: process.env.ACTIONS || ''};
if (process.env.IFRAME === '1') window.parent = {postMessage: message => messages.push(message)};
