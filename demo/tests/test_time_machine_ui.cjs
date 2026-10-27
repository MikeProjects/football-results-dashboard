"use strict";

// Dependency-free browser-script regressions: node --test tests/test_time_machine_ui.cjs
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(
  path.join(__dirname, "..", "src", "football_insights", "web", "static", "time_machine.js"),
  "utf8"
);

class Element {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.rawText = "";
    this.dataset = {};
    this.handlers = {};
    this.attributes = {};
    this.classList = { toggle() {} };
    this.hidden = false;
    this.disabled = false;
  }

  set textContent(value) {
    this.rawText = String(value);
    this.children = [];
  }

  get textContent() {
    return this.rawText + this.children.map(child => child.textContent).join("");
  }

  append(...children) { this.children.push(...children); }
  replaceChildren(...children) {
    this.rawText = "";
    this.children = children;
  }
  addEventListener(type, callback) { this.handlers[type] = callback; }
  setAttribute(name, value) { this.attributes[name] = value; }
  querySelectorAll(tag) { return this.children.filter(child => child.tag === tag); }
  querySelector(tag) { return this.children.find(child => child.tag === tag) || null; }
  dispatch(type, event) { return this.handlers[type](event); }
}

function snapshot(step) {
  const zero = { Spain: 0, Argentina: 0 };
  return {
    clock: step > 120 ? `Penalty kick ${step - 120}/10` : `${step}′`,
    phase: step > 120 ? "shootout" : step > 93 ? "extra_time" :
      step > 45 ? "second_half" : "first_half",
    score: zero, penalties: zero, shots_recorded: zero, saves_recorded: zero,
    disallowed_goals: zero, kicks: { Spain: [], Argentina: [] }, winner: null
  };
}

async function mount(responses) {
  const nodes = new Map();
  const get = name => {
    if (!nodes.has(name)) nodes.set(name, new Element());
    return nodes.get(name);
  };
  const calls = [];
  const document = {
    getElementById: get,
    createElement: tag => new Element(tag)
  };
  const timeline = {
    last_step: 130,
    snapshots: Array.from({ length: 131 }, (_, i) => snapshot(i)),
    events: [
      { id: "E007", step: 45, phase: "first_half", clock: "45′",
        title: "Half-time", detail: "Still level", highlight: true }
    ]
  };
  async function fetch(url, options) {
    if (url === "/api/time-machine") return { ok: true, json: async () => timeline };
    assert.equal(url, "/api/time-machine/explain");
    const args = JSON.parse(options.body);
    calls.push(args);
    const reply = responses.shift();
    assert.ok(reply, "Unexpected extra request");
    return { ok: true, json: async () => ({ ...reply, ...args }) };
  }
  vm.runInNewContext(script, {
    document, fetch, window: { clearInterval() {}, setInterval() { return 1; } }
  });
  await new Promise(resolve => setImmediate(resolve)); // let the async init fetch render
  return { get, calls, seek: step => get("tm-slider").dispatch("input", {
    target: { value: String(step) }
  }) };
}

test("failed commentary is retried, live output alone is cached", async () => {
  const ui = await mount([
    { status: "unavailable", commentary: "Temporary fallback" },
    { status: "live", commentary: "A fresh commentary after recovery" },
    { status: "live", commentary: "Analyst perspective" }
  ]);
  ui.seek(106);
  await ui.get("tm-explain").dispatch("click");
  assert.match(ui.get("tm-commentary-source").textContent, /not AI-generated/);
  assert.equal(ui.calls.length, 1);

  await ui.get("tm-explain").dispatch("click");
  assert.equal(ui.calls.length, 2, "Foundry must be retried after failure");
  assert.equal(ui.get("tm-commentary").textContent, "A fresh commentary after recovery");
  assert.match(ui.get("tm-commentary-source").textContent, /fresh independent request/);

  await ui.get("tm-explain").dispatch("click");
  assert.equal(ui.calls.length, 2, "successful live narration should be cached");
  assert.match(ui.get("tm-commentary-source").textContent, /cached in this browser/);

  ui.get("tm-analyst").dispatch("click");
  await ui.get("tm-explain").dispatch("click");
  assert.equal(ui.calls.length, 3, "cache must be scoped to audience mode");
  assert.equal(ui.calls[2].mode, "analyst");
});

test("narrow-screen stylesheet places the score above both teams", () => {
  const css = fs.readFileSync(
    path.join(__dirname, "..", "src", "football_insights", "web", "static", "time_machine.css"),
    "utf8"
  );
  assert.match(css, /@media\s*\(max-width:420px\)/);
  assert.match(css, /grid-template-columns:repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(css, /grid-template-areas:"score score" "home away"/);
  assert.match(css, /\.tm-score-center\s*\{\s*grid-area:score/);
});
