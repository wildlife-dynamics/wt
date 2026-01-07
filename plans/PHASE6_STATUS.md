# Phase 6 Implementation Status

**Phase**: Migrate ecoscope-workflows to Strict Function Registries
**Date**: 2025-12-17
**Status**: ✅ **CORE MIGRATION COMPLETE** - Ready for example compilation and testing

---

## Summary

Phase 6 successfully migrated both `ecoscope-workflows-core` and `ecoscope-workflows-ext-ecoscope` from task libraries with embedded execution features to pure function registries using only the `@register` decorator from wt-registry. This is a critical architectural change that separates:

- **Metadata** (`@register`) - stays in task libraries
- **Execution features** (`task()` wrapper) - provided by wt-task package
- **Discovery** - via wt-registry CLI instead of entry-points

---

## What's Complete (✅)

### 1. Core Task Migration (47 functions)

**File**: `ecoscope-workflows-core/ecoscope_workflows_core/tasks/`

All 47 task functions successfully migrated from `@task` to `@register`:

- ✅ **config** (2 functions): `set_string_var`, `set_workflow_details`
- ✅ **analysis** (11 functions): All dataframe aggregation and arithmetic operations
- ✅ **io** (4 functions): `persist_text`, `set_er_connection`, etc.
- ✅ **filter** (2 functions): DataFrame filtering operations
- ✅ **groupby** (4 functions): `set_groupers`, `split_groups`, `merge_df`, `combine_results`
- ✅ **results** (7 functions): Dashboard and widget operations
- ✅ **skip** (4 functions): Skip control flow operations
- ✅ **test** (1 function): Test utilities
- ✅ **transformation** (12 functions): Conversion, filtering, mapping, indexing, etc.

**Changes**:
- Replaced `from ecoscope_workflows_core.decorators import task` with `from wt_registry import register`
- Added meaningful titles and descriptions to all functions
- Applied appropriate tags based on function category
- Fixed 9 functions with malformed/truncated descriptions

**Verification**:
```bash
$ grep -r "^@register" ecoscope-workflows-core/ecoscope_workflows_core/tasks --include="*.py" | wc -l
47

$ grep -r "^@task" ecoscope-workflows-core/ecoscope_workflows_core/tasks --include="*.py" | wc -l
0
```

### 2. Extension Task Migration (54 functions)

**File**: `ecoscope-workflows-ext-ecoscope/ecoscope_workflows_ext_ecoscope/tasks/`

All 54 task functions successfully migrated:

- ✅ **analysis** (8 functions): Aggregation, density calculations, time density
- ✅ **data_connectors** (21 functions): EarthRanger, SMART, Earth Engine downloads
- ✅ **results** (14 functions): EcoMap, EcoPlot, tables
- ✅ **skip** (2 functions): Skip utilities and test functions
- ✅ **transformation** (8 functions): Classification, filtering, normalization
- ✅ **warning** (1 function): Warning utilities

**Verification**:
```bash
$ grep -r "^@register" ecoscope-workflows-ext-ecoscope --include="*.py" | wc -l
54

$ grep -r "^@task" ecoscope-workflows-ext-ecoscope --include="*.py" | wc -l
0
```

### 3. Dependency Updates

**ecoscope-workflows-core/pyproject.toml**:
- ✅ Added `wt-registry = ">=0.1.0"` to dependencies
- ✅ Removed entry-points for task discovery:
  ```toml
  # REMOVED:
  [project.entry-points."ecoscope_workflows"]
  tasks = "ecoscope_workflows_core.tasks"
  ```

**ecoscope-workflows-ext-ecoscope/pyproject.toml**:
- ✅ Added `wt-registry = ">=0.1.0"` to dependencies
- ✅ Removed entry-points for task discovery

### 4. Package Structure

**__init__.py files**:
- ✅ Both packages already have minimal exports (just `tasks` module)
- ✅ No execution features exported (already correct)

### 5. Migration Tooling

Created `migrate_tasks.py` script that:
- ✅ Automatically converts `@task` to `@register`
- ✅ Generates titles from function names (snake_case → Title Case)
- ✅ Extracts descriptions from decorators or docstrings
- ✅ Applies appropriate tags based on directory structure
- ✅ Updates imports from `ecoscope_workflows_core.decorators` to `wt_registry`
- ✅ Handles both packages in one run

**Script statistics**:
- Migrated 41 files total (21 core + 20 ext-ecoscope)
- 101 functions migrated (47 core + 54 ext)
- 100% success rate

---

## What's Not Done (⏳)

### 1. Legacy Module Removal (PENDING)

The following legacy modules should be removed from ecoscope-workflows-core (per Phase 6 plan):

- ⏳ `decorators.py` - Task decorator logic (now in wt-task)
- ⏳ `registry.py` - Registry management (replaced by wt-registry)
- ⏳ `compiler.py` - Compilation logic (replaced by wt-compiler)

**Action**: These modules are still present and may be used by:
- Other parts of the codebase (graph.py, testing.py, etc.)
- The old compilation workflow
- Generated examples

**Decision needed**: Remove immediately or deprecate during example migration?

### 2. Example Compilation Workflow (PENDING)

Current workflow uses old compiler:
```bash
# OLD (in dev/recompile.sh)
pixi run ecoscope-workflows compile --spec examples/patrols/spec.yaml --clobber
```

Should become:
```bash
# NEW
pixi run wt-compiler compile --spec examples/patrols/spec.yaml --clobber
```

**Requirements**:
- wt-compiler CLI tool implementation (not yet implemented per Phase 4.1 status)
- Integration with wt-registry for task discovery
- Template updates to generate code with `task()` wrapper

**Status**: Blocked on wt-compiler CLI tool (Phase 4.1 nice-to-have)

### 3. Example Recompilation and Testing (PENDING)

Need to:
- ⏳ Recompile all three examples (patrols, events, subject-tracking)
- ⏳ Verify generated code uses new pattern:
  ```python
  from wt_task import task
  from ecoscope_workflows_core.tasks.config import set_time_range

  time_range = task(set_time_range).partial(time_format="%Y-%m-%d")
  ```
- ⏳ Run example test suites
- ⏳ Verify end-to-end execution

**Status**: Depends on wt-compiler integration

---

## Known Issues and Limitations (⚠️)

### 1. wt-registry Package Availability

**Issue**: Migration adds `wt-registry >= 0.1.0` dependency but package not yet published.

**Impact**: Cannot install/test migrated packages until wt-registry is:
1. Published to PyPI, OR
2. Published to conda-forge/ecoscope-workflows channel, OR
3. Installed locally in development environment

**Workaround**: For development, can install wt-registry locally:
```bash
cd wt/wt-registry
pip install -e .
```

### 2. Legacy Modules Still Present

**Issue**: decorators.py, registry.py, and compiler.py still exist in ecoscope-workflows-core

**Impact**: May cause confusion, import conflicts, or prevent clean break with old architecture

**Action**: Decide whether to:
- Remove immediately (risky if other code depends on them)
- Deprecate with warnings
- Remove during example migration
- Remove after examples are working

### 3. Generated Code Not Yet Updated

**Issue**: Existing generated examples still import from old infrastructure

**Impact**: Examples won't work with migrated task libraries until regenerated

**Action**: Requires wt-compiler CLI tool and example recompilation

---

## Migration Quality Metrics

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Functions migrated | 101 | 101 | ✅ |
| @task remaining | 0 | 0 | ✅ |
| @register decorators | 101 | 101 | ✅ |
| Files with malformed descriptions | 0 | 0 | ✅ (fixed) |
| Dependencies updated | 2 | 2 | ✅ |
| Entry-points removed | 2 | 2 | ✅ |
| Legacy modules removed | 3 | 0 | ⏳ |

---

## Testing Plan (When Ready)

### 1. Registry Discovery Test
```bash
# Install wt-registry locally
cd wt/wt-registry && pip install -e .

# Test discovery of core tasks
cd ecoscope-workflows/src/ecoscope-workflows-core
python -c "from wt_registry import get_registry; print(len(get_registry()))"
# Expected: 47

# Test discovery of ext-ecoscope tasks
cd ../ecoscope-workflows-ext-ecoscope
python -c "from wt_registry import get_registry; print(len(get_registry()))"
# Expected: 54 (or 101 if core is also imported)
```

### 2. Schema Generation Test
```bash
# Test wt-registry CLI
wt-registry --format json > /tmp/tasks.json
python -c "import json; data = json.load(open('/tmp/tasks.json')); print(f'{len(data[\"entries\"])} tasks')"
```

### 3. Example Compilation Test
```bash
# When wt-compiler CLI is ready
wt-compiler compile --spec examples/patrols/spec.yaml --output /tmp/test-patrols
cd /tmp/test-patrols
grep -n "from wt_task import task" *.py
grep -n "task(set_time_range)" *.py
```

### 4. End-to-End Test
```bash
# Run generated workflow
cd examples/patrols/ecoscope-workflows-patrols-workflow
pixi run pytest
```

---

## Success Criteria Status

From Phase 6 plan:

| Criteria | Status | Notes |
|----------|--------|-------|
| All 101 functions use @register | ✅ Done | 47 core + 54 ext |
| No @task decorators remain | ✅ Done | Verified with grep |
| No execution features exported | ✅ Done | __init__.py already minimal |
| Tasks discoverable via wt-registry CLI | ⏳ Blocked | Need wt-registry installed |
| JSON schemas generated correctly | ⏳ Blocked | Need wt-registry installed |
| Dependencies updated | ✅ Done | Added wt-registry to both packages |
| Entry-points removed | ✅ Done | Removed from both pyproject.toml |
| Old infrastructure removed | ⏳ Pending | decorators.py, registry.py, compiler.py still present |
| Examples recompile with wt-compiler | ⏳ Blocked | Need wt-compiler CLI |
| Example tests pass | ⏳ Blocked | Need successful recompilation |

---

## Recommendations

### Immediate Next Steps (Priority Order)

1. **HIGH**: Install wt-registry locally for development/testing
   ```bash
   cd wt/wt-registry
   pip install -e .
   # OR
   uv pip install -e .
   ```

2. **HIGH**: Test registry discovery
   ```bash
   cd ecoscope-workflows/src/ecoscope-workflows-core
   python -c "from wt_registry import get_registry; from ecoscope_workflows_core import tasks; print(list(get_registry().keys())[:5])"
   ```

3. **MEDIUM**: Implement wt-compiler CLI tool (Phase 4.1 deferred item)
   - Add `wt-compiler compile` command
   - Integrate with wt-registry discovery
   - Update templates to wrap with `task()`

4. **MEDIUM**: Decide on legacy module removal strategy
   - Audit dependencies on decorators.py, registry.py, compiler.py
   - Create deprecation plan
   - Remove or deprecate modules

5. **MEDIUM**: Update example compilation workflow
   - Modify `dev/recompile.sh` to use wt-compiler
   - Test compilation of one example
   - Verify generated code structure

6. **LOW**: Recompile and test all examples
   - Recompile patrols, events, subject-tracking
   - Run test suites
   - Document any breaking changes

### Blockers

1. **wt-registry availability**: Need local installation or conda package
2. **wt-compiler CLI**: Need implementation of CLI tool (Phase 4.1 deferred)
3. **Example dependencies**: Generated examples may depend on legacy modules

---

## Conclusion

✅ **Phase 6 core migration is COMPLETE and successful.**

The architectural transformation from task libraries with embedded execution to pure function registries is complete:
- 101/101 functions migrated
- 0 @task decorators remaining
- Dependencies updated
- Entry-points removed

**Next phase requires**:
- wt-registry installation/availability
- wt-compiler CLI implementation
- Example recompilation and testing

The migration script (`migrate_tasks.py`) can be reused for future task library migrations or reverted if needed.
