const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function harness() {
  const requests = [];
  const notifications = [];
  const node = (dataset = {}) => ({
    dataset, value: "", textContent: "", disabled: false, handlers: {},
    classList: { toggle() {} },
    addEventListener(name, callback) { this.handlers[name] = callback; },
    setAttribute() {}, focus() {},
  });
  const nodes = Object.fromEntries(["status", "detail", "error", "until", "refresh"].map((name) => [name, node()]));
  const buttons = ["pause", "resume", "pause-until"].map((action) => node({ uploadAction: action }));
  const root = {
    querySelector(selector) { return nodes[selector.replace("[data-upload-", "").replace("]", "")]; },
    querySelectorAll() { return buttons; }, setAttribute() {},
  };
  const context = {
    AbortSignal, Date, Event,
    document: { hidden: false, addEventListener() {} },
    window: {
      addEventListener() {}, setTimeout() {},
      IsoPacker: {
        notify(message, isError) { notifications.push({ message, isError }); },
        fetchJson(url, options) { return new Promise((resolve, reject) => requests.push({ url, options, resolve, reject })); },
      },
    },
  };
  const filename = path.join(__dirname, "../static/js/upload-controls.js");
  const source = fs.readFileSync(filename, "utf8").replace(/\}\)\(\);\s*$/, "window.testUploads = { parseWindows, pauseUntilIso, statusSummary, setupControls }; })();");
  vm.runInNewContext(source, context, { filename });
  return { ...context.window.testUploads, requests, notifications, nodes, buttons, root };
}

function control(extra = {}) {
  return { scope: "all_cd2_uploads", effective_paused: false, manual_paused: false, windows: [], reason: "none", ...extra };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

test("daily pause windows support midnight and reject invalid or empty enabled plans", () => {
  const h = harness();
  const windows = h.parseWindows("23:30-00:20\n06:10 - 06:40\n23:30-00:20", true);
  assert.equal(windows.length, 2);
  assert.equal(windows[0].start, "23:30");
  assert.equal(windows[0].end, "00:20");
  for (const value of ["", "24:00-01:00", "00:00-00:00", "01:00-", "01:00-01:99"]) {
    assert.throws(() => h.parseWindows(value, true));
  }
  assert.equal(h.parseWindows("", false).length, 0);
  assert.throws(() => h.parseWindows(Array(49).fill("01:00-02:00").join("\n"), true));
});

test("custom resume time is sent as Beijing time regardless of client timezone", () => {
  const h = harness();
  const now = Date.parse("2026-10-22T00:00:00Z");
  assert.equal(h.pauseUntilIso("2026-10-22T09:30", now), "2026-10-22T09:30:00+08:00");
  assert.throws(() => h.pauseUntilIso("2026-10-22T07:59", now));
  assert.throws(() => h.pauseUntilIso("2026-02-30T12:00", now));
  assert.throws(() => h.pauseUntilIso("", now));
});

test("an unconfirmed remote pause is never displayed as paused", () => {
  const h = harness();
  assert.match(h.statusSummary(control({ effective_paused: true, remote_pause_confirmed: false })), /暂停待确认/);
  assert.match(h.statusSummary(control({ effective_paused: true, remote_pause_confirmed: true })), /暂停已确认/);
});

test("a slow pre-action refresh cannot overwrite a confirmed manual pause", async () => {
  const h = harness();
  h.setupControls(h.root);
  h.requests[0].resolve({ upload_control: control() });
  await flush();
  h.nodes.refresh.handlers.click();
  h.buttons[0].handlers.click();
  assert.equal(h.requests.length, 3);
  assert.deepEqual(JSON.parse(h.requests[2].options.body), { action: "pause" });
  h.requests[2].resolve({ upload_control: control({ effective_paused: true, remote_pause_confirmed: true, manual_paused: true, reason: "manual" }) });
  await flush();
  h.requests[1].resolve({ upload_control: control() });
  await flush();
  assert.match(h.nodes.status.textContent, /暂停已确认/);
  assert.equal(h.buttons[0].disabled, false);
});

test("failed mutation leaves an unknown state and shows an error toast", async () => {
  const h = harness();
  h.setupControls(h.root);
  h.requests[0].resolve({ upload_control: control() });
  await flush();
  h.buttons[0].handlers.click();
  h.requests[1].reject(new Error("CD2 unavailable"));
  await flush();
  assert.match(h.nodes.status.textContent, /待确认/);
  assert.equal(h.buttons[0].disabled, true);
  assert.equal(h.notifications.at(-1).message, "CD2 unavailable");
  assert.equal(h.notifications.at(-1).isError, true);
});

test("manual resume preserves the server response when a daily window still applies", async () => {
  const h = harness();
  h.setupControls(h.root);
  h.requests[0].resolve({ upload_control: control({ effective_paused: true, manual_paused: true, reason: "manual" }) });
  await flush();
  h.buttons[1].handlers.click();
  assert.deepEqual(JSON.parse(h.requests[1].options.body), { action: "resume" });
  h.requests[1].resolve({ upload_control: control({ effective_paused: true, remote_pause_confirmed: true, reason: "schedule", schedule_enabled: true, windows: [{ start: "23:30", end: "00:20" }] }) });
  await flush();
  assert.match(h.nodes.status.textContent, /暂停已确认/);
  assert.match(h.nodes.detail.textContent, /每日暂停窗口/);
});
