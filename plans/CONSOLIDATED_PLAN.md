# wt (Workflow Toolkit) - Consolidated Project Plan

**Created:** 2026-01-07
**Purpose:** Comprehensive status report + development roadmap
**Source:** Consolidation of ./wt/plans (PLAN.md, PHASE6_STATUS.md, PHASE6_COMPLETION_PLAN.md, PLAN_FIX_DISCOVERY.md)

---

## 1. Project Overview

**wt** is a modular refactoring of the legacy ecoscope-workflows codebase into independent, single-responsibility namespace packages. The core architectural innovation is **separating serializable metadata (`@register`) from execution features (`@task`)**, enabling cross-environment discovery via CLI serialization boundaries.

### Package Architecture

```
wt-contracts (foundation - zero wt deps)
    │
    ├─► wt-registry (discovery & metadata)
    ├─► wt-task (execution features)
    ├─► wt-compiler (DAG generation)
    └─► wt-invokers (execution abstraction)
            │
            └─► wt-runner (FastAPI app)
```

| Package | Purpose | Status |
|---------|---------|--------|
| **wt-contracts** | Type-safe interfaces (Pydantic + Protocols) | ✅ Complete |
| **wt-registry** | `@register` decorator, JSON schema generation, CLI | ✅ Complete |
| **wt-task** | `@task` decorator, .partial()/.map()/.call() execution | ✅ Complete |
| **wt-compiler** | spec.yaml → DAG artifacts (Python, Docker, pixi.toml) | ✅ Core complete, 67% tests passing |
| **wt-invokers** | LocalSubprocess + CloudBatch execution | ✅ Complete |
| **wt-runner** | FastAPI workflow execution endpoints | ✅ Complete |

---

## 2. Key Architectural Decisions (Preserved Context)

### 2.1 Serialization Boundary (from PLAN.md)
Task discovery happens via `wt-registry` CLI in ephemeral rattler environments, NOT direct Python imports. This prevents wt-compiler from needing task library dependencies.

```
wt-compiler ──subprocess──► rattler env ──► wt-registry CLI ──► JSON output
```

### 2.2 Dual-Purpose Task (from PLAN.md)
The `task()` function works as both:
- **Decorator**: `@task` on existing functions
- **Wrapper**: `task(registered_func).partial(...).map(...)` in generated code

### 2.3 Pure Function Registries (from PHASE6_STATUS.md)
Task libraries (ecoscope-workflows-core/ext) become **pure function registries** depending ONLY on `wt-registry` for `@register`. All execution infrastructure lives in `wt-task` or `wt-compiler`.

### 2.4 Two-Phase YAML Loading (from PLAN_FIX_DISCOVERY.md)
Workflow compilation requires:
1. Parse requirements from YAML (without full Spec validation)
2. Populate known_tasks via discovery
3. Validate full Spec (now works with populated known_tasks)
4. Compile to artifacts

---

## 3. Current Status

### Phase Completion

| Phase | Description | Status |
|-------|-------------|--------|
| 0 | Create wt-contracts | ✅ Complete |
| 1 | Move/enhance wt-registry | ✅ Complete |
| 2 | Create wt-task | ✅ Complete |
| 3 | Create wt-invokers | ✅ Complete |
| 4 | Create wt-compiler | ✅ Core complete |
| 5 | Create wt-runner | ✅ Complete |
| 6 | Migrate ecoscope-workflows | 🟡 In Progress (70%) |

### Phase 6 Detailed Status

**Completed:**
- ✅ 101/101 task functions migrated (`@task` → `@register`)
- ✅ 47 functions in ecoscope-workflows-core
- ✅ 54 functions in ecoscope-workflows-ext-ecoscope
- ✅ Dependencies updated to wt-registry >= 0.1.0
- ✅ Entry-points removed (replaced by wt-registry CLI)
- ✅ Metadata enrichment (titles, descriptions, tags)

**Remaining:**
- ✅ wt-compiler CLI implementation
- ⏳ Discovery integration into compiler (PLAN_FIX_DISCOVERY.md) - code exists, needs e2e verification
- ⏳ Legacy module removal from ecoscope-workflows
- ⏳ Example recompilation and testing
- ⏳ Documentation updates

---

## 4. Code Quality Assessment

### Metrics
- **Source files:** 49 Python files (~8,867 LOC)
- **Test files:** 29 test files (~6,405 LOC)
- **Test-to-code ratio:** 72%
- **Overall grade:** B+

### Critical Issues

| Issue | Location | Status |
|-------|----------|--------|
| wt-compiler CLI not implemented | wt-compiler/src/wt_compiler/cli.py | ✅ Complete |
| 15 failing tests in wt-compiler | wt-compiler/tests/ | 🟡 67% pass |
| Discovery not integrated into compiler | wt-compiler/compiler.py | 🟡 Code exists, needs e2e test |

### Technical Debt
- 10 `# type: ignore` comments (external library typing issues)
- Inconsistent error handling patterns across modules
- Missing README for wt-invokers
- Subprocess-based rattler integration (fallback until native API stable)

### Test Coverage Gaps
| Module | Coverage | Priority |
|--------|----------|----------|
| wt-compiler | 54% | High |
| wt-runner | ~34% | Medium |
| wt-compiler/discovery.py | 16% | High |

---

## 5. Remaining Work (Prioritized)

### P0: Critical Path (Unblocks Phase 6 Completion)

1. **~~Implement wt-compiler CLI~~** ✅ COMPLETE
   - Created `wt-compiler/src/wt_compiler/cli.py`
   - Command: `wt-compiler compile --spec <file> --clobber --update`
   - Entry point added to pyproject.toml
   - Files: `cli.py`, `__main__.py`, `pyproject.toml`, `tests/test_cli.py`

2. **Integrate Discovery into Compiler** (PLAN_FIX_DISCOVERY.md) 🟡 CODE EXISTS
   - `discovery.py` uses wt-contracts `RegistryOutput` ✅
   - `compile_workflow_from_yaml()` implements two-phase loading ✅
   - End-to-end integration test needed ⏳
   - Files: `discovery.py`, `compiler.py`

### P1: Phase 6 Completion

3. **Audit wt-task for Gaps**
   - Verify Graph class exists (needed by generated DAGs)
   - Check MockSyncTask (testing utility)
   - Verify util functions present or obsolete

4. **Verify wt-compiler Templates**
   - Ensure templates generate imports from `wt_task` (not legacy)
   - Check for remaining imports from ecoscope_workflows_core

5. **Remove Legacy Modules** (after P0 complete)
   - Delete from ecoscope-workflows-core:
     - decorators.py, registry.py, compiler.py, __main__.py
     - graph.py, testing.py, util.py (after audit)
   - Remove CLI entry point and click dependency

6. **Update Recompilation Workflow**
   - Modify `dev/recompile.sh` to use `wt-compiler compile`
   - Update pixi.toml compile environment

7. **Regenerate and Test Examples**
   - patrols, events, subject-tracking examples
   - Verify imports from `wt_task` (not legacy)
   - Run all example test suites

### P2: Quality Improvements

8. **Fix Failing Tests**
   - 15 failing tests in wt-compiler (API mismatches)
   - Target: >90% pass rate

9. **Increase Test Coverage**
    - wt-compiler: 54% → 80%+
    - wt-compiler/discovery.py: 16% → 60%+

10. **Documentation**
    - Add README to wt-invokers
    - Expand root README with architecture overview
    - Create integration guide

11. **Standardization**
    - Consistent error handling patterns
    - Reduce type-ignore comments
    - Standardize docstring format

---

## 6. Execution Order

```
Phase 6 Completion Path:
┌─────────────────────────────────────────────────────────┐
│ P0.1: wt-compiler CLI                                   │
│ P0.2: Discovery integration                             │
└─────────────────┬───────────────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────────────┐
│ P1.3: Audit wt-task gaps                                │
│ P1.4: Verify templates                                  │
└─────────────────┬───────────────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────────────┐
│ P1.6: Update recompile workflow                         │
│ P1.7: Regenerate ONE example (test)                     │
└─────────────────┬───────────────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────────────┐
│ P1.5: Remove legacy modules                             │
│ P1.7: Regenerate remaining examples                     │
└─────────────────┬───────────────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────────────┐
│ P2: Quality improvements (parallel track)               │
└─────────────────────────────────────────────────────────┘
```

---

## 7. Success Criteria

### Phase 6 Complete When:
- [x] `wt-compiler compile --spec <file>` works end-to-end
- [ ] Discovery populates known_tasks before Spec validation (code exists, needs e2e test)
- [ ] All legacy modules removed from ecoscope-workflows
- [ ] All examples recompiled and tests passing
- [ ] Generated code imports from `wt_task`, not legacy modules

### Project Complete When:
- [ ] All 6 packages installable and documented
- [ ] >90% test pass rate across all packages
- [ ] >80% test coverage for critical modules
- [ ] Type checking passes (mypy strict)
- [ ] Zero circular dependencies
- [ ] Clean separation of concerns verified

---

## 8. Key Files Reference

### wt-compiler (Primary Focus)
- `wt-compiler/src/wt_compiler/compiler.py` - Main compilation logic
- `wt-compiler/src/wt_compiler/discovery.py` - Task discovery (code exists, needs e2e test)
- `wt-compiler/src/wt_compiler/spec.py` - Spec validation
- `wt-compiler/src/wt_compiler/cli.py` - CLI implementation (new)
- `wt-compiler/src/wt_compiler/__main__.py` - CLI entry point (new)

### wt-contracts (Foundation)
- `wt/wt-contracts/src/wt_contracts/registry.py` - RegistryOutput schema

### Legacy (To Remove)
- `ecoscope-workflows-core/ecoscope_workflows_core/decorators.py`
- `ecoscope-workflows-core/ecoscope_workflows_core/registry.py`
- `ecoscope-workflows-core/ecoscope_workflows_core/compiler.py`

### Configuration
- `dev/recompile.sh` - Recompilation script (to update)
- `pixi.toml` - Compile environment (to update)
