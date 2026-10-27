# Football Time Machine — synthetic match showcase

> **Fictional alternate history.** This is NOT the actual 2026 World Cup final
> result or an official FIFA/Opta event feed. A Spain–Argentina final inspired
> this *original illustrative script*: extra time finishes 0–0 and Argentina
> wins the fictional shootout 4–3.

## What this adds

The existing [Football insights](../README.md) historical analytics is retained,
including its seven tool-backed cards. This separately scoped hackathon feature
demonstrates a compact `synthetic events → deterministic match state → evidence
→ Microsoft Foundry commentary → two audience modes` pipeline.

Open **/time-machine** in the existing web app. The replay works without Azure;
click **Explain this moment** with `AI_NARRATIVE_MODE=live` and the existing
Foundry deployment configured to request a real model-generated commentary.
When the model is off or unreachable, the UI explicitly says its text is a
deterministic event summary rather than an AI response.

## Minimal architecture

- `demo/src/football_insights/showcase.py`: one **fixed**, 30-event
  original scenario; a pure reducer rebuilds the match state at any cursor.
  Minutes 0–120 have snapshots. Ten further cursor positions represent the ten
  shootout attempts. Goals during a shootout are *not* match goals.
- `demo/src/football_insights/showcase_commentary.py`: derives a fresh,
  evidence-limited model input each time. It does **not** pass earlier model
  responses, `conversation`, or `previous_response_id`, and requests
  `store=False`. Model inputs are reconstructed on the **private insights
  service**, never accepted as facts from browsers.
- `demo/src/football_insights/insights/app.py`:
  `POST /v1/time-machine/explain` for a bounded cursor and audience mode.
- `demo/src/football_insights/web/app.py`: serves `/time-machine`,
  `/api/time-machine` and `/api/time-machine/explain`. The original routes,
  security middleware and historical tools remain.
- `demo/src/football_insights/web/templates/time_machine.html` and
  `static/time_machine.{js,css}`: one page, local-only assets, keyboard-accessible
  controls, seek/rewind, highlights, a score board and explain/evidence panel.
  A monotonically increasing request ID discards late replies from old cursors.

The visible event statistics refer to **selected fictional records**, not
complete game totals; every stat identifies Spain and Argentina separately.
The clock labels 45′ as half-time and numbers each penalty kick in the current
event. Rewinding before the shootout hides the outcome and clears previously
rendered penalty kicks, while the evidence panel still shows a cutoff-specific
penalty score. A scenario-specific footer explains that this fictional replay
does not use the historical datasets from the main dashboard.
The app cannot infer tactical causation, mentality, full-match possession,
full passing counts, or precise time-of-day or second precision from this script.

## Design decisions for judges

1. **Separation of facts and language.** Every match state, penalty and evidence
   ID is computed in ordinary Python; the LLM cannot change the score.
2. **No future leakage in model inputs.** `evidence_at(step)` contains only
   events at or before the selected replay step. Rewinding builds a new
   evidence package, even if the prior request happened after the shootout.
3. **One model, two voices.** Fan and Analyst use the same trusted facts but
   different style instructions. No additional trained model or deployment.
4. **Stateless API calls.** A fresh `responses.create` call is made only on
   demand. Earlier commentaries are never provided as context; an optional
   client-side display cache is also never returned to the model.
5. **Honest degradation and audience-ready language.** The model is asked
   to describe football naturally, without exposing internal evidence keys,
   event IDs, or developer terms. A small output check rejects those markers,
   as well as premature match results; on rejection or Foundry failure, the
   deterministic summary is clearly labeled non-AI. This is a practical
   safeguard, **not a proof that every natural-language assertion is grounded**.
6. **Constrained original sample.** No copyrighted event feed, match video,
   raw Kaggle dataset or licensed Opta/WhoScored data is copied here.

## Focused tests

From the repository's `demo` directory after installing its development
dependencies:

```bash
python -m pytest -q tests/test_showcase.py tests/test_showcase_web.py
python -m ruff check src tests
```

The existing GitHub CI also runs `mypy`, the full non-live pytest suite,
and the no-data-history guard. These tests do not make billable Azure requests.

## Remaining validation before submitting

- Confirm the web and internal insights images containing this branch are
  running and `/time-machine` works end to end. Check minute 45, minute 106,
  penalty kick 10/10 at step 130, and rewind 130 → 45. Verify the late
  penalty score and winner are no longer visible after rewind.
- Enable the *already configured* Foundry deployment and verify one **live**
  Fan and Analyst response. Never label offline fallback as a live model call.
- Record a public video shorter than two minutes and cite upstream Reactor
  baseline, original hackathon enhancements, and any third-party data sources.
- No automatic Azure deployment or new cloud resources are triggered by this
  source change. Monitor running ACA/Foundry costs separately.

### Deferred improvements

A deterministic `Story So Far` digest, commentary history scoped to a replay
session, narrative branching after rewind, and probabilistic scenario generation
are deliberately outside the first MVP.
