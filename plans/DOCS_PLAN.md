# Documentation Plan: wt-* Framework & Ecoscope Workflow Patterns

## Overview

Create two interconnected documentation sites following the [Divio documentation system](https://docs.divio.com/documentation-system/):
1. **wt-* Framework docs** (this repo) - General-purpose workflow compilation & execution
2. **Ecoscope Workflows docs** (ecoscope-workflows repo) - Ecoscope-specific patterns & conventions

**Primary audience**: New Ecoscope workflow developers
**Secondary audiences**: Internal contributors, future standalone wt-* users

---

## Tooling Decisions

| Aspect | Choice | Rationale |
|--------|--------|-----------|
| **Static site generator** | MkDocs + Material theme | Python-native, excellent search, easy GitHub Pages deployment |
| **Code examples** | Tested snippets | Extract to runnable test files to prevent drift |
| **Tutorial structure** | Getting-started + Advanced | Beginner tutorials with minimal examples; advanced tutorials walking through production workflows |
| **API documentation** | Auto-generated + hand-written | mkdocstrings for API reference, curated narrative guides |

---

## Part 1: wt-* Framework Documentation (This Repo)

### Location
```
docs/
├── index.md                    # Landing page with package overview
├── tutorials/
│   ├── registering-tasks.md    # Create and register task functions
│   └── first-workflow.md       # Build your first workflow end-to-end
├── how-to/
│   ├── compile-workflow.md     # Compile a spec.yaml to artifacts
│   ├── run-locally.md          # Execute workflows locally
│   ├── run-cloud-batch.md      # Deploy to Google Cloud Batch
│   ├── run-via-api.md          # Use wt-runner HTTP API
│   └── use-task-methods.md     # .map(), .partial(), .validate(), etc.
├── reference/
│   ├── packages.md             # Package architecture diagram & roles
│   ├── spec-yaml.md            # Workflow specification format
│   ├── wt-contracts/
│   │   ├── index.md            # Package overview
│   │   ├── registry-models.md  # RegistryMetadata, RegistryEntry, etc.
│   │   ├── task-models.md      # TaskProtocol
│   │   └── cli-models.md       # WorkflowCLIArgs, WorkflowCLIEnv
│   ├── wt-registry/
│   │   ├── index.md            # Package overview
│   │   ├── decorator.md        # @register decorator API
│   │   ├── registry.md         # get_registry(), global registry
│   │   └── cli.md              # wt-registry CLI reference
│   ├── wt-task/
│   │   ├── index.md            # Package overview
│   │   ├── decorator.md        # @task decorator API
│   │   └── methods.md          # .call(), .map(), .partial(), etc.
│   ├── wt-compiler/
│   │   ├── index.md            # Package overview
│   │   ├── compiler.md         # DagCompiler class
│   │   ├── spec.md             # Spec, TaskInstance, TaskGroup models
│   │   ├── discovery.md        # discover_tasks_from_requirements()
│   │   └── artifacts.md        # Generated artifact types
│   ├── wt-invokers/
│   │   ├── index.md            # Package overview
│   │   ├── abstract.md         # AbstractInvoker interface
│   │   ├── local.md            # LocalSubprocessInvoker
│   │   └── cloud-batch.md      # CloudBatchInvoker
│   └── wt-runner/
│       ├── index.md            # Package overview
│       ├── api.md              # HTTP endpoints reference
│       └── tracing.md          # OpenTelemetry configuration
└── explanation/
    ├── architecture.md         # Monorepo design & package relationships
    ├── discovery-mechanism.md  # Subprocess-based task discovery (why/how)
    └── contracts.md            # Serialization boundaries & type safety
```

### Per-Package README Updates
Each package keeps its own `README.md` with:
- Quick installation
- Minimal usage example
- Link to full docs

---

## Part 2: Ecoscope Workflows Documentation (ecoscope-workflows repo)

### Key Insight: Workflow Types as Primary Organizing Concept

Ecoscope has multiple **workflow types** (dashboard, file download, etc.), each with:
- A **runnable skeleton** developers can copy and modify
- **Required integration points** (e.g., time_range, data source, gather_dashboard)
- **Optional customizations** they can add incrementally

**Documentation philosophy**: Give developers a working skeleton first, explain pieces in context, defer deep dives to reference docs.

### Location
```
docs/
├── index.md                            # Landing page: "What workflow type do you want to build?"
│
├── workflow-types/                     # PRIMARY: Organized by workflow type
│   ├── dashboard/
│   │   ├── index.md                    # What is a dashboard workflow? When to use it?
│   │   ├── skeleton.md                 # Minimal working spec.yaml you can copy & run
│   │   ├── integration-points.md       # Required pieces: time_range, data_source,
│   │   │                               # workflow_details, groupers, widgets, gather_dashboard
│   │   ├── adding-widgets.md           # How to add/customize widgets
│   │   ├── adding-groupers.md          # How to add filtered/paginated views
│   │   └── layout.md                   # Dashboard grid layout (layout.json)
│   └── file-download/
│       ├── index.md                    # What is a file download workflow?
│       ├── skeleton.md                 # Minimal working spec.yaml
│       └── ...
│
├── tutorials/                          # LEARNING: Step-by-step guides
│   ├── getting-started/
│   │   ├── run-the-skeleton.md         # Clone skeleton, run it, see output
│   │   └── customize-your-first.md     # Make one change, see the result
│   └── advanced/
│       ├── events-workflow.md          # Full walkthrough: events example
│       ├── patrols-workflow.md         # Full walkthrough: patrols example
│       └── subject-tracking-workflow.md # Full walkthrough: subject-tracking
│
├── how-to/                             # GOAL-ORIENTED: Specific tasks
│   ├── configure-data-sources.md       # EarthRanger connection setup
│   ├── customize-forms.md              # RJSF overrides for configuration UI
│   └── deploy-workflow.md              # Build & deploy to production
│
├── reference/                          # DEEP DIVES: When you need specifics
│   ├── gather-dashboard.md             # Terminal task contract & schema
│   ├── widget-types.md                 # WidgetSingleView, GroupedWidget contracts
│   ├── groupers.md                     # ValueGrouper, TemporalGrouper, AllGrouper
│   ├── data-models.md                  # Events, Patrols, Subjects, Observations
│   ├── earthranger-tasks.md            # get_events, get_patrols, etc.
│   └── form-customization.md           # Full RJSF override syntax
│
└── explanation/                        # UNDERSTANDING: Why things work this way
    ├── workflow-types.md               # Overview of all workflow types
    ├── dashboard-rendering.md          # How web/desktop apps render dashboards
    └── grouper-views.md                # How groupers drive paginated views
```

### Workflow Type Documentation Template

Each workflow type directory follows this pattern:

| File | Purpose |
|------|---------|
| `index.md` | What is this workflow type? When to use it? What does output look like? |
| `skeleton.md` | **Minimal working spec.yaml** - copy this and run it immediately |
| `integration-points.md` | Required pieces explained in context (not as isolated topics) |
| `adding-*.md` | How to customize/extend the skeleton |

---

## Cross-Navigation Strategy

### In wt-* docs
- Banner at top: "Building for Ecoscope? See [Ecoscope Workflow Patterns →](link)"
- In each relevant section, callout boxes: "Ecoscope users: see [specific Ecoscope doc]"

### In Ecoscope docs
- Banner at top: "Ecoscope workflows are built on the [wt-* framework →](link)"
- Reference sections link to wt-* reference for underlying concepts
- Clear separation: "This is an Ecoscope convention" vs "This is wt-* framework behavior"

---

## Content Priorities (Phase 1)

### Must Have (MVP for onboarding)
1. **wt-* index.md** - Package architecture diagram, quick start pointers
2. **wt-* tutorials/registering-tasks.md** - How to create task functions
3. **wt-* reference/spec-yaml.md** - Full spec.yaml format documentation
4. **Ecoscope index.md** - "What workflow type do you want to build?" landing page
5. **Ecoscope workflow-types/dashboard/skeleton.md** - Runnable skeleton spec.yaml
6. **Ecoscope workflow-types/dashboard/integration-points.md** - Required pieces in context
7. **Ecoscope tutorials/getting-started/run-the-skeleton.md** - Copy, run, see output

### Should Have (Phase 2)
- **Ecoscope workflow-types/dashboard/adding-widgets.md** - Widget customization
- **Ecoscope workflow-types/dashboard/adding-groupers.md** - Filtered views
- **Ecoscope how-to/configure-data-sources.md** - EarthRanger setup
- **Ecoscope how-to/customize-forms.md** - RJSF overrides
- Reference docs for deep dives (gather-dashboard, widget-types, groupers)
- wt-* reference directories for each package

### Nice to Have (Phase 3)
- **Advanced tutorials** (full walkthroughs of events, patrols, subject-tracking examples)
- **File download workflow type** documentation
- Architecture explanations
- Video walkthroughs

---

## Key Documents to Create

### 1. wt-* Landing Page (`docs/index.md`)

```markdown
# wt-* Workflow Framework

A modular framework for compiling and executing typed Python workflows.

## Package Architecture
[ASCII diagram showing: contracts → registry/task/compiler/invokers → runner]

## Quick Start
- [Tutorial: Build Your First Workflow](tutorials/first-workflow.md)
- [Reference: Workflow Specification](reference/spec-yaml.md)

## For Ecoscope Developers
If you're building workflows for the Ecoscope platform, start with the
[Ecoscope Workflow Patterns documentation](link-to-ecoscope-docs).
```

### 2. Spec.yaml Reference (`docs/reference/spec-yaml.md`)

Document the full workflow specification format:
- `id`, `requirements` section
- Task instance format (`id`, `task`, `partial`, `map`, `mapvalues`, `skipif`)
- Task groups (`title`, `type: task-group`, `tasks`)
- Reference syntax (`${{ workflow.task_id.return }}`)
- RJSF overrides

### 3. Ecoscope Dashboard Reference (`docs/reference/gather-dashboard.md`)

Document:
- `gather_dashboard` signature & parameters
- Dashboard JSON schema for web/desktop
- Widget types & their data contracts
- View structure & CompositeFilter keys

---

## Verification Plan

After documentation is written:
1. Have a new developer follow the tutorials without assistance
2. Verify all code examples compile and run
3. Check cross-links resolve correctly
4. Validate against actual spec.yaml files in examples/

---

## MkDocs Setup (Both Repos)

### Configuration (`mkdocs.yml`)
```yaml
site_name: wt-* Workflow Framework  # or "Ecoscope Workflows"
site_url: https://ecoscope.github.io/wt/  # TBD
repo_url: https://github.com/ecoscope/wt
edit_uri: edit/main/docs/

theme:
  name: material
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.expand
    - search.suggest
    - content.code.copy

plugins:
  - search
  - mkdocstrings:  # Auto-generated API docs
      handlers:
        python:
          paths: [src]
          options:
            show_source: true
            show_root_heading: true

nav:
  - Home: index.md
  - Tutorials:
    - tutorials/registering-tasks.md
    - tutorials/first-workflow.md
  - How-to Guides:
    - how-to/compile-workflow.md
    - how-to/run-locally.md
    # ...
  - Reference:
    - reference/packages.md
    - reference/spec-yaml.md
    - wt-contracts:
      - reference/wt-contracts/index.md
      - reference/wt-contracts/registry-models.md
      - reference/wt-contracts/task-models.md
      - reference/wt-contracts/cli-models.md
    - wt-registry:
      - reference/wt-registry/index.md
      - reference/wt-registry/decorator.md
      - reference/wt-registry/registry.md
      - reference/wt-registry/cli.md
    # ... (similar structure for wt-task, wt-compiler, wt-invokers, wt-runner)
  - Explanation:
    - explanation/architecture.md
    # ...

markdown_extensions:
  - admonition        # Callout boxes
  - pymdownx.details  # Collapsible sections
  - pymdownx.highlight
  - pymdownx.superfences
  - pymdownx.tabbed:
      alternate_style: true
```

### Dependencies
```toml
# pyproject.toml or docs/requirements.txt
mkdocs-material >= 9.0
mkdocstrings[python] >= 0.24
```

---

## Tested Code Snippets Strategy

### Directory Structure
```
docs/
├── tutorials/
│   └── first-workflow.md        # Contains <!-- snippet:tutorial_first_workflow -->
└── _snippets/
    └── test_tutorial_first_workflow.py  # Runnable test file
```

### How It Works
1. **Write tests as the source of truth**: Each code example lives in a test file
2. **Include in docs**: Use a custom plugin or manual copy to embed snippets
3. **CI verification**: Run `pytest docs/_snippets/` to ensure examples work

### Example Test File
```python
# docs/_snippets/test_tutorial_first_workflow.py
"""Testable code examples for first-workflow tutorial."""

def test_register_decorator():
    """Example: Basic task registration with @register."""
    # -- snippet: register_basic --
    from wt_registry import register

    @register(description="Add two numbers")
    def add(a: int, b: int) -> int:
        return a + b
    # -- end snippet --

    assert add(1, 2) == 3

def test_task_decorator():
    """Example: Task execution with @task."""
    # -- snippet: task_basic --
    from wt_task import task

    @task
    def multiply(a: int, b: int) -> int:
        return a * b
    # -- end snippet --

    assert multiply.call(a=2, b=3) == 6

def test_spec_yaml_minimal():
    """Example: Minimal spec.yaml parsing."""
    # -- snippet: spec_yaml_minimal --
    from wt_compiler import Spec

    spec = Spec.from_yaml('''
    id: minimal-workflow
    requirements:
      - name: my-tasks
        version: ">=1.0"
    workflow:
      - id: step1
        task: add
        partial:
          a: 1
          b: 2
    ''')
    # -- end snippet --

    assert spec.id == "minimal-workflow"
```

**Note:** `@register` and `@task` are **separate decorators** with different purposes:
- `@register` - Adds function to the global registry for discovery by wt-compiler
- `@task` - Wraps function with execution methods (`.call()`, `.map()`, `.partial()`, etc.)

Tasks used in Ecoscope workflows are typically registered in the ecoscope-workflows-core package and consumed via spec.yaml, not decorated directly in workflow code.

### Snippet Extraction
Use `pytest-examples` or a simple script to:
1. Extract code between `# -- snippet: name --` markers
2. Inject into markdown at `<!-- snippet:name -->` placeholders
3. Run in CI to verify all snippets pass

---

## Dashboard Skeleton (Ecoscope Docs)

The **skeleton.md** is the most important document for onboarding. It provides:

### What the Skeleton Contains
A minimal, runnable `spec.yaml` that includes all required integration points:

```yaml
# skeleton.md will contain something like:
id: my-dashboard-workflow
requirements:
  - name: ecoscope-workflows-core
    version: ">=1.0"

workflow:
  # 1. Required: Workflow metadata
  - name: Workflow Details
    id: workflow_details
    task: set_workflow_details

  # 2. Required: Data source connection
  - name: Data Source
    id: er_client
    task: set_er_connection

  # 3. Required: Time range
  - name: Time Range
    id: time_range
    task: set_time_range

  # 4. Required: At least one data fetch
  - name: Get Events
    id: events
    task: get_events
    partial:
      client: ${{ workflow.er_client.return }}
      time_range: ${{ workflow.time_range.return }}

  # 5. Optional: Groupers for filtered views
  - name: Set Groupers
    id: groupers
    task: set_groupers

  # 6. Required: At least one widget
  - name: Event Count
    id: event_count_widget
    task: create_single_value_widget_single_view
    partial:
      # ...widget config...

  # 7. Required: Terminal task
  - name: Gather Dashboard
    id: dashboard
    task: gather_dashboard
    partial:
      details: ${{ workflow.workflow_details.return }}
      time_range: ${{ workflow.time_range.return }}
      widgets: [${{ workflow.event_count_widget.return }}]
      groupers: ${{ workflow.groupers.return }}
```

### How to Present the Skeleton

1. **Copy this file** - "Here's a working spec.yaml. Copy it."
2. **Run it** - "Run `wt-compiler spec.yaml` to compile, then execute."
3. **See the result** - Screenshot of what the dashboard looks like
4. **Now customize** - Links to adding-widgets.md, adding-groupers.md, etc.

### Integration Points Documentation

The **integration-points.md** explains each required piece in context:

| Integration Point | What It Does | Why It's Required |
|-------------------|--------------|-------------------|
| `workflow_details` | Sets dashboard title/description | Displayed in UI header |
| `set_er_connection` | Configures EarthRanger auth | Data fetching needs credentials |
| `time_range` | Sets temporal bounds | All queries need date filtering |
| `gather_dashboard` | Assembles final output | Web/desktop apps expect this schema |

This is NOT the same as isolated reference docs - it explains pieces **in context of the whole**.

---

## Form Customization Documentation (Ecoscope Docs)

### What to Document

Configuration forms (rendered via React JSON Schema Form) can be customized in several ways:

1. **Field Types** - Different input widgets (dropdown, slider, date picker, etc.)
2. **Field Layout** - Grouping related fields, collapsible sections
3. **Validation** - Required fields, value constraints, conditional visibility
4. **Dynamic Dependencies** - Fields that depend on other field values (e.g., event types filtered by data source)
5. **Styling** - Visual appearance customizations

### Files to Create

| File | Purpose |
|------|---------|
| `how-to/customize-forms.md` | Step-by-step guide: field layout, sections, overrides |
| `reference/form-customization.md` | Complete reference: RJSF override syntax, field types, uiSchema |

### Key Patterns to Document

```yaml
# Example: Dynamic field dependencies
rjsf-overrides:
  properties:
    # Event types dropdown is filtered by selected data source
    get_events_data.properties.event_types.ecoscope:event_type:
      "properties.er_client_name.properties.data_source.properties.name"

# Example: Limiting choices for groupers
  $defs:
    ValueGrouper.oneOf:
      - const: "event_category"
        title: "Event Category"
      - const: "event_type"
        title: "Event Type"

# Example: UI customization
  uiSchema:
    get_events_data.event_types.ui:options.displayLabel: false
```

---

## Implementation Order

### Phase 1: Infrastructure (Both Repos)
1. Add MkDocs configuration (`mkdocs.yml`) to this repo
2. Add documentation dependencies to `pyproject.toml`
3. Create `docs/` directory structure
4. Set up GitHub Actions for docs deployment
5. Create snippet testing infrastructure (`docs/_snippets/`)

### Phase 2: wt-* Core Docs (This Repo)
6. Write landing page (`docs/index.md`) with architecture diagram
7. Write `tutorials/registering-tasks.md` - task creation & registration
8. Write `tutorials/first-workflow.md` with tested snippets
9. Write `reference/spec-yaml.md` - full specification format
10. Write `reference/packages.md` - package overview with roles
11. Auto-generate API docs with mkdocstrings for each package

### Phase 3: Ecoscope Docs - Dashboard Workflow Type (ecoscope-workflows repo)
12. Create parallel MkDocs setup in ecoscope-workflows
13. Write `index.md` - "What workflow type do you want to build?" landing page
14. Write `workflow-types/dashboard/index.md` - What is a dashboard workflow?
15. Write `workflow-types/dashboard/skeleton.md` - **Runnable skeleton spec.yaml**
16. Write `workflow-types/dashboard/integration-points.md` - Required pieces in context
17. Write `tutorials/getting-started/run-the-skeleton.md` - Copy, run, see output

### Phase 4: Ecoscope Docs - Customization
18. Write `workflow-types/dashboard/adding-widgets.md` - Widget customization
19. Write `workflow-types/dashboard/adding-groupers.md` - Filtered views
20. Write `how-to/configure-data-sources.md` - EarthRanger setup
21. Write `how-to/customize-forms.md` - RJSF overrides

### Phase 5: Ecoscope Docs - Reference & Advanced
22. Write `reference/gather-dashboard.md` - Deep dive on terminal task
23. Write `reference/widget-types.md` - Widget API details
24. Write `reference/groupers.md` - Grouper types in detail
25. Write `tutorials/advanced/events-workflow.md` - Production example walkthrough

### Phase 6: Cross-Linking & Polish
26. Add cross-navigation banners and callouts
27. Review all links resolve correctly
28. Have new developer test: copy skeleton → run → see dashboard
29. Add remaining reference docs based on feedback

---

## Files to Create (This Repo)

| File | Purpose | Priority |
|------|---------|----------|
| `mkdocs.yml` | MkDocs configuration | P0 |
| `docs/index.md` | Landing page + architecture | P0 |
| `docs/tutorials/registering-tasks.md` | Task creation & registration tutorial | P0 |
| `docs/tutorials/first-workflow.md` | Build your first workflow tutorial | P0 |
| `docs/reference/spec-yaml.md` | Spec format reference | P0 |
| `docs/reference/packages.md` | Package architecture | P1 |
| `docs/reference/wt-*/` | Per-package reference directories (6 packages) | P1 |
| `docs/_snippets/test_*.py` | Tested code examples | P1 |
| `docs/how-to/compile-workflow.md` | Compilation guide | P1 |
| `docs/explanation/architecture.md` | Design explanation | P2 |

---

## Success Criteria

1. **New developer can run a dashboard** by copying skeleton.md and running it immediately
2. **Skeleton actually works** - tested in CI, produces valid dashboard output
3. **Incremental customization works** - each adding-*.md doc produces a runnable modification
4. **Cross-links work** between wt-* and Ecoscope docs
5. **Deep dives are optional** - developers can ship without reading reference docs
6. **API docs are auto-generated** and stay in sync with code
