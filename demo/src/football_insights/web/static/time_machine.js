/* Vanilla JS replay: no external assets, state comes exclusively from the Python reducer. */
(() => {
  "use strict";
  const el = id => document.getElementById(id);
  const home = "Spain", away = "Argentina";
  const phases = {
    first_half: "First half", second_half: "Second half",
    extra_time: "Extra time", shootout: "Penalty shootout"
  };
  let timeline = null;
  let cursor = 0;
  let mode = "fan";
  let timer = null;
  let requestNumber = 0;
  const cache = new Map(); // Cached display text is NEVER sent into a later model request.

  function stop() {
    if (timer !== null) window.clearInterval(timer);
    timer = null;
    el("tm-play").textContent = "▶ Play";
  }

  function textNode(tag, value, className = "") {
    const node = document.createElement(tag);
    node.textContent = value; // Avoid inserting model responses or fixture text as HTML.
    if (className) node.className = className;
    return node;
  }

  function createMomentButtons() {
    const holder = el("tm-moments");
    holder.replaceChildren();
    for (const event of timeline.events.filter(e => e.highlight)) {
      const btn = textNode("button", "", "tm-moment");
      btn.type = "button";
      btn.dataset.step = String(event.step);
      const stamp = event.phase === "shootout" ? "Penalty round " + event.round : event.clock;
      btn.append(textNode("span", stamp));
      btn.append(textNode("strong", event.step <= cursor ? event.title : "Jump to moment"));
      btn.addEventListener("click", () => seek(event.step));
      holder.append(btn);
    }
  }

  function penaltyDots(label, kicks) {
    const group = textNode("div", "", "tm-kick-row");
    group.append(textNode("span", label + ": "));
    for (const made of kicks) {
      const dot = textNode("span", made ? "✓" : "×", "tm-kick-dot " + (made ? "yes" : "no"));
      dot.setAttribute("aria-label", made ? "scored" : "missed");
      group.append(dot);
    }
    return group;
  }

  function render() {
    const snapshot = timeline.snapshots[cursor];
    const score = snapshot.score;
    el("tm-score").textContent = score[home] + " : " + score[away];
    el("tm-clock").textContent = snapshot.clock + " · " + phases[snapshot.phase];
    el("tm-slider").value = String(cursor);
    el("tm-progress-text").textContent = cursor + " / " + timeline.last_step;
    el("tm-back").disabled = cursor === 0;
    el("tm-next").disabled = cursor === timeline.last_step;

    const penaltyPanel = el("tm-penalties");
    penaltyPanel.hidden = snapshot.phase !== "shootout" && cursor !== 120;
    if (!penaltyPanel.hidden) {
      el("tm-penalty-score").textContent =
        snapshot.penalties[home] + " : " + snapshot.penalties[away];
      el("tm-penalty-kicks").replaceChildren(
        penaltyDots("Spain", snapshot.kicks[home]),
        penaltyDots("Argentina", snapshot.kicks[away])
      );
    }
    const winner = el("tm-winner");
    winner.hidden = !snapshot.winner;
    winner.textContent = snapshot.winner ? "🏆 " + snapshot.winner + " wins this fictional final" : "";

    const justOccurred = timeline.events.filter(e => e.step === cursor);
    el("tm-current-event").textContent = justOccurred.length
      ? justOccurred.map(e => e.clock + " · " + e.title + " — " + e.detail).join(" ")
      : "No major recorded incident during this minute. The previous state carries forward.";

    const stats = el("tm-stats");
    stats.replaceChildren();
    const items = [
      ["Recorded shots", scoreText(snapshot.shots_recorded)],
      ["Recorded saves", scoreText(snapshot.saves_recorded)],
      ["Disallowed goals", scoreText(snapshot.disallowed_goals)],
      ["Match goals", scoreText(snapshot.score)]
    ];
    for (const [name, value] of items) {
      const box = textNode("div", "", "tm-stat");
      box.append(textNode("span", name), textNode("strong", value));
      stats.append(box);
    }

    for (const btn of el("tm-moments").querySelectorAll("button")) {
      const step = Number(btn.dataset.step);
      btn.classList.toggle("current", step === cursor);
      btn.querySelector("strong").textContent = timeline.events.find(e => e.step === step && e.highlight)?.title
        && step <= cursor ? timeline.events.find(e => e.step === step && e.highlight).title : "Jump to moment";
    }

    const past = timeline.events.filter(e => e.step <= cursor);
    const recentIds = past.slice(-5).map(e => e.id).join(", ") || "none";
    const evidence = el("tm-evidence");
    const dl = document.createElement("dl");
    for (const [label, value] of [
      ["Replay cutoff", snapshot.clock],
      ["Known event IDs", recentIds],
      ["Match score", score[home] + "–" + score[away]],
      ["Penalty score", snapshot.penalties[home] + "–" + snapshot.penalties[away]],
      ["Data provenance", "Selected synthetic what-if events; no official event feed"]
    ]) {
      dl.append(textNode("dt", label), textNode("dd", value));
    }
    evidence.replaceChildren(dl);
  }

  function scoreText(values) {
    return values[home] + " / " + values[away];
  }

  function seek(step) {
    if (!timeline) return;
    stop();
    cursor = Math.max(0, Math.min(timeline.last_step, Number(step)));
    requestNumber += 1; // Ignore a stale Foundry response if the viewer rewinds.
    el("tm-commentary").textContent = "Explain this moment to get a new, cutoff-bounded narration.";
    el("tm-commentary-source").textContent = "No commentary for this selected step.";
    render();
  }

  function setMode(nextMode) {
    mode = nextMode;
    for (const name of ["fan", "analyst"]) {
      const btn = el("tm-" + name);
      btn.classList.toggle("tm-mode-active", name === mode);
      btn.setAttribute("aria-pressed", String(name === mode));
    }
    requestNumber += 1;
    el("tm-commentary").textContent = "Choose Explain to hear the " + mode + " perspective.";
    el("tm-commentary-source").textContent = "The source events do not change between modes.";
  }

  async function explain() {
    if (!timeline) return;
    stop();
    const requestedStep = cursor;
    const requestedMode = mode;
    const id = ++requestNumber;
    const key = requestedStep + ":" + requestedMode;
    if (cache.has(key)) {
      display(cache.get(key), true);
      return;
    }
    const btn = el("tm-explain");
    btn.disabled = true;
    el("tm-commentary").textContent = "Generating evidence-bounded commentary…";
    try {
      const response = await fetch("/api/time-machine/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ step: requestedStep, mode: requestedMode })
      });
      if (!response.ok) throw new Error("commentary request was not accepted");
      const body = await response.json();
      if (body.step !== requestedStep || body.mode !== requestedMode) throw new Error("mismatched response");
      if (id !== requestNumber || cursor !== requestedStep || mode !== requestedMode) return;
      cache.set(key, body);
      display(body, false);
    } catch (_error) {
      if (id === requestNumber) {
        el("tm-commentary").textContent = "The commentary service is currently unavailable.";
        el("tm-commentary-source").textContent = "The replay and evidence remain deterministic.";
      }
    } finally {
      btn.disabled = false;
    }
  }

  function display(result, fromCache) {
    el("tm-commentary").textContent = result.commentary;
    el("tm-commentary-source").textContent = result.status === "live"
      ? "Foundry AI commentary" + (fromCache ? " · cached in this browser" : " · fresh independent request")
      : "Deterministic event summary · Foundry unavailable (not AI-generated)";
  }

  async function init() {
    try {
      const response = await fetch("/api/time-machine");
      if (!response.ok) throw new Error("The scenario could not be loaded.");
      timeline = await response.json();
      el("tm-slider").max = String(timeline.last_step);
      createMomentButtons();
      render();
    } catch (_error) {
      el("tm-error").hidden = false;
      el("tm-error").textContent = "The scenario could not be loaded. Refresh the page to retry.";
    }
  }

  el("tm-slider").addEventListener("input", event => seek(event.target.value));
  el("tm-back").addEventListener("click", () => seek(cursor - 1));
  el("tm-next").addEventListener("click", () => seek(cursor + 1));
  el("tm-play").addEventListener("click", () => {
    if (!timeline) return;
    if (timer !== null) return stop();
    if (cursor >= timeline.last_step) seek(0);
    el("tm-play").textContent = "❚❚ Pause";
    // A compressed event stream for the two-minute demonstration, not actual live ingest.
    timer = window.setInterval(() => {
      if (cursor >= timeline.last_step) return stop();
      cursor += 1;
      requestNumber += 1;
      el("tm-commentary").textContent = "Click Explain to comment on the current position.";
      el("tm-commentary-source").textContent = "No model call for this position.";
      render();
    }, 230);
  });
  el("tm-fan").addEventListener("click", () => setMode("fan"));
  el("tm-analyst").addEventListener("click", () => setMode("analyst"));
  el("tm-explain").addEventListener("click", explain);
  init();
})();
