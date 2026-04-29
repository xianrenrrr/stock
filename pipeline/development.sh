#!/bin/bash
# STOCK Multi-Agent Pipeline
# Each feature x 5 agents = independent claude CLI calls (no context carryover).
# Subagents run on Opus 4.6 with max effort.
# Modes:
#   Continuous (default): ./development.sh             -> iterate over every TODO feature in docs/feature_backlog.md
#   Fixed:                ./development.sh F00 F01     -> run only the listed features

set -e

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# Subagent invocation: Opus 4.6 + max effort for every claude -p call.
# Override via env if needed (e.g. STOCK_CLAUDE_MODEL=claude-opus-4-6[1m]).
CLAUDE_MODEL="${STOCK_CLAUDE_MODEL:-claude-opus-4-6}"
CLAUDE_EFFORT="${STOCK_CLAUDE_EFFORT:-max}"
BACKLOG_FILE="$PROJECT_DIR/docs/feature_backlog.md"

# Feature set: CLI args override continuous-mode discovery.
if [ $# -gt 0 ]; then
  FEATURES=("$@")
  CONTINUOUS_MODE=0
else
  FEATURES=()
  CONTINUOUS_MODE=1
fi

AGENTS=(planner creator validator screener writer)

LOG_DIR="$PROJECT_DIR/pipeline/logs"
mkdir -p "$LOG_DIR"

CONTEXT_PREFIX="Critical pre-steps (do every time):
1. Read md/complete_workflow.md - THE source of truth for how the entire system works end-to-end.
2. Read docs/code_structure.md - understand current codebase: all files, modules, tables, endpoints.
3. Read docs/feature_backlog.md - find the current feature description, acceptance criteria, key files.
4. Read docs/requirements.md - understand project tech stack and architecture.
5. Read CLAUDE.md - follow the coding style guide strictly.
6. Read design.md at project root if (and only if) you need more architectural context.

Key principles:
- Python 3.12 project. Use type hints, pydantic models, and 'from __future__ import annotations' in every module.
- Existing code is production. Never delete or rewrite functionality that is not explicitly part of this feature.
- Incremental changes only: add new files, or surgically modify existing files.
- When modifying existing files: READ the file first, understand it, then edit.
- Follow naming: snake_case for files/functions/vars, PascalCase for classes/pydantic models, UPPER_SNAKE_CASE for constants.
- Structure function bodies as 'code paragraphs' with one-line '#' comments above each paragraph stating WHAT it does.
- Every source file starts with a single-line module docstring and 'from __future__ import annotations'.
- Imports grouped: stdlib, third-party, internal (stock.*). Blank line between groups. Alphabetical within each.
- No 'except Exception: pass'. Raise specific exceptions. Wrap entry points (CLI, API, scheduled jobs) with structured error handling.
- All LLM calls go through stock.models.get_client(provider) and respect the daily cost ceiling.
- Tests mock all network I/O (LLM, yfinance, RSS). Never let tests touch data/stock.db - use :memory: SQLite."

# discover_next_todo: emit the first feature ID in the backlog whose Status is TODO.
discover_next_todo() {
  awk '
    /^## F[0-9]+/ {
      if (match($0, /F[0-9]+/)) { feat = substr($0, RSTART, RLENGTH) }
    }
    /^\*\*Status\*\*:[[:space:]]*TODO[[:space:]]*$/ {
      if (feat != "") { print feat; exit }
    }
  ' "$BACKLOG_FILE"
}

# feature_status: emit the current status string for a given feature ID.
feature_status() {
  awk -v target="$1" '
    /^## F[0-9]+/ {
      if (match($0, /F[0-9]+/)) { feat = substr($0, RSTART, RLENGTH) }
    }
    /^\*\*Status\*\*:[[:space:]]*/ {
      if (feat == target) {
        sub(/^\*\*Status\*\*:[[:space:]]*/, "")
        sub(/[[:space:]]*$/, "")
        print
        exit
      }
    }
  ' "$BACKLOG_FILE"
}

# run_feature: execute the planner -> creator -> validator -> screener -> writer chain for one feature.
run_feature() {
  local feature="$1"
  local feature_total=${#AGENTS[@]}
  local feature_step=0

  mkdir -p "$PROJECT_DIR/pipeline/outputs/$feature"

  echo ""
  echo "============================================"
  echo " $feature START - $(date)"
  echo " Model: $CLAUDE_MODEL | Effort: $CLAUDE_EFFORT"
  echo "============================================"

  for agent in "${AGENTS[@]}"; do
    feature_step=$((feature_step + 1))
    echo ""
    echo ">>> [$feature $feature_step/$feature_total] $agent - $(date '+%H:%M:%S')"
    echo "--------------------------------------------"

    local log_file="$LOG_DIR/${feature}_${agent}.log"
    local prompt=""

    case $agent in
      planner)
        prompt="You are the Planner Agent. Your task is to create a detailed implementation plan for feature $feature.

$CONTEXT_PREFIX

Planning steps:
1. Read the five docs files listed above to understand the full context.
2. Find $feature in docs/feature_backlog.md - read its description, key files, and acceptance criteria.
3. Read each key file listed for $feature (or the existing files it will modify) to understand the current code.
4. Write a detailed implementation plan including:
   - Files to modify (with specific line ranges and what to change)
   - Files to create (full path, purpose, skeleton of classes/functions)
   - Pydantic models, TypedDicts, or SQL schema changes to add
   - Step-by-step implementation order
   - Edge cases to handle
   - How to verify each acceptance criterion
5. Save the plan to pipeline/outputs/$feature/01_plan.md.
6. Update docs/feature_backlog.md: change $feature status from TODO to IN_PROGRESS.

IMPORTANT: Only plan. Do not write implementation code. Output MUST be saved to the file."
        ;;

      creator)
        prompt="You are the Creator Agent. Your task is to implement feature $feature according to the plan.

$CONTEXT_PREFIX

Implementation steps:
1. Read pipeline/outputs/$feature/01_plan.md - this is your implementation blueprint.
2. For each file to modify: READ the file first, understand existing code, then make surgical edits.
3. For each new file: follow existing project conventions (see CLAUDE.md).
4. Implement all code changes from the plan:
   - Add/modify Python modules, pydantic models, SQL schema as specified.
   - Maintain existing functionality - do not break other features.
   - Follow code paragraph style with comments above each paragraph.
   - Use pydantic BaseModel for structured returns, raise specific exceptions, use named imports grouped by origin.
   - Add/update tests alongside the code (same feature, same commit-equivalent).
5. Save a change summary to pipeline/outputs/$feature/02_code_summary.md with:
   - Files created (full path, purpose)
   - Files modified (full path + what changed)
   - New pydantic models / TypedDicts / SQL tables or columns
   - New CLI commands or FastAPI endpoints
   - Integration points with existing code

IMPORTANT: Actually create/modify code files, not just describe changes. Summary MUST be saved to file."
        ;;

      validator)
        prompt="You are the Validator Agent. Your task is to validate the implementation of feature $feature.

$CONTEXT_PREFIX

Validation steps:
1. Read pipeline/outputs/$feature/02_code_summary.md to know what changed.
2. For each file listed as created: verify it exists and has valid Python syntax (python -m py_compile <file>).
3. For each file listed as modified: read it and verify the changes are correct and complete.
4. Activate the project virtualenv: source .venv/Scripts/activate 2>/dev/null || python -m venv .venv && source .venv/Scripts/activate
5. Install deps if pyproject.toml changed: python -m pip install -e '.[dev]' 2>&1 | tail -5
6. Run tests: python -m pytest -q 2>&1 | tee pipeline/outputs/$feature/_pytest.log
7. Run type check: python -m mypy --strict src/stock 2>&1 | tee pipeline/outputs/$feature/_mypy.log
8. Run lint: python -m ruff check src/stock tests 2>&1 | tee pipeline/outputs/$feature/_ruff.log
9. Verify acceptance criteria from docs/feature_backlog.md are met by reading the code.
10. Check that invariants from docs/requirements.md are not violated (no broker code, cost ceiling honored, loopback only, etc.).
11. Save validation report to pipeline/outputs/$feature/03_validation.md with:
    - Passed checks (prefixed [PASS])
    - Failed checks (prefixed [FAIL], include error message)
    - Fixes applied (if you fixed anything)
    - pytest / mypy / ruff summaries (rows/errors)

IMPORTANT: If you find bugs, FIX them directly in the code. Report MUST be saved to file."
        ;;

      screener)
        prompt="You are the Screener Agent. Your task is to review the code quality of feature $feature.

$CONTEXT_PREFIX

Review steps:
1. Read pipeline/outputs/$feature/02_code_summary.md to know which files to review.
2. Read each changed/created file and review for:
   - Security: prompt injection via news bodies, credential exposure in logs, path traversal, SQL injection (use parameterized queries), OWASP top 10.
   - Code quality: duplication, function length (>50 lines is suspicious), naming, dead code.
   - Error handling: specific exceptions only, no bare except, no silent swallow, entry points wrap with structured error responses.
   - Style compliance: module docstring on line 1, 'from __future__ import annotations' on line 2, import grouping, code paragraphs with one-line '#' comments.
   - Type safety: mypy --strict clean, no 'Any' except where unavoidable, TypedDict or pydantic.BaseModel for structured data.
   - LLM invariant: every call goes through stock.models.get_client() and checks daily cost ceiling before firing.
   - Test invariant: all network I/O mocked, no touching of real data/stock.db.
   - Consistency with existing codebase style.
3. Save review to pipeline/outputs/$feature/04_review.md with:
   - Critical issues (must fix, prefixed [CRITICAL])
   - Suggestions (optional, prefixed [SUGGESTION])
   - Good patterns (prefixed [GOOD])
4. If there are critical issues, fix them directly in the code.

IMPORTANT: Review report MUST be saved to file. Fix critical issues directly."
        ;;

      writer)
        prompt="You are the Writer Agent. Your task is to update project documentation after feature $feature is complete.

$CONTEXT_PREFIX

Documentation steps:
1. Read ALL pipeline outputs for $feature:
   - pipeline/outputs/$feature/01_plan.md
   - pipeline/outputs/$feature/02_code_summary.md
   - pipeline/outputs/$feature/03_validation.md
   - pipeline/outputs/$feature/04_review.md
2. Read current docs/code_structure.md (preserve ALL existing content - append only, never delete).
3. Update docs/code_structure.md:
   - Add new files with one-line descriptions under the appropriate section (src/stock/, tests/, prompts/, data/, etc.).
   - Update descriptions of modified files if their purpose materially changed.
   - Add new SQL tables/columns to the data section if applicable.
4. Update docs/feature_backlog.md: change $feature status from IN_PROGRESS to DONE.
   Only mark DONE if the validation report (03_validation.md) shows tests pass and no [FAIL] checks remain. Otherwise leave as IN_PROGRESS and note the blocker in 05_summary.md.
5. If $feature adds or changes end-to-end flow, update md/complete_workflow.md with the new flow step (append, do not rewrite).
6. Write session summary to pipeline/outputs/$feature/05_summary.md:
   - Feature overview (1-2 sentences)
   - Key changes implemented (bullet list)
   - Files added / modified count
   - pytest / mypy / ruff results summary
   - Any remaining issues or follow-ups for future features

IMPORTANT: MUST update code_structure.md (append only) and feature_backlog.md. Summary MUST be saved to file."
        ;;
    esac

    if claude -p "$prompt" \
         --model "$CLAUDE_MODEL" \
         --effort "$CLAUDE_EFFORT" \
         --dangerously-skip-permissions \
         --verbose 2>&1 | tee "$log_file"; then
      echo "[OK] $feature - $agent completed"
    else
      echo "[FAIL] $feature - $agent FAILED (see $log_file)"
      echo "Continuing to next step..."
    fi
  done

  echo ""
  echo "============================================"
  echo " $feature COMPLETE"
  echo "============================================"
}

echo "============================================"
echo " STOCK Pipeline"
if [ $CONTINUOUS_MODE -eq 1 ]; then
  echo " Mode: CONTINUOUS (drain every TODO feature in $BACKLOG_FILE)"
else
  echo " Mode: FIXED (${FEATURES[*]})"
fi
echo " Model: $CLAUDE_MODEL | Effort: $CLAUDE_EFFORT"
echo " Started at $(date)"
echo "============================================"

FEATURES_DONE=0

if [ $CONTINUOUS_MODE -eq 1 ]; then
  while true; do
    next=$(discover_next_todo)
    if [ -z "$next" ]; then
      echo ""
      echo "No TODO features remaining in $BACKLOG_FILE. Continuous loop complete."
      break
    fi

    run_feature "$next"
    FEATURES_DONE=$((FEATURES_DONE + 1))

    status=$(feature_status "$next")
    if [ "$status" != "DONE" ]; then
      echo ""
      echo "!!! $next status is '$status' after pipeline run (expected DONE)."
      echo "!!! Stopping continuous loop to prevent retrying a stuck feature."
      echo "!!! Inspect $LOG_DIR/${next}_*.log, then either re-run './development.sh $next' or edit the backlog manually."
      break
    fi
  done
else
  for feature in "${FEATURES[@]}"; do
    run_feature "$feature"
    FEATURES_DONE=$((FEATURES_DONE + 1))
  done
fi

echo ""
echo "============================================"
echo " PIPELINE FINISHED"
echo " Features processed: $FEATURES_DONE"
echo " Finished at $(date)"
echo " Logs in: $LOG_DIR/"
echo "============================================"
