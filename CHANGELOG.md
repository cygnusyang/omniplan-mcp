# Changelog

All notable changes to `mcp-omniplan-jtr`. Versioning follows
[Semantic Versioning](https://semver.org/).

The project started as a fork of
[`xiahan4956/omniplan-mcp`](https://github.com/xiahan4956/omniplan-mcp) at
commit `b235768` (their `v0.1.0`). After Tier 0/1 work landed, ~86% of LOC
was new and the JXA bridge in `src/omniplan_mcp/jxa.py` was the only
significant remaining upstream code (kept verbatim under MIT). At v0.4.0 the
distribution was renamed to `mcp-omniplan-jtr` and the project posture
changed from "fork" to "build inspired by". See `LICENSE` for attribution.

## [Unreleased]

### Fixed
- **Timezone-independent date round-trips.** The v0.4.1/v0.4.2 fix switched
  date reads to `getUTC*` getters; that held in the Eastern timezone it was
  written for, but east of UTC (observed at UTC+8) it read OmniPlan's
  local-midnight dates one day early — writing `2026-09-19` read back
  `2026-09-18`.
  - Read side: `fmtDate` / `fmt` now use **local** getters everywhere
    (`documents.py`, `tasks.py`).
  - Write side: all settable date writes (`manual_start_date`, the four
    constraint dates, project `actual.startDate`) now build a local-midnight
    Date via a new `dateFromISO` helper instead of `new Date("YYYY-MM-DD")`,
    which parses as UTC midnight and could store the previous day west of
    UTC. `dateFromISO` also rejects impossible calendar dates (e.g.
    `2026-02-31`) instead of letting JS normalize them.
    `manual_end_date` is removed from writes — see Changed below.
  - `query_tasks` date filters compare local-midnight instants on both sides,
    so "ending before DATE" is now a true calendar-date boundary in any
    timezone.

### Changed
- **`manual_end_date` is now rejected on `create_task`, `create_tasks`, and
  `update_task`.** Probed live 2026-09-17: OmniPlan derives a task's end as
  `manual_start_date + effort` and ignores writes to `task.manualEndDate` in
  every scheduling configuration, so accepting the parameter was a silent
  no-op. Callers now get a `ValueError` steering them to
  `manual_start_date` + `effort_seconds`. `manual_end_date` remains in tool
  output (read side is unaffected).

### Tests
- `tests/conftest.py` `requires_omniplan` gate no longer requires the
  sandbox container at `~/Library/Containers/com.omnigroup.OmniPlan4`.
  Non-sandbox installs (direct `.app` download) run without it and were
  silently skipping every integration test. The gate now probes for a
  responding front document via `osascript` (`Application("OmniPlan")
  .documents().length`).

## [0.4.5] - 2026-05-07

### Fixed
- **Decimal helper backward-compatibility.** v0.4.4's
  `decimalToFloat` swapped the regex parser for a direct
  `parseFloat(d.toString())`. That works on OmniPlan 4.10.3+ where
  `d.toString()` returns the numeric form (Verified). On 4.10.2 it
  was untested whether `toString()` returns numeric or the
  `[object Decimal: 100]` wrapper form — Inferred to work, not
  Verified. To eliminate the regression risk, the helper now tries
  the numeric parse first, and falls back to the wrapper-form regex
  if the toString output isn't a numeric literal. Works on both 4.10.2
  and 4.10.3 regardless of which shape toString returns.

- **`move_task` / `move_resource` raise a clear error on old OmniPlan.**
  v0.4.4 surfaced `TypeError: task.move is not a function` (raw
  omniJS error) when called against OmniPlan 4.10.2. v0.4.5 checks
  `typeof task.move !== 'function'` BEFORE the call and throws a
  helpful message naming the version requirement (4.10.3+, build
  v232.5.7) with a link to the staging URL where test builds live.

### CHANGELOG correction
- The v0.4.4 entry claimed the Decimal change "works on 4.10.2
  unchanged" — that was Inferred, not Verified, and stated as fact.
  Per the Verified/Observed/Inferred protocol it should have been
  marked. The v0.4.5 fix removes the risk regardless.

### Notes
- Recommended upgrade path: `uv tool upgrade mcp-omniplan-jtr` (or
  `pip install --upgrade mcp-omniplan-jtr`). v0.4.4 stays on PyPI but
  is superseded; the new tools' error messages on 4.10.2 are
  noticeably less confusing in v0.4.5.

## [0.4.4] - 2026-05-07

### Added
- **`move_task(task_id, new_parent_id?, index?)`** — reparent a task
  without changing its uniqueID. Wraps the new omniJS
  `task.move(newParent, index)` shipped in OmniPlan 4.10.3 (test build
  v232.5.9, 2026-05-06) per OmniGroup support ticket OG #3107771.
  Cycle/self-move guards. `new_parent_id` defaults to root.
- **`move_resource(resource_id, new_parent_id?, index?)`** — same shape
  as `move_task`, wraps `resource.move(newParent, index)` (also new in
  4.10.3). Resources have a `members` tree rather than `subtasks`;
  signature is otherwise identical.

### Changed
- **`decimalToFloat` simplified** in `src/omniplan_mcp/resources.py`.
  The previous regex `String(d).match(/Decimal:\s*…/)` was a workaround
  for `String(Decimal)` returning the wrapper form
  `"[object Decimal: 100]"`. Per Ken Case @ Omni (OG #3107771,
  2026-05-06), `d.toString()` returns the numeric form directly. The
  regex is gone; we now do `parseFloat(d.toString())`. All existing
  resource integration tests still pass.

### Tests
- 8 new integration tests in `tests/integration/test_move_task.py`
  replace the `xfail(strict=True)` sentinel: reparent + uniqueID
  preserved, default-end index, explicit index, move-to-root,
  dependency survival, self-move rejected, descendant-cycle rejected,
  unknown-id rejected.
- 8 new integration tests in `tests/integration/test_move_resource.py`
  mirror the move_task suite plus an assignment-survival check
  (assignments on a moved resource survive because uniqueID is
  preserved).

### Compatibility
- Requires OmniPlan 4.10.3+ for the move tools. The two new tools
  raise an omniJS-side error on older builds (`task.move is not a
  function` / `resource.move is not a function`); other tools and the
  Decimal change work on 4.10.2 unchanged.

### Notes
- See `dev-docs/beta-v232.5.9-probe-results.md` for the empirical
  probe report that drove this release.

## [0.4.2] - 2026-05-02

### Fixed
- `tasks.py` `fmtDate()` now uses `getUTC*` like `documents.py` did in
  v0.4.1. Symptom: writing `2027-04-12` as a constraint date or
  `manual_start_date` read back as `2027-04-11` in Eastern timezone.
  Caught by manual MCP smoke run; same root cause as the v0.4.1
  documents.py fix. Now applies to every date field on `task` /
  `get_task` output (manual_start_date, manual_end_date,
  start_no_earlier_than, start_no_later_than, end_no_earlier_than,
  end_no_later_than, plus computed start_date / end_date).

### Tests
- `test_constraints.py` — four constraint-date round-trip tests now
  assert against the input string (`TARGET_DATE`) instead of
  cross-comparing two skewed values. The earlier
  `assert constraint == manual` passed even when both were shifted
  by one day. Plus a new `test_manual_start_date_persists_without_timezone_skew`
  pins the manual setter directly. These would all have caught
  v0.4.1's gap on first run; the gap survived because the asserts
  were too weak.

## [0.4.1] - 2026-05-02

### Fixed
- `get_project_info` and any other date round-trip path through
  `documents.py` now uses `getUTCFullYear/Month/Date` instead of
  local-time getters. Writing an ISO date string parses as UTC
  midnight, so reading via local-time getters introduced a one-day
  skew west of UTC. The pre-existing `test_update_project_start_date_persists`
  flake was the visible symptom; the bug applied to every date read
  on a timezone-shifted host.
- `tests/e2e/test_oplx_xml_cross_check.py` and
  `tests/workflow/test_save_close_reopen.py` `_front_document_path()`
  helper: tries `path()` first, falls back to `file()` if path()
  raises `Can't convert types (-1700)`. The error happens with some
  saved documents on macOS 15+ where the SDEF coercion of NSURL to
  POSIX path fails. The production `get_project_info` already wraps
  in try/catch; the test helpers were missing that defensive cast.

### Added
- Homebrew tap formula at `johntrandall/tap/mcp-omniplan-jtr` —
  resource-bundled Python venv with all 36 transitive PyPI deps. Three
  install paths now documented in README: brew tap / uv tool / pip.

## [0.4.0] - 2026-05-02

### Changed (BREAKING)
- **Renamed PyPI distribution from `omniplan-mcp` to `mcp-omniplan-jtr`.**
  The CLI command renamed from `omniplan-mcp` to `mcp-omniplan-jtr`; users
  re-registering with Claude Code or Claude Desktop must update their MCP
  config. The Python import name (`omniplan_mcp`) is unchanged — visible
  only to developers extending the package.
- **Lineage reframed from "fork" to "inspired by"** in the README, since
  ~86% of current LOC is new and the project's direction is now
  independent from upstream. Original author still credited in `LICENSE`.
- **Removed `upstream` git remote** and dropped fork-style PR-upstreaming
  workflow. Subsequent feature work is committed directly to `main`.
- **Added `LICENSE`** (MIT) with dual copyright — John Randall for the
  current project and xiahan4956 for the original `jxa.py` bridge that
  remains in the codebase.
- **Project metadata** (`description`, `license`, `authors`, `classifiers`,
  URLs) populated in `pyproject.toml` for PyPI publication.

### Docs
- **README rewritten as consumer-facing** — install instructions, what-it-
  does table, example prompts. Geekier content moved to
  `dev-docs/README-DEV.md`.
- **`dev-docs/README-DEV.md` added** — architecture, tool-extension recipe,
  vendor-docs reference, editable-install workflow, lineage notes.
- **Redacted private-host paths and project-specific filenames from
  `dev-docs/ROADMAP.md`** — local vendor-docs mirror references replaced
  with the canonical public URL at <https://omni-automation.com/omniplan/>.

## [0.4.3] - 2026-05-02

### Fixed
- `query_tasks` filter clauses are now parenthesized before joining with
  `&&`. The keyword filter uses `||` internally; without explicit parens,
  JS's `&&`-binds-tighter-than-`||` precedence let any title-match
  short-circuit subsequent `task_type` / `completed` / `due_*` filters.
  Symptom: `query_tasks(keyword="X", task_type="milestone")` returned
  every task whose title matched X regardless of type. Caught by the
  new `tests/integration/test_basic_endpoints.py` suite.
- `query_tasks` `task_type` filter normalization now matches what
  `taskToObj` produces. Previously the filter compared
  `String(t.type)` (e.g. `[object TaskType: TaskType.milestone]`)
  to the bare task_type string, which never matched. Filter now
  applies the same regex chain `taskToObj` uses for output.

### Tests
- New `tests/integration/test_basic_endpoints.py` covers four endpoints
  the verifier flagged as untested: `list_documents`, `query_tasks`,
  `get_task`, `delete_task`. Round-trip tests for keyword/completed/
  task_type filters, error path on unknown task_id, full-shape
  assertion for `get_task`, and a delete-then-confirm-gone for
  `delete_task`.
- `tests/integration/test_resources.py` `test_create_resource_round_trip`
  now re-reads via `list_resources` to confirm the create persisted
  rather than just echoing the input.
- `tests/e2e/test_oplx_xml_cross_check.py` `test_dependency_landing_in_actual_xml`
  now asserts the `prerequisite-task` `idref` matches the actual
  predecessor task's id (previously only checked existence).
- `tests/workflow/test_create_link_assign_save.py` skip gate fixed:
  the previous probe used `run_omnijs("return document.fileType;")`
  and compared the awaited string to `None`, which never fired the
  skip on Untitled documents. Now uses the same JXA-SDEF path-or-file
  probe as the e2e tests.

### Docs
- `README.md` tool count corrected from 19 to 20 (was stale since
  `list_assignments` shipped without a count update).
- `README.md` install snippet for the brew tap re-described:
  Python deps are bundled in an isolated venv, only `python@3.13`
  comes from brew. Previous wording said "deps via brew" which was
  misleading.
- `README.md` Limitations expanded: `actual.currency` ambiguity and
  `Decimal.toString` regex workaround now surfaced (previously only
  in `dev-docs/omnijs-persistence-gaps.md`).
- `CHANGELOG.md` `[Unreleased]` block consolidated into the v0.4.0
  section since those features shipped at v0.4.0; pre-existing
  v0.3.0 "BLOCKED" claims forward-pointed to the v0.4.0 retraction.

## [0.4.0] (continued — Tier 1 work shipped at the v0.4.0 cut)

The Tier 1 features below shipped at v0.4.0 alongside the rename. They
were tracked under "Unreleased" prior to the 2026-05-02 cut and merged
into this section after the verifier-pass review.

### Added
- `update_task` accepts `start_no_earlier_than`, `start_no_later_than`,
  `end_no_earlier_than`, and `end_no_later_than` (ISO date strings, or
  empty string to clear). `get_task` surfaces them under the same names.
  Maps to the documented omniJS `task.startNoEarlierThanDate` /
  `startNoLaterThanDate` / `endNoEarlierThanDate` / `endNoLaterThanDate`
  setters. Round-trip verified live in
  `tests/integration/test_constraints.py` (4 tests, all passing).
  Earlier drafts of this fork's docs marked constraint dates as
  "BLOCKED — value lost across calls"; that was us probing under SDEF
  property names (`startConstraintDate` etc.) that don't exist on the
  omniJS Task class. The documented names work as expected.
- `list_assignments(task_id) -> [{resource_id, resource_name,
  units_assigned}]` — exposes per-task assignment info that
  `list_resources` doesn't cover. (Note: this brings the tool count
  from 19 to 20; the v0.3.0 entry below is pre-`list_assignments`.)

### Fixed
- `list_dependencies` and `add_dependency` now round-trip
  `lead_time_seconds` via the documented `Duration.workSeconds`
  accessor instead of returning `null` / echoing the input. The
  previous session wrongly concluded `Duration` was opaque on read; the
  documented Duration class exposes `workSeconds`, `elapsedSeconds`,
  `elapsed`, and friends. Module docstring and tests updated.
- `assign_resource` now writes via the documented
  `assignment.unitsAssigned` (Number, read/write) instead of the
  non-existent `assignment.units`. The value is read back after the
  write — a true round-trip, not an echo.
- `get_project_info` now enumerates baselines via
  `proj.baselineNames`, returning
  `scenarios: ["Actual", ...proj.baselineNames]` instead of the
  hard-coded `["Actual"]`. The documented Project class exposes
  `baselineNames` (Array of String) plus `baselineNamed(name)`.

### Docs
- Rewrote `dev-docs/omnijs-persistence-gaps.md` from scratch. Earlier
  drafts asserted ~6 "persistence gaps" as facts; on doc re-read those
  were us probing under SDEF AppleScript names (`startConstraintDate`,
  `assignment.units`, etc.) that the omniJS classes don't expose under
  those names. The corrected doc lists only the surviving gaps: missing
  `task.moveTo` / reparenting (verified by three failed paths plus
  saved-bundle XML cross-check), and the `Decimal.toString` regex parse
  workaround. README "Known omniJS limitations" table aligned. ROADMAP
  Tier 1 status updated — constraints flipped from BLOCKED to shipped.

## [0.3.0] - 2026-05-01

> **Note:** Several "BLOCKED" claims in this entry were retracted at
> v0.4.0 — see the v0.4.0 (continued — Tier 1 work) section above for
> what shipped after the doc re-read. Specifically, constraint dates,
> `dep.leadTimeDuration`, `assignment.units` (renamed `unitsAssigned`),
> and `proj.scenarios` (renamed `baselineNames`) all work; the v0.3.0
> "blocked" framing was based on probing under SDEF AppleScript names
> that don't exist on the omniJS surface.

Tier 1 of the fork roadmap (`dev-docs/ROADMAP.md`): adds
project-info, bulk task creation, resource CRUD + assignments, and
documents two omniJS surface gaps (constraints, move) as
`xfail(strict=True)` sentinels. Bumps the fork from 0.2.0 to 0.3.0.

Upstream PRs: [#6](https://github.com/xiahan4956/omniplan-mcp/pull/6),
[#7](https://github.com/xiahan4956/omniplan-mcp/pull/7), and the
resource module PR opened in this release.

Tool count: 13 → 19. New tools: `get_project_info`, `update_project`,
`create_tasks`, `list_resources`, `create_resource`, `delete_resource`,
`assign_resource`, `unassign_resource`.

### Added
- `list_resources`, `create_resource(name, type, email?, cost_per_use?)`,
  `delete_resource(resource_id)`, `assign_resource(task_id, resource_id,
  units?)`, `unassign_resource(task_id, resource_id)` in a new
  `src/omniplan_mcp/resources.py` module. ResourceType enum supports
  `staff` / `equipment` / `material` / `group`. `cost_per_use` is
  written through `Decimal.fromString(...)` per the omniJS contract;
  read back by parsing the Decimal toString.
- `create_tasks(tasks: list[dict])` — bulk task creation in a single
  JXA call. Each spec accepts the same fields as `create_task` plus a
  `parent_index` field for intra-batch parent references (a later task
  can parent to an earlier one without needing the earlier one's
  uniqueID). Performance: 50 tasks via 50 `create_task` calls is
  ~50–150s of osascript startup; via `create_tasks` it's ~1s.
- `get_project_info()` — returns `{name, path, start_date, end_date,
  scenarios}`. `path` is fetched via the JXA SDEF surface (omniJS
  doesn't expose it). `scenarios` only advertises `["Actual"]` because
  `proj.scenarios` is undefined in omniJS.
- `update_project(start_date)` — writes `actual.startDate`. Verified
  persistent across JXA calls.

### Test infrastructure
- `tests/integration/test_save_document.py` skips gracefully when the
  front document hasn't been saved yet (e.g. fresh Tart VM with only
  an Untitled doc) — `document.save()` would otherwise pop the Save As
  sheet and block the JXA call.

### Notes on omniJS gaps
- `actual.currency` accepts a write inline but doesn't persist across
  JXA boundaries (same trap as constraint dates) — deliberately omitted
  from `update_project` rather than shipping a footgun.
- Working hours / calendar — `actual.rootResource.schedule` exists but
  is opaque on read; deferred until we add a parallel SDEF bridge or
  Omni exposes accessors.
- `assignment.units` — write accepted, NOT persistent across JXA
  boundaries (same trap as `dep.leadTimeDuration`). `assign_resource`
  echoes the input value but `list_resources` doesn't expose a units
  field, since reads can't be trusted.
- Constraint dates and `move_task` — both blocked on omniJS persistence
  gaps; documented xfail sentinels in
  `tests/integration/test_constraints.py` and `test_move_task.py`.

## [0.2.0] - 2026-05-01

Tier 0 of the fork roadmap (`dev-docs/ROADMAP.md`): adds dependency
support, effort/three-point estimation, name-based lookup, and
explicit save. Bumps the fork from `0.1.1` to `0.2.0`. Upstream PRs:
[#2](https://github.com/xiahan4956/omniplan-mcp/pull/2),
[#3](https://github.com/xiahan4956/omniplan-mcp/pull/3),
[#4](https://github.com/xiahan4956/omniplan-mcp/pull/4),
[#5](https://github.com/xiahan4956/omniplan-mcp/pull/5).

### Added
- `save_document()` tool. OmniPlan does NOT autosave on idle (verified
  empirically — `document.modified` stays `true` for at least 10s after
  an edit). Explicit save is required to persist between UI File>Save
  commands and the quit-time save prompt. Returns
  `{saved, name, modified_before, modified_after}`. The wrapper polls
  the dirty flag for up to 2s after `document.save()` since the flag
  clears ~500ms after the synchronous return.
- `add_dependency(predecessor_id, successor_id, kind, lead_time_seconds)`,
  `remove_dependency(predecessor_id, successor_id)`,
  `list_dependencies(task_id=None)` tools (new module
  `src/omniplan_mcp/dependencies.py`). Supports all four DependencyKind
  values (FS / SS / FF / SF). **Known limitation:** `lead_time_seconds`
  is write-only — OmniPlan's omniJS `Duration` is opaque and exposes no
  read accessor, so `list_dependencies` returns `lead_time_seconds:
  null`. Documented in the module docstring and tests.
- `find_task(name, exact=False)` tool. Substring (case-insensitive) by
  default, exact match opt-in. Returns `[{id, title, outline_id}]`.
  Removes the "list everything → grep → use ID" pattern.
- `create_task` / `update_task` accept `effort_seconds`,
  `min_effort_seconds`, `expected_effort_seconds`, `max_effort_seconds`.
  Effort writes a raw integer to `task.effort` (verified live against
  OmniPlan 4.10.2). Setting all three estimates triggers OmniPlan's
  PERT recompute: `effort = (min + 4*expected + max) / 6` — documented
  in `tests/integration/test_effort.py`.
- `tests/` package: pytest layout (`unit/`, `integration/`, `manual/`,
  `fixtures/`), `requires_omniplan` marker that auto-skips when OmniPlan 4
  is not running, integration `test_root` fixture that creates `__test__root`
  on demand and cleans up every `__test__*` task after each test.
- `[project.optional-dependencies] dev` group with `pytest` and
  `pytest-asyncio`.
- Unit tests for the JXA envelope helpers in `tests/unit/test_jxa_escape.py`.
- Integration tests for effort fields in `tests/integration/test_effort.py`.

### Changed
- `test_tools.py` moved to `tests/manual/smoke.py`. Run with
  `python tests/manual/smoke.py`. Unchanged behaviour.
- ROADMAP: documented the front-document + marker-isolation testing
  approach (no checked-in `.oplx` fixture for now).

## [0.1.0] - upstream baseline

Forked from [xiahan4956/omniplan-mcp](https://github.com/xiahan4956/omniplan-mcp)
at commit `b235768` on 2026-05-01. Six task-CRUD tools:
`list_documents`, `query_tasks`, `get_task`, `create_task`, `update_task`,
`delete_task`.
