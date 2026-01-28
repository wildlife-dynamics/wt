# wt Roadmap

This document tracks deferred work and future development plans for the wt package ecosystem.

## Deferred Work

### Graph Module Migration

**Status**: Not started
**Priority**: Low (async execution not used in production)

The graph infrastructure for async execution remains in `ecoscope-workflows-core` and has not been migrated to `wt-task`:

- `DependsOn` - dependency declaration for single task dependencies
- `DependsOnSequence` - dependency declaration for sequential task dependencies
- `Graph` - directed acyclic graph representation of task dependencies
- `Node` - graph node representing a task instance

**Why deferred**: Async execution mode is not currently deployed in production. The sequential execution mode is used exclusively, which doesn't require the graph infrastructure.

**What would be needed**:
1. Migrate `ecoscope_workflows_core/graph.py` to `wt-task`
2. Update `run_async.jinja2` template to import from `wt_task.graph`
3. Add async executor implementations to `wt-task`
4. Test async execution end-to-end

### Async Execution Template (run_async.jinja2)

**Status**: Not migrated
**Depends on**: Graph module migration

The `run_async.jinja2` template still imports from `ecoscope_workflows_core` for graph-related functionality. This template will be updated once the graph module is migrated.

### Pluggable Testing Architecture

**Status**: Future consideration
**Priority**: Medium

The testing infrastructure (`create_task_magicmock`, mock return value resolution) currently lives in `ecoscope_workflows_core.testing`. A more pluggable architecture could allow domain-specific implementations of mock data loading.

**Potential improvements**:
- Abstract mock return value resolution interface
- Support for different mock data formats/sources
- Integration with wt-task testing utilities

## Completed Milestones

### Phase 1-5: Core Migration (Completed)
- [x] wt-compiler CLI with `compile` command
- [x] wt-task core components (SyncTask, executors, skip, tracing)
- [x] wt-registry for function registry management
- [x] Templates updated to use `wt_task.task` decorator
- [x] Templates updated to use `wt_task.tracing`

## Contributing

When working on deferred items:
1. Create a feature branch
2. Update this roadmap with progress
3. Ensure backward compatibility where possible
4. Add comprehensive tests for new functionality
