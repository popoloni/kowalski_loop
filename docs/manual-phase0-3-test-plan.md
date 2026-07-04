# Manual Test Plan

## Phase 0-3 Release Validation for `llmstack`

This document describes a manual validation plan for the changes recently committed in the `local-llm-workspace` repository.

The scope covers:
- the modular `llmstack` package split
- the model registry and model switching flow
- the Phase 2 loop modes
- the Phase 3 verification gates, `llmstack init` wizard, and `thinking_mode`
- the CLI regression fix for `llmstack init --force`
- the documentation updates in `README.md` and `docs/evolution-plan.md`

The goal is to verify the user-facing behavior end to end, not to re-run the automated test suite.

---

## 1. Test Objectives

A manual tester should be able to confirm that:

1. `llmstack` starts from the expected workspace configuration.
2. Model discovery and model switching work without editing source code.
3. Each loop mode behaves according to its contract.
4. Verification plugins are disabled by default and only run when configured.
5. `llmstack init` can create a fresh workspace config, with or without prompts.
6. Existing configs are protected unless `--force` is provided.
7. The CLI handles `--force` both as a global flag and when it appears after `init`.
8. `thinking_mode` is normalized and can be overridden per task.
9. The documentation explains the current behavior clearly and matches the implementation.

---

## 2. Scope

### In scope
- `llmstack cli`
- `llmstack init`
- model list/use/recommend behavior
- `plan`, `continuous`, `watch`, and `supervised` loop modes
- verification gates and plugin selection
- `thinking_mode` handling
- documentation completeness for the above

### Out of scope
- Phase 4 control plane
- Telegram integration
- dashboard/web analytics work beyond basic launch sanity
- installer automation
- performance benchmarking beyond basic functional checks

---

## 3. Environment and Prerequisites

### Required environment
- macOS workstation with the repository cloned locally
- project virtual environment available at `env/`
- repository root on the command line via the repo folder
- no uncommitted local changes unless the tester explicitly wants to validate against a dirty tree

### Recommended setup commands

```bash
cd /Users/enricopapalini/local-llm-workspace
source env/bin/activate
python -m pip install -e .
```

The editable install step is required if you want to run `python -m llmstack.cli ...`
from temporary workspaces outside the repository root. After that install, the same
activated `env/` can be reused from any test directory under `/tmp`.

### Useful verification commands

```bash
python -m llmstack.cli --help
python -m llmstack.cli init --help
python -m llmstack.cli model --help
```

### Test data suggestions
Prepare at least two temporary workspaces for manual testing:
- one Python-oriented workspace
- one JavaScript-oriented workspace
- one generic workspace

You can create them under `/tmp` or with `mktemp -d`.

Example setup:

```bash
tmp_python=$(mktemp -d /tmp/llmstack-python-XXXXXX)
tmp_js=$(mktemp -d /tmp/llmstack-js-XXXXXX)
tmp_generic=$(mktemp -d /tmp/llmstack-generic-XXXXXX)
```

---

## 4. Acceptance Criteria Summary

The release can be considered manually validated if all of the following are true:
- a new workspace can be initialized interactively
- a new workspace can be initialized non-interactively
- overwrite protection works
- `--force` works in both supported invocation forms
- the generated config contains the expected template metadata
- model switching persists the selected model
- each loop mode behaves as described
- verification plugins remain disabled by default
- plugin filtering, opt-in, opt-out, and `plan_complete` hooks behave correctly
- `thinking_mode` accepts `off`, `auto`, and `on`
- the docs match the actual CLI behavior and config keys

---

## 5. Manual Test Cases

### 5.1 CLI and Help Surface

#### TC-CLI-01: Top-level help is available
**Purpose:** confirm the CLI entry point is wired and discoverable.

**Steps:**
1. Run `python -m llmstack.cli --help`.
2. Run `python -m llmstack.cli init --help`.
3. Run `python -m llmstack.cli model --help`.

**Expected result:**
- Each command prints usage information.
- `init` help mentions the scriptable flags and overwrite control.
- No traceback or import error occurs.

#### TC-CLI-02: Global command dispatch still works after the refactor
**Purpose:** verify the package split did not break the main entry point.

**Steps:**
1. Run `python -m llmstack.cli model list`.
2. Run `python -m llmstack.cli doctor`.

**Expected result:**
- Commands execute without a Python import failure.
- Output reflects the current workspace config.

---

### 5.2 `llmstack init` Wizard

#### TC-INIT-01: Interactive wizard creates a fresh config
**Purpose:** verify the normal onboarding flow.

**Preconditions:**
- Use an empty temporary directory.

**Steps:**
1. Start from a temp directory, for example:

```bash
tmpdir=$(mktemp -d /tmp/llmstack-init-interactive-XXXXXX)
cd "$tmpdir"
```

2. Run:

```bash
python -m llmstack.cli init
```

3. Answer the prompts for:
   - `dev_root`
   - project type
   - project goal
   - model/backend preference
   - starter plan generation choice
4. Confirm the command finishes successfully.

**Expected result:**
- `llmstack_config.json` is created in the workspace.
- The config contains the chosen values.
- A starter plan is created only if the user chose to bootstrap it.
- The wizard shows the selected model and template information.

#### TC-INIT-02: Non-interactive mode works end to end
**Purpose:** verify the wizard can be scripted.

**Steps:**
1. Use a new temporary directory, for example:

```bash
tmpdir=$(mktemp -d /tmp/llmstack-init-noninteractive-XXXXXX)
cd "$tmpdir"
```

2. Run exactly:

```bash
python -m llmstack.cli init \
  --non-interactive \
  --dev-root workspace-js \
  --project-type js \
  --goal "Build a JS tool" \
  --model dflash-qwen27b \
  --no-bootstrap-plan
```

**Expected result:**
- No prompt appears.
- The command succeeds.
- The generated config stores the requested values.
- No starter plan is generated when `--no-bootstrap-plan` is used.

#### TC-INIT-03: Project type aliases normalize correctly
**Purpose:** verify project type handling is user-friendly.

**Steps:**
1. For each alias, start from a fresh temp directory and run the wizard non-interactively.
2. Example commands:

```bash
tmpdir=$(mktemp -d /tmp/llmstack-init-alias-js-XXXXXX)
cd "$tmpdir"
python -m llmstack.cli init --non-interactive --project-type javascript --no-bootstrap-plan

tmpdir=$(mktemp -d /tmp/llmstack-init-alias-py-XXXXXX)
cd "$tmpdir"
python -m llmstack.cli init --non-interactive --project-type py --no-bootstrap-plan
```

3. Repeat with `typescript`, `node`, and `nodejs` as needed.
4. Compare the generated config output for each case.

**Expected result:**
- JavaScript-like aliases normalize to the `js` template.
- `py` normalizes to the Python template.
- Unknown values fall back to `generic`.

#### TC-INIT-04: Generated template metadata is explicit
**Purpose:** confirm the new template metadata is present.

**Steps:**
1. Create a new config using the wizard in a fresh temp directory.
2. Open the resulting `llmstack_config.json` in that temp directory.

**Expected result:**
- The config contains `project_type`.
- The config contains `project_template`.
- The config contains `project_goal`.
- The template block includes at least:
  - template name
  - language
  - description
  - starter layout
  - plan name

#### TC-INIT-05: Bootstrap plan generation can be enabled and disabled
**Purpose:** verify the starter plan switch.

**Steps:**
1. In one fresh temp directory, run:

```bash
python -m llmstack.cli init --non-interactive --project-type python --bootstrap-plan
```

2. In a second fresh temp directory, run:

```bash
python -m llmstack.cli init --non-interactive --project-type python --no-bootstrap-plan
```

**Expected result:**
- When enabled, a starter plan file is generated.
- When disabled, no plan generation occurs.
- The generated `plan_file` path still points to the expected location under `.claude/plans`.

#### TC-INIT-06: Existing config is protected without force
**Purpose:** verify overwrite protection.

**Steps:**
1. Create a fresh temp workspace and add a placeholder config:

```bash
tmpdir=$(mktemp -d /tmp/llmstack-init-protect-XXXXXX)
cd "$tmpdir"
printf '{"sentinel": true}\n' > llmstack_config.json
```

2. Run:

```bash
python -m llmstack.cli init
```

**Expected result:**
- The command fails with a clear overwrite refusal.
- The existing file is left unchanged.

#### TC-INIT-07: `--force` works as a global flag
**Purpose:** verify overwrite is allowed when the flag is passed before `init`.

**Steps:**
1. Create a fresh temp workspace with an existing config file.
2. Run a command such as:

```bash
python -m llmstack.cli --force init --non-interactive --project-type generic --no-bootstrap-plan
```

**Expected result:**
- The command overwrites the existing config.
- The resulting config reflects the new inputs.

#### TC-INIT-08: `--force` works after `init`
**Purpose:** verify the regression fixed in the commit.

**Steps:**
1. Create a fresh temp workspace with an existing config file.
2. Run a command such as:

```bash
python -m llmstack.cli init --force --non-interactive --project-type generic --no-bootstrap-plan
```

**Expected result:**
- The command succeeds.
- The existing config is replaced.
- No `unrecognized arguments: --force` error appears.

#### TC-INIT-09: Invalid model is rejected before write
**Purpose:** confirm model validation happens before the config is written.

**Steps:**
1. Use a fresh temp workspace.
2. Run:

```bash
python -m llmstack.cli init --non-interactive --model not-a-real-model --no-bootstrap-plan
```

**Expected result:**
- The command fails clearly.
- No config is written.
- The error indicates the model is unknown.

---

### 5.3 Model Registry and Switching

#### TC-MODEL-01: Model list shows the registry
**Purpose:** verify the registry is readable through the CLI.

**Steps:**
1. Run `python -m llmstack.cli model list`.

**Expected result:**
- The configured models are listed.
- The active model is clearly marked.
- Model backend information is visible.

#### TC-MODEL-02: Switching models persists the active choice
**Purpose:** verify the selected model is saved.

**Steps:**
1. Run `python -m llmstack.cli model use turboquant-qwen35b-moe`.
2. Re-open `llmstack_config.json`.
3. Run `python -m llmstack.cli model list` again.

**Expected result:**
- `active_model` changes in the config.
- The list shows the new model as active.
- The switch survives a second command invocation.

#### TC-MODEL-03: Recommendation command produces a sensible choice
**Purpose:** verify workload-aware recommendation output.

**Steps:**
1. Run `python -m llmstack.cli model recommend --use agentic`.
2. Run `python -m llmstack.cli model recommend --use decode`.

**Expected result:**
- Each command prints a recommendation.
- The recommended model is consistent with the intended use.
- `--apply` persists the recommended model when requested.

#### TC-MODEL-04: Doctor reports a served-model mismatch
**Purpose:** verify the health check warns when the served model and config disagree.

**Steps:**
1. Start one model on port 8787.
2. Change `active_model` to a different model without restarting the server.
3. Run `python -m llmstack.cli doctor`.

**Expected result:**
- The doctor command reports a mismatch.
- The output suggests how to fix it.
- The command exits non-zero when the mismatch exists.

---

### 5.4 Loop Modes

#### TC-MODE-01: Plan mode respects priority ordering
**Purpose:** verify the ordered-plan behavior is preserved.

**Steps:**
1. Load a plan containing tasks with different `priority` values.
2. Run the supervisor in `plan` mode.
3. Observe the task execution order.

**Expected result:**
- Higher-priority tasks run first.
- Ties preserve original task order.
- Completed tasks are skipped on re-run.

#### TC-MODE-02: Continuous mode picks up appended tasks
**Purpose:** verify the queue-backed mode is live.

**Steps:**
1. Start a workspace in `continuous` mode.
2. Confirm the queue is initially empty.
3. Append a new task to the queue file.
4. Wait for the next poll or refresh cycle.

**Expected result:**
- The new task is picked up automatically.
- The runner does not require a restart.
- Invalid JSON in the queue file does not crash the process.

#### TC-MODE-03: Watch mode enqueues on file change
**Purpose:** verify filesystem watching works.

**Steps:**
1. Start the workspace in `watch` mode.
2. Modify a Python file.
3. Observe the task queue.

**Expected result:**
- A task is enqueued when the file changes.
- Non-Python files are ignored if they are outside the watch filter.
- The watcher remains stable after repeated changes.

#### TC-MODE-04: Supervised mode pauses for approval
**Purpose:** verify the approval flow works.

**Steps:**
1. Start the workspace in `supervised` mode.
2. Let the next task be previewed.
3. Approve the task.
4. Repeat and skip a task once.

**Expected result:**
- The next task is shown before execution.
- Execution waits for approval.
- Approved tasks run.
- Skipped tasks remain marked as skipped.

---

### 5.5 Verification Gates and Plugins

#### TC-GATE-01: Plugins are disabled by default
**Purpose:** verify the default behavior does not change existing task execution.

**Steps:**
1. Load a default config with no `verification_plugins` section.
2. Run a task that only exercises the built-in gates.

**Expected result:**
- No plugin commands run.
- The built-in gates still execute.
- The behavior matches the pre-plugin baseline.

#### TC-GATE-02: Invalid plugin configuration fails fast
**Purpose:** verify configuration validation is strict.

**Steps:**
1. Add an invalid plugin definition to the config.
2. Reload the app or run a command that loads the config.

**Expected result:**
- The config is rejected with a clear error.
- The app does not continue with a broken plugin setup.

#### TC-GATE-03: Plugin selection respects language and file filters
**Purpose:** verify targeted execution.

**Steps:**
1. Configure one plugin for Python files.
2. Configure a second plugin for a different language or filename pattern.
3. Run tasks with matching and non-matching files.

**Expected result:**
- Matching tasks run the plugin.
- Non-matching tasks skip it.
- The skip is silent and does not fail the task.

#### TC-GATE-04: Task-level opt-in works
**Purpose:** verify task-specific allow-listing.

**Steps:**
1. Define multiple plugins globally.
2. Set `verification_plugins` on a task to include only one plugin.
3. Run the task.

**Expected result:**
- Only the selected plugin runs.
- Other matching plugins are suppressed.

#### TC-GATE-05: Task-level opt-out works
**Purpose:** verify task-specific plugin suppression.

**Steps:**
1. Define a plugin that would normally match the task.
2. Set `disable_plugins` on the task.
3. Run the task.

**Expected result:**
- The disabled plugin does not run.
- The task uses only the remaining gates.

#### TC-GATE-06: Failing plugin feedback reaches the retry path
**Purpose:** verify the smart-retry integration.

**Steps:**
1. Configure a plugin that exits non-zero and prints a useful error.
2. Run a task that triggers the plugin.
3. Trigger a retry.

**Expected result:**
- The plugin failure is reported.
- The failure text is captured for the next retry.
- The retry prompt includes the failure context.

#### TC-GATE-07: `plan_complete` hooks run only once
**Purpose:** verify end-of-plan hooks are not repeated per task.

**Steps:**
1. Add a plugin with `when: plan_complete`.
2. Run a plan with multiple tasks.
3. Inspect the plugin side effect.

**Expected result:**
- The plugin runs once after the full plan finishes.
- It does not run after every task.

#### TC-GATE-08: Weak gate warning is visible when expected
**Purpose:** verify weak verification still warns the user.

**Steps:**
1. Run a task that only satisfies minimal verification.
2. Observe the gate output.

**Expected result:**
- The weak-gate warning appears when applicable.
- The warning does not prevent normal completion unless the task truly fails.

---

### 5.6 `thinking_mode`

#### TC-THINK-01: Default thinking mode is off
**Purpose:** verify the config default.

**Steps:**
1. Load a workspace config with no explicit `thinking_mode`.
2. Run an agentic task.

**Expected result:**
- The active mode resolves to `off`.
- No invalid mode error is raised.

#### TC-THINK-02: `auto` enables adaptive thinking
**Purpose:** verify the intermediate reasoning mode.

**Steps:**
1. Set `thinking_mode` to `auto` globally or on a task.
2. Run an agentic task.
3. Inspect the debug logs.

**Expected result:**
- The task runs with adaptive thinking enabled.
- Debug output shows the selected mode.

#### TC-THINK-03: `on` enables full thinking
**Purpose:** verify the highest reasoning mode.

**Steps:**
1. Set `thinking_mode` to `on` globally or on a task.
2. Run an agentic task.
3. Inspect the debug logs.

**Expected result:**
- Full thinking is enabled.
- The debug logs reflect the override.

#### TC-THINK-04: Task-level override wins
**Purpose:** verify precedence.

**Steps:**
1. Set the global config to `off`.
2. Set a specific task to `auto` or `on`.
3. Run that task.

**Expected result:**
- The task-level value wins over the global default.
- The chosen mode is visible in the task attempt logs.

#### TC-THINK-05: Invalid values are rejected
**Purpose:** verify normalization is strict.

**Steps:**
1. Put an invalid `thinking_mode` value in the config.
2. Reload the app.

**Expected result:**
- The config loader rejects the value.
- The error is clear and actionable.

---

### 5.7 Regression and Documentation Checks

#### TC-DOC-01: README documents the new init wizard fields
**Purpose:** verify the docs match the implementation.

**Steps:**
1. Open `README.md`.
2. Find the `llmstack init` section.
3. Confirm the wizard flags and template descriptions are documented.

**Expected result:**
- The README mentions interactive and non-interactive init.
- The README documents `--force`.
- The README explains the generated config keys: `project_type`, `project_template`, and `project_goal`.

#### TC-DOC-02: Evolution plan reflects the current implementation state
**Purpose:** verify roadmap documentation is current.

**Steps:**
1. Open `docs/evolution-plan.md`.
2. Check the Phase 3 section and the progress snapshot.

**Expected result:**
- Phase 3 is marked done.
- The follow-up refinements are recorded.
- The roadmap still points to Phase 4 as the next step.

#### TC-REG-01: `llmstack init --force` is accepted in the real CLI
**Purpose:** verify the bug fix remains in place.

**Steps:**
1. Create a temp workspace with an existing config file.
2. Run `python -m llmstack.cli init --force --non-interactive ...`.

**Expected result:**
- The command succeeds.
- The config is overwritten.
- No parser error is produced.

---

## 6. Recommended Manual Execution Order

A practical order for a human tester is:

1. CLI and help surface
2. `llmstack init` interactive flow
3. `llmstack init` non-interactive flow
4. overwrite protection and `--force`
5. model list/use/recommend
6. plan mode and priority ordering
7. continuous mode
8. watch mode
9. supervised mode
10. verification plugins and `plan_complete`
11. `thinking_mode`
12. documentation audit

This order moves from low-risk discovery checks to the areas most likely to catch regressions.

---

## 7. Exit Criteria

The change set is ready for release when:
- all test cases above have been run manually at least once
- any failures are either fixed or explicitly accepted
- the docs still match the code after the final verification pass
- the `llmstack init --force` regression has been confirmed as closed

---

## 8. Notes for the Tester

- Prefer fresh temporary directories for init tests so you can inspect the generated files without side effects.
- For model and loop tests, reuse the same workspace only if you want to confirm persistence across runs.
- If a test mentions log inspection, capture the exact output snippet before moving on.
- If a command fails unexpectedly, stop and record the full command and output before retrying.

---

## 9. Manual Checklist

### 9.1 Preflight

- [ ] `env/bin/python` is available and working
- [ ] `python -m llmstack.cli --help` runs without import errors
- [ ] A clean temporary workspace is ready for `llmstack init`
- [ ] The tester knows which workspace is being used for each case

### 9.2 Init Wizard

- [ ] Interactive `llmstack init` creates a new config
- [ ] Non-interactive `llmstack init` creates a new config without prompts
- [ ] `--project-type` selects the expected template
- [ ] `--goal` is stored in the generated config
- [ ] `--model` is stored in the generated config
- [ ] `--bootstrap-plan` generates a plan when enabled
- [ ] `--no-bootstrap-plan` skips plan generation when requested
- [ ] Existing configs are rejected without `--force`
- [ ] `--force` works when passed before `init`
- [ ] `--force` works when passed after `init`
- [ ] The generated config includes `project_type`
- [ ] The generated config includes `project_template`
- [ ] The generated config includes `project_goal`

### 9.3 Models and Modes

- [ ] `llmstack model list` shows the registry and active model
- [ ] `llmstack model use <name>` persists the selected model
- [ ] `llmstack model recommend --use agentic` returns a sensible default
- [ ] `llmstack model recommend --use decode` returns a sensible default
- [ ] `plan` mode preserves priority ordering
- [ ] `continuous` mode picks up appended tasks
- [ ] `watch` mode enqueues on file changes
- [ ] `supervised` mode waits for approval before running

### 9.4 Gates and Thinking Mode

- [ ] Verification plugins stay disabled by default
- [ ] Plugin language/file filtering works
- [ ] Task-level plugin opt-in works
- [ ] Task-level plugin opt-out works
- [ ] Failing plugins feed feedback into the retry path
- [ ] `plan_complete` plugins run once at the end
- [ ] `thinking_mode=off` behaves as expected
- [ ] `thinking_mode=auto` behaves as expected
- [ ] `thinking_mode=on` behaves as expected
- [ ] Task-level `thinking_mode` overrides the global default

### 9.5 Docs and Regression

- [ ] README documents the wizard flags and config keys
- [ ] `docs/evolution-plan.md` marks Phase 3 as done
- [ ] The Phase 3 follow-up refinements are present in the roadmap
- [ ] The `llmstack init --force` regression is confirmed fixed in the real CLI
- [ ] Evidence is saved for every failure or ambiguity

---

## 10. Suggested Evidence to Capture

For each failed or ambiguous test, save:
- the exact command used
- the full terminal output
- the workspace path
- the relevant config file snippet
- the generated plan or queue file if applicable

That evidence is usually enough to reproduce and fix most regressions quickly.
