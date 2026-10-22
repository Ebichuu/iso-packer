const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function browserHarness(script = "files") {
  const requests = [];
  const notifications = [];
  const storage = new Map();
  const element = () => ({ append() {}, appendChild() {} });
  const context = {
    URLSearchParams,
    document: { addEventListener() {}, createElement: element },
    window: {
      localStorage: {
        getItem: (key) => storage.get(key) || null,
        setItem: (key, value) => storage.set(key, value),
      },
      IsoPacker: {
        qs: (selector) => selector === "#compare-groups" ? element() : null,
        qsa: () => [],
        setText() {},
        clearNode() {},
        notify(message) { notifications.push(message); },
        fetchJson(url) {
          return new Promise((resolve, reject) => requests.push({ url, resolve, reject }));
        },
      },
    },
  };
  const filename = path.join(__dirname, `../static/js/${script}.js`);
  const exports = script === "files" ? "state, loadDirectory, loadDestinationDirectory" : "state, scan, loadPickerDirectory";
  const source = fs.readFileSync(filename, "utf8").replace(/\}\)\(\);\s*$/, `window.testBrowser = { ${exports} }; })();`);
  vm.runInNewContext(source, context, { filename });
  return { ...context.window.testBrowser, requests, notifications };
}

test("slow response from the previous root cannot replace the current directory", async () => {
  const harness = browserHarness();
  const first = harness.loadDirectory("/watch/old");
  harness.state.root = "output";
  const second = harness.loadDirectory("/output/current");
  harness.requests[1].resolve({ root: "output", path: "/output/current", root_path: "/output", entries: [] });
  await second;
  harness.requests[0].resolve({ root: "watch", path: "/watch/old", root_path: "/watch", entries: [] });
  await first;
  assert.equal(harness.state.root, "output");
  assert.equal(harness.state.path, "/output/current");
  assert.equal(harness.state.rootPath, "/output");
});

test("obsolete directory error cannot navigate the current root back to its top", async () => {
  const harness = browserHarness();
  const first = harness.loadDirectory("/watch/old");
  const second = harness.loadDirectory("/watch/current");
  harness.requests[1].resolve({ root: "watch", path: "/watch/current", root_path: "/watch", entries: [] });
  await second;
  harness.requests[0].reject(new Error("old request failed"));
  await first;
  assert.equal(harness.requests.length, 2);
  assert.equal(harness.state.path, "/watch/current");
});

test("copy destination stays on the most recently selected directory", async () => {
  const harness = browserHarness();
  const first = harness.loadDestinationDirectory("/output/old");
  const second = harness.loadDestinationDirectory("/output/current");
  harness.requests[1].resolve({ path: "/output/current", entries: [] });
  await second;
  harness.requests[0].resolve({ path: "/output/old", entries: [] });
  await first;
  assert.equal(harness.state.destinationPath, "/output/current");
});

test("navigation clears the previous file selection before the directory request finishes", async () => {
  const harness = browserHarness();
  harness.state.selected.add("/watch/old/Movie");
  const request = harness.loadDirectory("/watch/current");
  assert.equal(harness.state.selected.size, 0);
  harness.requests[0].resolve({ path: "/watch/current", entries: [] });
  await request;
});

test("media scan queues the latest changed path and discards the obsolete result", async () => {
  const harness = browserHarness("compare");
  harness.state.root = "watch";
  harness.state.path = "/watch/old";
  const first = harness.scan();
  harness.state.root = "output";
  harness.state.path = "/output/current";
  await harness.scan();
  harness.state.query = "Movie";
  await harness.scan();
  assert.equal(harness.requests.length, 1);
  harness.requests[0].resolve({ path: "/watch/old", groups: [], summary: {} });
  await first;
  assert.equal(harness.state.path, "/output/current");
  assert.equal(harness.requests.length, 2);
  const latestUrl = new URL(harness.requests[1].url, "https://packer.example");
  assert.equal(latestUrl.searchParams.get("root"), "output");
  assert.equal(latestUrl.searchParams.get("path"), "/output/current");
  assert.equal(latestUrl.searchParams.get("q"), "Movie");
  harness.requests[1].resolve({ path: "/output/current", groups: [], summary: { group_count: 2 } });
  await new Promise(setImmediate);
  assert.deepEqual(harness.notifications, []);
  assert.equal(harness.state.summary.group_count, 2);
  assert.equal(harness.state.loading, false);
});

test("media directory picker ignores out-of-order responses", async () => {
  const harness = browserHarness("compare");
  const first = harness.loadPickerDirectory("/watch/old");
  const second = harness.loadPickerDirectory("/watch/current");
  harness.requests[1].resolve({ path: "/watch/current", entries: [] });
  await second;
  harness.requests[0].resolve({ path: "/watch/old", entries: [] });
  await first;
  assert.equal(harness.state.pickerPath, "/watch/current");
});

function sharedStatusHarness(payloads = []) {
  const elements = new Map();
  const timers = [];
  const events = [];
  const makeElement = () => ({
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute(name, value) { this[name] = value; },
    removeAttribute(name) { delete this[name]; },
    prepend(node) { elements.set(node.id, node); },
  });
  for (const id of ["global-worker-badge", "workspace-worker-state", "pipeline-primary-status", "pipeline-progress-text", "pipeline-cancel-pack", "index-active-count"]) {
    elements.set(id, makeElement());
  }
  const content = makeElement();
  const context = {
    document: {
      addEventListener() {},
      querySelector: (selector) => selector === "main > div" ? content : elements.get(selector.slice(1)) || null,
      querySelectorAll: () => [],
      getElementById: (id) => elements.get(id) || null,
      createElement: makeElement,
    },
    window: { dispatchEvent: (event) => events.push(event), location: {} },
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    AbortSignal,
    fetch: async () => {
      const payload = payloads.shift();
      if (payload instanceof Error) throw payload;
      const status = payload._status || 200;
      return { status, ok: status >= 200 && status < 300, json: async () => payload };
    },
    setTimeout: (callback, delay) => timers.push({ callback, delay }),
    console: { error() {} },
  };
  const filename = path.join(__dirname, "../static/js/shared.js");
  vm.runInNewContext(fs.readFileSync(filename, "utf8"), context, { filename });
  return { api: context.window.IsoPacker, start: context.startSerializedSystemLoop, elements, timers, events };
}

function activeStatus(worker) {
  return { worker, state: { active: { source: "/watch/Movie", status: "running", progress: { phase: "packing", percent: 42 } } }, file_operations: { active_count: 1, items: [] } };
}

test("offline, recovering and outdated data cannot report a cached task as currently running", () => {
  const { api } = sharedStatusHarness();
  for (const [worker, expected] of [
    [{ alive: false, snapshot_stale: true, startup_complete: false }, "offline"],
    [{ alive: true, startup_complete: false }, "recovering"],
    [{ alive: true, startup_complete: true, snapshot_stale: true, snapshot_age_seconds: 19 }, "stale"],
  ]) {
    const status = api.normalizeStatusPayload(activeStatus(worker));
    assert.equal(status.service_health.state, expected);
    assert.equal(status.current_job, null);
    assert.equal(status.active, null);
    assert.equal(status.has_active_file_operation, false);
  }
  assert.equal(api.normalizeStatusPayload(activeStatus()).current_job.progress, 42);
  assert.equal(api.normalizeStatusPayload(activeStatus({ alive: true, startup_complete: true, snapshot_stale: false })).current_job.progress, 42);
});

test("polling shows offline status and automatically restores normal task display on recovery", async () => {
  const healthy = activeStatus({ alive: true, startup_complete: true, snapshot_stale: false });
  const harness = sharedStatusHarness([activeStatus({ alive: false }), healthy]);
  harness.start();
  await new Promise(setImmediate);
  assert.equal(harness.elements.get("global-worker-badge").innerText, "后台服务离线");
  assert.equal(harness.elements.get("pipeline-primary-status").textContent, "后台服务离线");
  assert.equal(harness.elements.get("pipeline-progress-text").textContent, "--");
  assert.equal(harness.elements.get("pipeline-cancel-pack").disabled, true);
  assert.equal(harness.events[0].detail.current_job, null);
  assert.equal(harness.timers.length, 1);
  harness.timers.shift().callback();
  await new Promise(setImmediate);
  assert.equal(harness.elements.get("global-worker-badge").innerText, "PACKING");
  assert.equal(harness.elements.get("service-health-notice").hidden, true);
  assert.equal(harness.events[1].detail.current_job.progress, 42);
  assert.equal(harness.timers[0].delay, 2000);
});

test("poll failures mark the retained data unconfirmed and keep retrying", async () => {
  const harness = sharedStatusHarness([activeStatus({ alive: true }), new Error("network down")]);
  harness.start();
  await new Promise(setImmediate);
  harness.timers.shift().callback();
  await new Promise(setImmediate);
  assert.equal(harness.elements.get("global-worker-badge").innerText, "数据更新中断");
  assert.equal(harness.elements.get("index-active-count").textContent, "--");
  assert.equal(harness.events.at(-1).detail.current_job, null);
  assert.equal(harness.events.at(-1).detail.service_health.state, "disconnected");
  assert.equal(harness.timers[0].delay, 8000);
});

test("startup 503 displays recovery information and continues polling", async () => {
  const harness = sharedStatusHarness([{ _status: 503, ok: false, worker: { alive: true, startup_complete: false } }]);
  harness.start();
  await new Promise(setImmediate);
  assert.equal(harness.elements.get("global-worker-badge").innerText, "后台服务恢复中");
  assert.equal(harness.events[0].detail.current_job, null);
  assert.equal(harness.events[0].detail.service_health.state, "recovering");
  assert.equal(harness.timers[0].delay, 8000);
});
