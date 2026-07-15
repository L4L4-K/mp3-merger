# Repository-wide refactoring plan

## Scope and compatibility contract

This refactoring targets maintainability, readability, testability, type clarity, and reliability without changing externally observable behavior.

The following contracts must remain unchanged:

- FastAPI application entry point: app.main:app.
- HTTP paths and methods: GET /, POST /api/merge, POST /api/merge-batches, GET /health, /static.
- Existing FastAPI default documentation endpoints.
- Multipart field names, minimum/maximum file-count behavior, status codes, response media types, response filenames, and error detail text.
- Environment variable names, defaults, import-time loading, and FFmpeg argument semantics.
- Browser workflow, visible messages, file ordering, naming, sequential per-batch requests, ZIP format, and download behavior.
- Docker/Compose startup commands and port.
- Existing helper names exported from app.main, even though only app.main:app is documented.

Breaking changes, security-boundary changes, removal of /api/merge-batches, asynchronous job processing, upload-body enforcement, dependency major upgrades, and ZIP64/streaming changes are deferred migration work.

## Baseline

Baseline commit: c6418266038da469bf8d36cc728cd16d6848017d on develop.

Pre-existing worktree state:

- Tracked files were clean.
- REPOSITORY_ANALYSIS.md already existed as an untracked file and must be preserved.

Validation baseline:

| Check | Result |
|---|---|
| FastAPI import and route enumeration through uv/Python 3.12.13 | Passed; existing routes include OpenAPI/Swagger/ReDoc, /static, /, both merge APIs, and /health |
| Python dependency consistency | Passed: no broken requirements |
| python -m compileall -q app | Passed |
| Existing repository test command | None |
| Exploratory unittest discovery | Failed before tests ran because tests/ did not exist |
| git diff --check | Passed |
| Node.js / FFmpeg / Docker execution | Not available in the local environment |

## Refactor pass 1: Characterization and contract tests

### Targets

- tests/python/
- tests/js/
- package.json
- Existing public behavior in app/main.py and static/js/

### Current behavior

The repository has no automated tests. CI checks dependency consistency, Python bytecode compilation, and Docker build only.

### Problem evidence

- app/main.py combines configuration, validation, filesystem I/O, FFmpeg command construction, process execution, manifest parsing, and routes.
- Critical naming, state, and ZIP behavior is implemented in static/js/ without tests.
- .github/workflows/ci.yml does not execute application behavior.

### Improvement

- Add Python unittest characterization tests without adding Python dependencies.
- Add Node built-in test-runner tests without npm dependencies.
- Cover environment defaults/overrides, manifest errors, filename rules, upload limits, FFmpeg argv/errors, route registration/response behavior, frontend naming/state, merge-entry construction, and ZIP headers/CRC.

### Preserved contract

Tests assert current behavior rather than introducing new behavior.

### Risks

- Tests may accidentally depend on implementation details.
- FFmpeg process tests must mock subprocess execution; a separate real-FFmpeg smoke remains necessary.

### Validation

- python -m unittest discover -s tests/python -t . -v
- npm test
- npm run check

### Completion criteria

- Tests cover normal, invalid, empty, duplicate, and boundary cases.
- No network or external service is required by tests.
- Tests fail if public route, error, naming, command, ordering, or ZIP contracts drift.

### Dependencies

None. This pass protects later refactors.

## Refactor pass 2: Backend module boundaries

### Targets

- app/main.py
- app/config.py
- app/manifests.py
- app/uploads.py
- app/audio.py
- app/__init__.py

### Current behavior

app/main.py is a 305-line module containing all backend responsibilities.

### Problem evidence

- Import-time environment parsing is mixed with route registration.
- Pure manifest and command-building logic is coupled to HTTP and process execution.
- Upload validation, filesystem writes, subprocess execution, and response lifecycle are difficult to test independently.
- The server-side batch route creates its output directory before entering its cleanup-protected try block.

### Improvement

- Introduce an immutable typed settings value while retaining the original constants.
- Move manifest parsing to a typed module.
- Move upload/name/filesystem helpers to an upload module with explicit size/chunk parameters.
- Move FFmpeg command construction and process result handling to an audio module with explicit encoding settings.
- Keep routes and compatibility wrappers in app.main.
- Move batch output-directory creation into the existing cleanup-protected region.

### Preserved contract

- Exact routes, signatures, constants, status codes, detail strings, response headers, environment semantics, command ordering, timeout, and cleanup timing.
- Existing helper symbols remain importable from app.main.

### Risks

- Import order could change environment-loading or route registration.
- Wrapper defaults could diverge from previous module constants.
- Exception translation could change accidentally.

### Validation

- Full Python characterization suite.
- FastAPI import and exact route enumeration.
- OpenAPI path comparison.
- python -m compileall app tests.

### Completion criteria

- app.main primarily owns application/route composition.
- Domain-independent parsing and command construction can be tested without starting a server or FFmpeg.
- No circular imports.
- Characterization tests pass unchanged.

### Dependencies

Depends on pass 1.

## Refactor pass 3: Frontend testability and type clarity

### Targets

- static/app.js
- static/js/jobs.js
- static/js/state.js
- tests/js/frontend.test.js

### Current behavior

The frontend is already split into ES modules, but merge-entry construction remains private inside the DOM-heavy app entry point and state shapes are implicit.

### Problem evidence

- static/app.js:getReadyEntries combines state access with pure output-name/title derivation.
- Core state, natural sorting, naming, and ZIP behavior has no executable specification.
- Batch/item/state object shapes are not documented for editor type inference.

### Improvement

- Extract only merge-entry construction into a pure jobs.js module.
- Add focused JSDoc structural types to state.js without runtime dependencies.
- Reject invalid item indexes before mutation so a stale drag source cannot move or remove the last item; valid index behavior is unchanged.
- Test existing pure modules and state transitions using Node's built-in runner.

### Preserved contract

- DOM structure, event wiring, messages, request order, field names, progress calculation, filenames, ZIP bytes, download behavior, and all valid item operations.

### Risks

- ES module configuration could affect Node tooling; browser loading remains native ES modules.
- Shared mutable state requires tests to reset state explicitly.

### Validation

- npm test
- npm run check
- Static import graph review for cycles.

### Completion criteria

- Extracted function produces byte-for-byte-equivalent entry names/titles.
- Existing state and ZIP behavior is characterized, including invalid-index no-op handling and ZIP central-directory metadata.
- No browser-facing text changes; the only control-flow change is the invalid-index early return, while valid operations remain unchanged.

### Dependencies

Pass 1 test infrastructure; may proceed independently of backend split.

## Refactor pass 4: CI and documentation alignment

### Targets

- .github/workflows/ci.yml
- README.md
- docs/refactoring/plan.md

### Current behavior

CI compiles Python and builds Docker but runs no behavior tests. README has no validation commands and lists only the pre-refactor structure.

### Problem evidence

- Regression tests would not protect pull requests unless wired into CI.
- New contributors cannot discover test commands from README.

### Improvement

- Run Python tests in the existing Python job.
- Add an explicit frontend test/check job using a pinned Node major.
- Update README structure and validation instructions.
- Record completion status and validation evidence here.

### Preserved contract

Runtime/deployment behavior and dependencies remain unchanged. package.json is private and contains no packages.

### Risks

- The new CI job depends on the selected setup-node action and hosted-runner availability.
- Node is not installed on PATH in the workspace; local validation therefore uses a disposable Node 22 runtime outside the repository.

### Validation

- YAML/static review.
- Local Python suite and syntax checks.
- Node commands when a Node runtime is available.
- git diff --check and final worktree review.

### Completion criteria

- Every added test has a documented local command and a CI execution path.
- README and source tree agree.
- No generated artifacts remain.

### Dependencies

Depends on passes 1-3.

## Progress

- [x] Baseline and compatibility contract recorded.
- [x] Pass 1: characterization tests.
- [x] Pass 2: backend boundaries.
- [x] Pass 3: frontend testability.
- [x] Pass 4: CI/documentation.
- [x] Final full validation and self-review.

## Completion evidence

| Check | Result |
|---|---|
| Python dependency consistency | Passed: `python -m pip check` reported no broken requirements |
| Python tests | Passed: 45 discovered, 44 passed, 1 skipped because local FFmpeg/ffprobe executables are unavailable |
| Python compilation | Passed: `python -m compileall -q app tests`; generated bytecode directories were removed after the check |
| ASGI/OpenAPI contract | Passed: import, exact route order, and four documented OpenAPI paths match the baseline |
| JavaScript syntax | Passed: `npm run check` with a disposable Node.js 22.14.0 runtime |
| Frontend tests | Passed: 11 of 11 with Node's built-in test runner |
| Whitespace and worktree review | Passed: tracked and new-file whitespace checks, generated-artifact scan, and final path review |
| Docker build | Not run: Docker is unavailable in the local environment; the existing CI Docker job remains unchanged |
| Real FFmpeg integration | Not run locally: test skipped for missing executables; CI installs FFmpeg before running the suite |
| Lint, formatter, and static type checker | Not run: the repository defines none; JavaScript `node --check` is syntax validation, not type checking |

The temporary Node runtime lives under the operating-system temporary directory and is removed after validation. `REPOSITORY_ANALYSIS.md` remains the pre-existing untracked file recorded at baseline and is not part of this refactoring.
