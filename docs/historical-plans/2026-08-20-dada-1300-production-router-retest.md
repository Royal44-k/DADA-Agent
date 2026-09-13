# Dada 1300 Production Router Retest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Use the corrected 1,300-row corpus to measure the real production M1→M3 branch-routing accuracy with non-empty reminder and memory state, then publish an evidence-backed HTML report.

**Architecture:** Keep production code and services read-only. Create a new server-side isolated evaluation directory, use one dedicated numeric test user with one active `agent_task` and one active `agent_memory` row, and run the evaluator against the production Python package. Download results to the local workspace and render a self-contained HTML report plus the complete failure appendix.

**Tech Stack:** Python 3.10 on the small server, MySQL 8 (`dada_v3_test`), production 1.7B/9B OpenAI-compatible endpoints on V100, Python 3.12 locally for aggregation/reporting, self-contained HTML/CSS/JavaScript.

**Spec:** User request dated 2026-08-20 in this thread; corrected corpus `2026-08-17-m1-1p7b-intent-eval/sample-1300-corrected-2026-08-19.jsonl`.

## Global Constraints

- Do not modify or restart production Agent code, the 1.7B model, the 9B model, or any V100 process.
- All new server files live under `/home/number/codex-isolated-tests/intent-eval-20260820`.
- Use dedicated test user ID `2026082001`; never update or delete rows for another user.
- Reuse existing `agent_task` and `agent_memory` tables; do not create duplicate schema tables.
- The evaluator must call production M1 and production M3. No label filtering, result selection, or M3 exclusion is allowed.
- Report measured accuracy honestly. The target is at least 97%; a lower result is reported as a failed target, not hidden or relabeled.

---

### Task 1: Isolated Database Fixtures

**Files:**
- Create: `/home/number/codex-isolated-tests/intent-eval-20260820/fixture_state.py`
- Create: `/home/number/codex-isolated-tests/intent-eval-20260820/test_fixture_state.py`
- Read only: `/home/number/dada-runtime/asr-api-test-env/xiaozhi-server/dada/infra/db/task.py`
- Read only: `/home/number/dada-runtime/asr-api-test-env/xiaozhi-server/dada/infra/db/memory.py`

**Interfaces:**
- Produces: `ensure_fixtures(user_id: int) -> dict`, `verify_fixtures(user_id: int) -> dict`.
- Fixture task content: `Codex复测提醒：2026年8月21日上午9点复查路由结果`.
- Fixture memory content: `Codex复测记忆：车辆停在B2层测试车位`.

- [ ] **Step 1: Write a failing fixture test**

Assert that `verify_fixtures(2026082001)` reports at least one active task and one active memory and that repeated `ensure_fixtures` calls do not create duplicates.

- [ ] **Step 2: Run the test and verify RED**

Run: `python3 -m unittest -v test_fixture_state.py`

Expected: import failure because `fixture_state.py` does not exist.

- [ ] **Step 3: Implement idempotent fixture creation**

Use production `task_db.insert_task` and `memory_db.insert_memory`. Query by the exact fixture content before insertion; never issue a broad delete or update.

- [ ] **Step 4: Run the test and verify GREEN**

Run: `python3 -m unittest -v test_fixture_state.py`

Expected: all fixture tests pass and the second call returns the same row IDs.

- [ ] **Step 5: Record state evidence**

Write `fixture-state.json` containing test user ID, row IDs, active counts, and UTC/CST timestamp. Record file SHA-256 instead of committing because the server evaluation directory is intentionally outside a Git repository.

### Task 2: Stateful Production Router Harness

**Files:**
- Create: `/home/number/codex-isolated-tests/intent-eval-20260820/full_router_probe_stateful.py`
- Create: `/home/number/codex-isolated-tests/intent-eval-20260820/run_full_router_prod_stateful.py`
- Create: `/home/number/codex-isolated-tests/intent-eval-20260820/test_full_router_probe_stateful.py`
- Copy read-only helpers from: `/home/number/dada-runtime/asr-api-test-env/xiaozhi-server-m1-intent-eval-20260817/eval/m1_probe.py`
- Copy read-only helpers from: `/home/number/dada-runtime/asr-api-test-env/xiaozhi-server-m1-intent-eval-20260817/eval/prod_eval_bootstrap.py`

**Interfaces:**
- Consumes: corrected JSONL and `DADA_EVAL_USER_ID=2026082001`.
- Produces: checkpoint-safe result JSONL with M1 prediction, M1 confidence, M3 usage/tags, final prediction, latency, exception, and exact model-call tier.

- [ ] **Step 1: Write failing harness tests**

Assert the harness uses a numeric fixture user, does not monkeypatch `task_db.list_active_tasks`, preserves corrected sample order, and marks M3-used rows from production `m3_tags`.

- [ ] **Step 2: Run the tests and verify RED**

Run: `python3 -m unittest -v test_full_router_probe_stateful.py`

Expected: import failure because the stateful harness does not exist.

- [ ] **Step 3: Implement the minimal stateful harness**

Adapt the proven evaluator logic but remove the placeholder reminder monkeypatch. Construct `SimpleNamespace(dada_user_id=2026082001)` and import all Dada modules from the production tree only after `activate_production_path`.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `python3 -m unittest -v test_full_router_probe_stateful.py`

Expected: all tests pass.

- [ ] **Step 5: Record harness hashes**

Run: `sha256sum *.py sample-1300-corrected-2026-08-19.jsonl > artifact-hashes-before-run.sha256`.

### Task 3: State-Gate and 13-Branch Smoke Test

**Files:**
- Create: `/home/number/codex-isolated-tests/intent-eval-20260820/smoke-13-corrected.jsonl`
- Create: `/home/number/codex-isolated-tests/intent-eval-20260820/results-smoke-13.jsonl`
- Create: `/home/number/codex-isolated-tests/intent-eval-20260820/preflight.json`

**Interfaces:**
- Consumes: one corrected row per label a–m.
- Produces: preflight evidence that production services are healthy, fixtures are active, `_narrow_state(2026082001)` does not remove `reminder_modify`, `reminder_query`, or `memory_query`, and every smoke row has a valid final label.

- [ ] **Step 1: Generate the deterministic smoke sample**

Take the first row for each corrected label a–m from the corrected corpus and assert exactly 13 unique labels.

- [ ] **Step 2: Verify service health and state gate**

Check Agent ports 8010/8013, V100 endpoints 45200/45201, active fixture counts, and `_narrow_state(2026082001)` output. Save evidence to `preflight.json`.

- [ ] **Step 3: Run the real smoke test**

Run: `DADA_EVAL_USER_ID=2026082001 python3 run_full_router_prod_stateful.py --input smoke-13-corrected.jsonl --output results-smoke-13.jsonl --fail-rate-stop 1.0`.

Expected: 13/13 rows finish with valid production labels, no exceptions, and at least one recorded 1.7B call per row.

- [ ] **Step 4: Stop on infrastructure failure**

Do not start the 1,300-row run if ports, endpoints, fixture state, label validity, or model-call evidence fails.

### Task 4: Full 1300-Row Production Evaluation

**Files:**
- Create: `/home/number/codex-isolated-tests/intent-eval-20260820/results-full-1300.jsonl`
- Create: `/home/number/codex-isolated-tests/intent-eval-20260820/run.log`

**Interfaces:**
- Consumes: all 1,300 corrected rows in original sample order.
- Produces: exactly 1,300 unique result rows with no silent omissions.

- [ ] **Step 1: Start checkpoint-safe evaluation**

Run under a hidden detached process with stdout/stderr in `run.log`, checkpoint every 10 rows, progress every 50 rows, and infrastructure fail-rate threshold 1%.

- [ ] **Step 2: Monitor progress without restarting completed rows**

Read `run.log` and result row count every 30–60 seconds. The harness resumes by `sample_id` if the SSH session drops.

- [ ] **Step 3: Validate completion**

Assert 1,300 rows, 1,300 unique IDs, exact sample order, no exceptions, valid final labels, and only model tiers `1.7b`/`9b`.

- [ ] **Step 4: Record final hashes**

Write `artifact-hashes-after-run.sha256` for corpus, fixture evidence, harness, smoke results, and full results.

### Task 5: Metrics and HTML Report

**Files:**
- Create locally: `2026-08-20-dada-1300-stateful-retest/aggregate_stateful_retest.py`
- Create locally: `2026-08-20-dada-1300-stateful-retest/test_aggregate_stateful_retest.py`
- Create locally: `2026-08-20-dada-1300-stateful-retest/哒哒Agent-M1+M3状态门控修订语料1300条复测报告-2026-08-20.html`
- Create locally: `2026-08-20-dada-1300-stateful-retest/失败测试集-2026-08-20.html`

**Interfaces:**
- Consumes: corrected corpus, `preflight.json`, fixture state, smoke results, full results, and hashes.
- Produces: overall/per-branch accuracy; confusion matrix; M1-direct/M3-entry/M3-correction/M3-worsening counts; 1.7B-versus-9B final error attribution; latency percentiles; full failure appendix; explicit pass/fail against 97% target.

- [ ] **Step 1: Write failing aggregation tests**

Use a literal synthetic fixture to assert accuracy, branch metrics, M3 attribution, percentile calculation, and target verdict.

- [ ] **Step 2: Run tests and verify RED**

Run: bundled Python `-m unittest -v test_aggregate_stateful_retest.py`.

Expected: import failure because aggregator does not exist.

- [ ] **Step 3: Implement aggregation and self-contained report rendering**

Use no external CDN. The visual direction is a diagnostic control-room ledger: deep navy background, signal cyan for verified state, amber for M3 intervention, red only for remaining errors, tabular numerals, a per-branch rail, confusion matrix, and searchable failure table.

- [ ] **Step 4: Run tests and verify GREEN**

Run both aggregation unit tests and independent HTML/JSONL structural checks.

- [ ] **Step 5: Verify the report claim**

The headline accuracy, numerator/denominator, target verdict, and every failure row must be recomputed from `results-full-1300.jsonl`; no manually entered metric is allowed.

