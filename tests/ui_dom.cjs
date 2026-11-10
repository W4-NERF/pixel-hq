/* Minimal DOM model for plain-Node behavior checks; not a browser or layout engine. */
const assert = require('node:assert/strict');
const decode = text => text.replace(/&(amp|lt|gt|quot|#39);/g, (_, name) => ({amp:'&', lt:'<', gt:'>', quot:'"', '#39':"'"}[name]));
const camel = name => name.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
class Element {
  constructor(tag='div', attrs={}) {
    this.tag = tag; this.attrs = attrs; this.dataset = {}; this.children = [];
    this.style = {setProperty: () => {}}; this.textContent = ''; this.value = attrs.value || '';
    this.disabled = Object.hasOwn(attrs, 'disabled'); this.isConnected = true;
    for (const [key, value] of Object.entries(attrs)) if (key.startsWith('data-')) this.dataset[camel(key.slice(5))] = value;
    const classes = new Set((attrs.class || '').split(/\s+/));
    this.classList = {add: name => classes.add(name), remove: name => classes.delete(name),
      toggle: (name, enabled) => enabled ? classes.add(name) : classes.delete(name)};
  }
  set innerHTML(html) {
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
      const options = select.children;
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
  insertAdjacentHTML(where, html) { this.innerHTML = where === 'afterbegin' ? html + this.innerHTML : this.innerHTML + html; }
}
const elements = new Map();
const document = {
  getElementById: id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); },
  querySelectorAll: selector => [...elements.values()].flatMap(el => el.querySelectorAll(selector))
};
const messages = [], listeners = new Map();
const window = {addEventListener: (type, fn) => listeners.set(type, fn), postMessage: message => messages.push(message)};
window.parent = window;
const location = {search: process.env.ACTIONS || ''};
if (process.env.IFRAME === '1') window.parent = {postMessage: message => messages.push(message)};
