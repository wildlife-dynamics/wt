# Phase 6 Completion Plan: wt-compiler CLI and Legacy Removal

## Overview

Complete Phase 6 of the wt refactoring by:
1. Adding a CLI to wt-compiler
2. Auditing and filling gaps in wt-task (if any)
3. Verifying wt-compiler templates generate correct imports
4. Removing legacy modules from ecoscope-workflows-core
5. Regenerating examples and testing

**Key Principle**: ecoscope-workflows packages become **pure function registries** that only depend on `wt-registry` (for `@register`). They do NOT depend on `wt-task`. Any infrastructure code currently in these packages should already exist in wt-task or wt-compiler.

## Tasks

### 1. Add CLI to wt-compiler

**Files to create/modify:**
- `wt/wt-compiler/src/wt_compiler/__main__.py` (NEW)
- `wt/wt-compiler/pyproject.toml` (add entry point + click dependency)

**Implementation:**
```python
# __main__.py - mirror legacy CLI structure
from io import TextIOWrapper
import click
import ruamel.yaml
from wt_compiler import DagCompiler, Spec

yaml = ruamel.yaml.YAML(typ="safe")

@click.command()
@click.option("--spec", type=click.File("r"), required=True, help="Workflow spec YAML file")
@click.option("--clobber/--no-clobber", default=False, help="Overwrite existing build directory")
@click.option("--install/--no-install", default=False, help="Generate lockfile and install deps")
@click.option("--update/--no-update", default=False, help="Update lockfile (with --clobber --no-install)")
def compile(spec: TextIOWrapper, clobber: bool, install: bool, update: bool):
    if update and not (clobber and not install):
        raise ValueError("--update requires --clobber and --no-install")
    spec_text = spec.read()
    compilation_spec = Spec(**yaml.load(spec_text))
    dc = DagCompiler(spec=compilation_spec)
    wa = dc.generate_artifacts(spec_relpath=spec.name)
    wa.dump(clobber=clobber, update=update)
    if install:
        wa.install()
    elif update:
        wa.update()

@click.group()
def main():
    pass

main.add_command(compile)

if __name__ == "__main__":
    main()
```

**pyproject.toml changes:**
```toml
dependencies = [
    ...
    "click>=8.0.0",  # ADD
]

[project.scripts]
wt-compiler = "wt_compiler.__main__:main"
```

### 2. Audit wt-task for Gaps

**Compare ecoscope-workflows-core infrastructure with wt-task:**

| Module | ecoscope-workflows-core | wt-task | Gap? |
|--------|------------------------|---------|------|
| SyncTask, AsyncTask | decorators.py | ✅ sync_task.py, async_task.py | No |
| task decorator | decorators.py | ✅ decorator.py | No |
| Executors base | executors/base.py | ✅ executors/base.py | No |
| PythonExecutor | executors/python.py | ✅ executors/python.py | No |
| Graph | graph.py | ❌ Not present | **Evaluate** |
| skip utilities | skip.py | ✅ skip.py | No |
| MockSyncTask | testing.py | ❌ Not present | **Evaluate** |
| util functions | util.py | ❓ Check wt-compiler | **Evaluate** |

**Action for each gap:**

1. **Graph**: DAG execution infrastructure
   - This is used by generated code for workflow execution
   - Must exist in wt-task for generated DAGs to import from `wt_task`
   - **Action**: Verify if present, add if missing

2. **MockSyncTask**: Testing utility
   - Used for mocking task execution in tests
   - Could be added to wt-task or kept as test utility
   - **Action**: Evaluate if generated tests need this

3. **util.py functions**: Task import utilities
   - `import_task_from_reference` - validates SyncTask instances
   - May be obsolete with @register architecture
   - **Action**: Check if wt-compiler has equivalent, or if obsolete

### 3. Verify wt-compiler Templates

**Check that templates generate correct imports:**

Per Phase 4.1 status, templates were updated to use:
```python
from wt_task import task
task(registered_function).partial(...).map(...)
```

**Verify these templates:**
- `wt-compiler/src/wt_compiler/templates/run_async.jinja2`
- `wt-compiler/src/wt_compiler/templates/run_sequential.jinja2`
- `wt-compiler/src/wt_compiler/templates/jupytext.jinja2`
- `wt-compiler/src/wt_compiler/templates/_macros.jinja2`

**Check for any remaining imports from:**
- `ecoscope_workflows_core.decorators`
- `ecoscope_workflows_core.graph`
- `ecoscope_workflows_core.executors`

**Update templates if needed** to import from `wt_task` instead.

### 4. Remove Legacy Modules from ecoscope-workflows-core

**After gaps are filled and templates verified:**

**Files to DELETE:**
- `ecoscope_workflows_core/decorators.py` (642 lines)
- `ecoscope_workflows_core/registry.py` (215 lines)
- `ecoscope_workflows_core/compiler.py` (1321 lines)
- `ecoscope_workflows_core/__main__.py` (CLI entry point)
- `ecoscope_workflows_core/graph.py` (if migrated to wt-task)
- `ecoscope_workflows_core/testing.py` (if migrated to wt-task)
- `ecoscope_workflows_core/util.py` (if obsolete or migrated)
- `ecoscope_workflows_core/executors/` directory (if equivalent in wt-task)

**Files to MODIFY:**
- `pyproject.toml`:
  - Remove `scripts = { ecoscope-workflows = ... }` entry point
  - Remove click dependency (if only used by CLI)
- `__init__.py`:
  - Remove exports of deleted modules

**Tests to DELETE:**
- `tests/test_decorators.py`
- `tests/test_graph.py` (if graph moved to wt-task)
- `tests/test_executors.py` (if executors equivalent)
- Other tests for deleted modules

### 5. Update Recompilation Workflow

**Modify dev/recompile.sh:**

```bash
# OLD
pixi run ... ecoscope-workflows compile --spec examples/${example}/spec.yaml --clobber

# NEW
pixi run ... wt-compiler compile --spec examples/${example}/spec.yaml --clobber
```

**Also update pixi.toml** to add wt-compiler to compile environment.

### 6. Regenerate and Test Examples

**Do NOT manually edit examples/ - regenerate them:**

```bash
# Regenerate all examples
./dev/recompile.sh patrols --clobber
./dev/recompile.sh events --clobber
./dev/recompile.sh subject-tracking --clobber
```

**Verify generated code imports from wt_task:**
```bash
grep -r "from wt_task import" examples/*/ecoscope-workflows-*/ecoscope_workflows_*/dags/
grep -r "from ecoscope_workflows_core.decorators" examples/  # Should find nothing
grep -r "from ecoscope_workflows_core.graph" examples/       # Should find nothing
```

**Run example tests:**
```bash
cd examples/patrols/ecoscope-workflows-patrols-workflow && pixi run pytest
cd examples/events/ecoscope-workflows-events-workflow && pixi run pytest
cd examples/subject-tracking/ecoscope-workflows-subject-tracking-workflow && pixi run pytest
```

## Execution Order

1. **Add wt-compiler CLI** (Task 1)
   - Create `__main__.py`
   - Add click dependency and entry point
   - Test: `wt-compiler compile --help`

2. **Audit wt-task gaps** (Task 2)
   - Check if Graph class exists in wt-task
   - Identify any other gaps (MockSyncTask, util functions)
   - Fill gaps if needed (add to wt-task)

3. **Verify templates** (Task 3)
   - Check wt-compiler templates for legacy imports
   - Update if any still reference ecoscope_workflows_core infrastructure

4. **Update recompile workflow** (Task 5)
   - Modify dev/recompile.sh to use wt-compiler
   - Update pixi.toml compile environment

5. **Regenerate one example** (Task 6, partial)
   - Regenerate patrols example
   - Verify generated imports are correct
   - Run tests

6. **Remove legacy modules** (Task 4)
   - Delete infrastructure modules from ecoscope-workflows-core
   - Delete associated tests
   - Update pyproject.toml and __init__.py

7. **Regenerate remaining examples** (Task 6, complete)
   - Regenerate events and subject-tracking
   - Run all tests

8. **Update documentation**
   - Update wt/PHASE6_STATUS.md to mark complete

## Critical Files Summary

**wt-compiler (add CLI):**
| Action | File |
|--------|------|
| CREATE | `wt/wt-compiler/src/wt_compiler/__main__.py` |
| MODIFY | `wt/wt-compiler/pyproject.toml` |

**wt-task (fill gaps if needed):**
| Action | File |
|--------|------|
| MAYBE ADD | Graph class (if not present) |

**wt-compiler (verify templates):**
| Action | File |
|--------|------|
| VERIFY | `templates/run_async.jinja2` |
| VERIFY | `templates/run_sequential.jinja2` |
| VERIFY | `templates/_macros.jinja2` |

**ecoscope-workflows-core (remove legacy):**
| Action | File |
|--------|------|
| DELETE | `decorators.py`, `registry.py`, `compiler.py`, `__main__.py` |
| DELETE | `graph.py`, `testing.py`, `util.py` (after audit) |
| DELETE | `executors/` directory (after equivalence check) |
| MODIFY | `pyproject.toml`, `__init__.py` |
| DELETE | Tests for deleted modules |

**Recompilation workflow:**
| Action | File |
|--------|------|
| MODIFY | `ecoscope-workflows/dev/recompile.sh` |
| MODIFY | `ecoscope-workflows/pixi.toml` (if needed) |

## Success Criteria

- [ ] `wt-compiler compile --help` works
- [ ] `wt-compiler compile --spec <file> --clobber` compiles a workflow
- [ ] wt-task has all infrastructure needed by generated code (no gaps)
- [ ] wt-compiler templates generate imports from `wt_task` (not legacy modules)
- [ ] Legacy modules deleted from ecoscope-workflows-core
- [ ] Legacy CLI entry point removed
- [ ] ecoscope-workflows-core only depends on wt-registry (not wt-task)
- [ ] dev/recompile.sh uses wt-compiler CLI
- [ ] All 3 examples regenerate successfully
- [ ] Generated code imports from `wt_task`
- [ ] No generated code imports from `ecoscope_workflows_core.{decorators,graph,executors}`
- [ ] Example tests pass
- [ ] PHASE6_STATUS.md updated
