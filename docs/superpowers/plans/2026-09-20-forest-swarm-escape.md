# Forest Swarm Escape Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic 100-drone simulation that starts inside the existing forest, escapes through five decentralized routes, and assembles into a heart outside the forest with zero central flight commands.

**Architecture:** A focused `forest-swarm-engine.js` module owns forest occupancy, safe start generation, A* routes, waypoint state, obstacle safety and combined metrics. It composes the existing `SwarmSimulation` for local neighbor observations, ellipsoid separation and failure modes. A separate view renders the combined scene, and a validator independently recomputes obstacle and inter-drone safety from coordinates.

**Tech Stack:** JavaScript ES modules, Node.js built-in test runner, Three.js, existing deterministic forest and swarm modules.

**Spec:** `docs/superpowers/specs/2026-09-20-forest-swarm-escape-design.md`

## Global Constraints

- The scenario contains exactly 100 drones.
- All starting points are inside `x ∈ [-12, 12]`, `y ∈ [-9, 9]` at 1.8 m altitude and outside inflated obstacle boxes.
- Five east-side exits are used; normal flight has `centralMessages === 0`.
- Neighbor avoidance consumes timestamped local observations; no hidden true-state steering is added.
- Raw obstacle contacts are counted before the idealized final obstacle constraint corrects a position.
- The same seed produces identical starts, routes and results.
- No GPL or unlicensed third-party source is copied.
- Existing 20 Node and 39 Python tests remain green.

## Review Focus

- A start or A* segment exactly touching an inflated obstacle boundary must be rejected.
- An impossible start set or unreachable exit must throw instead of silently lowering clearance.
- A diagonal A* step must not cut through the corner of two blocked cells.
- A drone in `localization-hold` or `landed` mode must not advance a waypoint.
- Independent validation must read coordinates and obstacle geometry rather than trusting engine safety metrics.

---

### Task 1: Deterministic Forest Mission Planner

**Files:**
- Create: `docs/live/forest-swarm-engine.js`
- Create: `tests/forest-swarm.test.mjs`

**Interfaces:**
- Consumes: `createForestWorld(seed)`, `createFormationTargets('heart', 100)`.
- Produces: `pointInsideInflatedBox(point, box, horizontalMargin, verticalMargin) -> boolean`.
- Produces: `buildOccupancyGrid(world, options) -> OccupancyGrid`.
- Produces: `findForestStarts(world, options) -> Array<[x,y,z]>`.
- Produces: `planGridPath(grid, start, goal) -> Array<[x,y,z]>`.
- Produces: `createForestEscapeMission(world, options) -> {starts, exits, routes, rallyTargets}`.

- [ ] **Step 1: Write failing geometry and start tests**

Add literal assertions that an inside point and exact boundary point are blocked, a point 1 mm beyond the inflated boundary is free, and `findForestStarts` returns exactly 100 deterministic points with pairwise horizontal spacing at least 0.82 m.

```js
test('forest starts are deterministic, separated, and outside inflated obstacles', () => {
  const world = createForestWorld(42);
  const a = findForestStarts(world, { count: 100, altitude: 1.8, spacing: 0.82, clearance: 0.38 });
  const b = findForestStarts(createForestWorld(42), { count: 100, altitude: 1.8, spacing: 0.82, clearance: 0.38 });
  assert.deepEqual(a, b);
  assert.equal(a.length, 100);
  for (const point of a) assert.ok(world.boxes.every((box) => !pointInsideInflatedBox(point, box, 0.38, 0.2)));
});
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `node --test --test-name-pattern="forest starts|inflated obstacle" tests/forest-swarm.test.mjs`

Expected: FAIL because the planner module and exports do not exist.

- [ ] **Step 3: Implement obstacle predicates, occupancy and starts**

Use closed interval comparisons for inflated boxes. Scan a fixed 0.41 m candidate lattice in west-to-east order, retain free points whose distance from every selected point is at least 0.82 m, and throw `RangeError('forest cannot fit requested safe starts')` if fewer than `count` points are found.

- [ ] **Step 4: Write failing A* and five-exit tests**

Create a small hand-built grid in which the shortest path would cut a blocked diagonal corner, assert every returned segment stays in free cells, then assert the 100-drone mission uses all five exit indices and every route ends at its assigned heart target outside `x = 12.5`.

- [ ] **Step 5: Run the tests and verify RED**

Run: `node --test --test-name-pattern="A.star|five exits|escape mission" tests/forest-swarm.test.mjs`

Expected: FAIL because `planGridPath` and `createForestEscapeMission` do not exist.

- [ ] **Step 6: Implement deterministic A* and mission construction**

Use eight-connected A* with Euclidean heuristic and stable tie-breaking `(f, h, y, x)`. A diagonal is legal only when both adjacent cardinal cells are free. Assign starts to the least-loaded nearby exit, simplify only collinear cells, append an outside transition point, and distance-match shifted heart targets centered at x=18.

- [ ] **Step 7: Verify Task 1**

Run: `node --test tests/forest-swarm.test.mjs tests/swarm.test.mjs tests/forest.test.mjs`

Expected: planner tests and all existing Node tests pass.

### Task 2: ForestSwarmSimulation and Obstacle Safety

**Files:**
- Modify: `docs/live/forest-swarm-engine.js`
- Modify: `tests/forest-swarm.test.mjs`

**Interfaces:**
- Consumes Task 1 `createForestEscapeMission`.
- Produces: `class ForestSwarmSimulation` with `step(dt)`, `metrics()`, `injectFailure(id, type)`, `clearFailure(id)` and `drones` access.
- Metrics add `forestContacts`, `obstacleInterventions`, `escaped`, `rallied`, `minimumObstacleClearance`, and `unresolvedObstacleViolations`.

- [ ] **Step 1: Write the failing waypoint-state test**

Construct a two-drone mission with literal three-point routes. Assert each drone advances only its own waypoint after entering the tolerance, changes from `escaping` to `rallying` only after crossing x=12.5, and leaves `centralMessages` at zero.

- [ ] **Step 2: Run the test and verify RED**

Run: `node --test --test-name-pattern="waypoint state" tests/forest-swarm.test.mjs`

Expected: FAIL because `ForestSwarmSimulation` does not exist.

- [ ] **Step 3: Implement composition and per-drone route state**

Create the underlying `SwarmSimulation` with mission starts, replace formation commands with each drone's current route waypoint, advance indices from onboard position only, and delegate failure APIs without generating central messages.

- [ ] **Step 4: Write failing raw-contact and obstacle-constraint tests**

Move one drone through a literal trunk box during a step. Assert raw `forestContacts` increments before correction, a near-but-not-contacting drone is projected outside the inflated box, and an independent coordinate check sees no unresolved final penetration.

- [ ] **Step 5: Run the tests and verify RED**

Run: `node --test --test-name-pattern="raw forest contact|obstacle constraint" tests/forest-swarm.test.mjs`

Expected: FAIL because obstacle metrics and projection are absent.

- [ ] **Step 6: Implement obstacle lookahead and final constraint**

Use the drone's current velocity and local route segment to detect near obstacles, bias the next command target toward the closest free grid cell, then apply an iterative inflated-AABB projection after dynamics. Count physical-box contact from the pre-projection position and recompute final obstacle clearance from geometry.

- [ ] **Step 7: Verify Task 2**

Run: `node --test tests/forest-swarm.test.mjs tests/swarm.test.mjs tests/forest.test.mjs`

Expected: all Node tests pass.

### Task 3: 100-Drone End-to-End Escape and Failure Resilience

**Files:**
- Modify: `docs/live/forest-swarm-engine.js`
- Modify: `tests/forest-swarm.test.mjs`

**Interfaces:**
- Consumes Task 2 `ForestSwarmSimulation`.
- Produces stable end-to-end behavior under nominal and adverse conditions.

- [ ] **Step 1: Write the failing nominal end-to-end test**

Run 100 drones for 120 simulated seconds at 25 ms control steps. Independently inspect every drone/box and drone/drone pair after every step. Assert zero raw obstacle contact, zero inter-drone contact, zero unresolved violations, `escaped >= 95`, `rallied >= 85`, and `centralMessages === 0`.

- [ ] **Step 2: Run the test and verify RED**

Run: `node --test --test-name-pattern="100 drones escape" tests/forest-swarm.test.mjs`

Expected: FAIL on at least one escape or rally threshold before tuning.

- [ ] **Step 3: Tune routes and local execution without lowering safety margins**

Adjust grid resolution, exit balancing, waypoint tolerance and outside transition spacing. Do not reduce the 0.72/1.25 m ellipsoid, obstacle clearance or success thresholds.

- [ ] **Step 4: Write the failing adverse and failure test**

Run with wind 0.35, P2P loss 15%, observation dropout 12% and observation noise 0.025. At 12 seconds inject link loss, localization loss and low battery into three separated drones. Assert zero contact, no central messages, one stable landing, zero localization-hold drift, and at least 92 escaped / 80 rallied among the remaining mission-capable drones.

- [ ] **Step 5: Run the test and verify RED**

Run: `node --test --test-name-pattern="forest failure resilience" tests/forest-swarm.test.mjs`

Expected: FAIL until failure-aware route metrics exclude only held/landed vehicles from the capable denominator.

- [ ] **Step 6: Implement failure-aware metrics and deterministic recovery behavior**

Keep failed drones as fixed local obstacles, allow link-loss drones to continue their routes, and report `missionCapable`, `escapedCapable`, and `ralliedCapable` without deleting failed vehicles from collision checks.

- [ ] **Step 7: Verify Task 3**

Run: `node --test tests/forest-swarm.test.mjs tests/swarm.test.mjs tests/forest.test.mjs`

Expected: all Node tests pass.

### Task 4: Combined Forest Page and Independent Batch Report

**Files:**
- Create: `docs/live/forest-swarm-view.js`
- Create: `docs/forest-swarm.html`
- Modify: `docs/swarm.html`
- Create: `tools/validate_forest_swarm.mjs`
- Create by validator: `results/forest-swarm/summary.json`
- Create by validator: `results/forest-swarm/100机森林逃生与集合验证报告.md`

**Interfaces:**
- Consumes Task 3 `ForestSwarmSimulation` and existing `createForest(scene, world)`.
- Produces a browser-visible combined scenario and machine-readable independent acceptance report.

- [ ] **Step 1: Build the combined page**

Render the forest, extended east ground, boundary line, five exit gates, shifted heart targets and instanced drones. Add metrics for escaped, rallied, forest contacts, inter-drone contacts, central messages, minimum ellipsoid factor and obstacle interventions. Add pause/reset and the three fault-injection controls.

- [ ] **Step 2: Link the existing swarm page**

Add a visible `进入100机森林逃生` link from `docs/swarm.html` to `docs/forest-swarm.html`.

- [ ] **Step 3: Implement independent validation**

The validator runs nominal and adverse scenarios, recomputes every AABB penetration and ellipsoid factor from coordinates each step, tracks hold drift and post-landing height, writes JSON and Markdown, and exits nonzero when any criterion fails.

- [ ] **Step 4: Run the validator**

Run: `node tools/validate_forest_swarm.mjs`

Expected: top-level `accepted: true`; nominal `escaped >= 95`, `rallied >= 85`; adverse capable thresholds pass; all contacts and unresolved violations are zero.

- [ ] **Step 5: Run the complete automated suite**

Run: `node --test tests/forest-swarm.test.mjs tests/swarm.test.mjs tests/forest.test.mjs` and `.venv/Scripts/python.exe -m pytest -q`.

Expected: all Node tests and all 39 Python tests pass.

- [ ] **Step 6: Verify the live page**

Open `http://127.0.0.1:8766/forest-swarm.html`, verify 100 drones and five exits render, observe escape count increasing, inject each failure, and confirm the page keeps `centralMessages` at zero with no console errors.
