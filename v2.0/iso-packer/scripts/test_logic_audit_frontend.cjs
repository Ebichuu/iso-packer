const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function settingsHarness() {
  const requests = [];
  const nodes = new Map();
  const callbacks = {};
  const element = (id = "") => {
    const classes = new Set();
    const handlers = {};
    const node = {
      id, handlers, dataset: {}, value: "", tagName: "INPUT", disabled: false,
      elements: {}, textContent: "", children: [],
      classList: { add: (v) => classes.add(v), remove: (v) => classes.delete(v), contains: (v) => classes.has(v) },
      addEventListener(type, callback) { handlers[type] = callback; },
      dispatchEvent() {}, focus() {}, closest() { return null; }, querySelector() { return null; },
      append(...children) { this.children.push(...children); },
      appendChild(child) { this.children.push(child); },
      replaceChildren(...children) { this.children = children; },
    };
    if (id) nodes.set(id, node);
    return node;
  };
  for (const id of ["system-config-form", "directory-picker", "directory-picker-title", "directory-picker-path", "directory-picker-list", "directory-picker-up", "directory-picker-use", "watch_dir", "output_dir"]) element(id);
  const context = {
    Event,
    document: {
      body: element(), createElement: () => element(), getElementById: (id) => nodes.get(id) || null,
      addEventListener(type, callback) { callbacks[type] = callback; },
    },
    window: {
      addEventListener() {}, setTimeout() {}, location: { reload() {} },
      IsoPacker: {
        qs: (selector) => nodes.get(selector.slice(1)) || null,
        setText(node, text) { if (node) node.textContent = text; },
        clearNode(node) { node.replaceChildren(); }, notify() {},
        fetchJson(url) { return new Promise((resolve, reject) => requests.push({ url, resolve, reject })); },
      },
    },
  };
  const filename = path.join(__dirname, "../static/js/settings.js");
  const source = fs.readFileSync(filename, "utf8").replace(
    "    function renderPickerMessage(text) {",
    "    window.auditSettings = { pickerState, loadDirectory, openPicker, closePicker };\n    function renderPickerMessage(text) {",
  );
  vm.runInNewContext(source, context, { filename });
  callbacks.DOMContentLoaded();
  return { ...context.window.auditSettings, requests, nodes, element };
}

function pickerButton(harness, field) {
  const button = harness.element();
  button.dataset = { dirTarget: field, dirScope: field };
  return button;
}

test("settings directory picker must not write a previous field's late response into the current field", async () => {
  const h = settingsHarness();
  h.nodes.get("watch_dir").value = "/watch/original";
  h.nodes.get("output_dir").value = "/output/original";
  h.openPicker(pickerButton(h, "watch_dir"));
  h.closePicker();
  h.openPicker(pickerButton(h, "output_dir"));
  h.requests[1].resolve({ path: "/output/original", entries: [] });
  await new Promise(setImmediate);
  h.requests[0].resolve({ path: "/watch/original", entries: [] });
  await new Promise(setImmediate);
  h.nodes.get("directory-picker-use").handlers.click();
  assert.equal(h.nodes.get("output_dir").value, "/output/original");
});

test("settings directory picker must disable confirmation while navigating to a new directory", async () => {
  const h = settingsHarness();
  h.pickerState.target = h.nodes.get("output_dir");
  const first = h.loadDirectory("/output/original", false);
  h.requests[0].resolve({ path: "/output/original", entries: [] });
  await first;
  const pending = h.loadDirectory("/output/new", false);
  const disabledDuringRequest = h.nodes.get("directory-picker-use").disabled;
  h.requests[1].resolve({ path: "/output/new", entries: [] });
  await pending;
  assert.equal(disabledDuringRequest, true);
});

test("a failed closed settings picker request must not launch fallback navigation in the new picker", async () => {
  const h = settingsHarness();
  h.nodes.get("watch_dir").value = "/watch/original";
  h.nodes.get("output_dir").value = "/output/current";
  h.openPicker(pickerButton(h, "watch_dir"));
  h.closePicker();
  h.openPicker(pickerButton(h, "output_dir"));
  h.requests[1].resolve({ path: "/output/current", entries: [] });
  await new Promise(setImmediate);
  h.requests[0].reject(new Error("obsolete directory unavailable"));
  await new Promise(setImmediate);
  assert.equal(h.requests.length, 2);
  assert.equal(h.pickerState.path, "/output/current");
});
