# Plan: Programmatic Skeleton Strategy for wt-* Documentation

## Context

The DOCS_PLAN.md proposes a "skeleton first" documentation approach where developers copy a working spec.yaml to get started. This plan enhances that strategy with a programmatic, CLI-driven approach that:
- Prevents drift between docs and working code
- Supports multiple skeleton flavors (events, patrols, etc.)
- Keeps wt-* packages generic via extension mechanism
- Provides a unified CLI experience

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         wt-cli (new package)                            │
│  Entry point: `wt`                                                      │
│  Subcommands: init, compile, registry                                   │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ skeleton_registry.py                                              │  │
│  │ - Discovers providers via entry_points("wt.skeleton_providers")   │  │
│  │ - Lists skeletons, delegates generation to providers              │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         │ delegates          │ delegates          │ discovers
         ▼                    ▼                    ▼
   ┌──────────┐        ┌─────────────┐     ┌─────────────────────────┐
   │wt-registry│       │ wt-compiler │     │ Skeleton Providers      │
   │   CLI    │        │    CLI      │     │ (via entry points)      │
   └──────────┘        └─────────────┘     └─────────────────────────┘
                                                     │
                                                     │
                              ┌───────────────────────────────────────┐
                              │ ecoscope-workflows-core               │
                              │                                       │
                              │ skeletons/                            │
                              │ ├── provider.py                       │
                              │ └── templates/                        │
                              │     ├── dashboard-events/             │
                              │     │   ├── spec.yaml                 │
                              │     │   ├── test-cases.yaml           │
                              │     │   └── layout.json               │
                              │     ├── dashboard-patrols/            │
                              │     └── dashboard-subject-tracking/   │
                              │                                       │
                              │ pyproject.toml:                       │
                              │ [project.entry-points."wt.skeleton_providers"]
                              │ ecoscope = "...skeletons:Provider"    │
                              └───────────────────────────────────────┘
```

## CLI User Experience

```bash
# List all available skeletons from all providers
wt init --list
# Output:
#   ecoscope/dashboard-events       Dashboard workflow for EarthRanger events
#   ecoscope/dashboard-patrols      Dashboard workflow for patrol data
#   ecoscope/dashboard-subjects     Dashboard for subject tracking

# Generate skeleton (interactive if no args)
wt init

# Generate specific skeleton
wt init ecoscope/dashboard-events

# Generate with customization
wt init ecoscope/dashboard-events --name my-events-dashboard --output-dir ./workflows/

# Generated files:
#   ./workflows/my-events-dashboard/
#   ├── spec.yaml
#   ├── test-cases.yaml
#   └── layout.json
```

## Implementation Plan

### Phase 1: wt-cli Package & Unified CLI

**New package: wt-cli/**
```
wt-cli/
├── src/wt_cli/
│   ├── __init__.py
│   ├── main.py              # `wt` entry point, Click-based
│   ├── commands/
│   │   ├── init.py          # `wt init` - skeleton generation
│   │   ├── compile.py       # `wt compile` - delegates to wt-compiler
│   │   └── registry.py      # `wt registry` - delegates to wt-registry
│   └── skeleton_registry.py # Provider discovery & management
├── tests/
├── pyproject.toml
└── README.md
```

**Key files to create:**

1. `wt-cli/src/wt_cli/main.py` - Click CLI with subcommands
2. `wt-cli/src/wt_cli/skeleton_registry.py` - Entry point discovery
3. `wt-cli/src/wt_cli/commands/init.py` - Skeleton generation logic

**pyproject.toml entry point:**
```toml
[project.scripts]
wt = "wt_cli.main:cli"
```

### Phase 2: Skeleton Provider Protocol (wt-contracts)

**Add to wt-contracts:**
```python
# wt-contracts/src/wt_contracts/skeleton.py

from typing import Protocol
from pathlib import Path
from pydantic import BaseModel

class SkeletonVariable(BaseModel):
    """A customizable variable for a skeleton template."""
    name: str                  # Variable name in templates, e.g., "workflow_name"
    prompt: str                # Prompt shown to user, e.g., "Workflow name"
    default: str | None        # Default value, or None if required
    description: str | None    # Help text for interactive mode


class SkeletonMetadata(BaseModel):
    """Metadata for a skeleton template."""
    id: str                    # e.g., "dashboard-events"
    name: str                  # e.g., "Dashboard - Events"
    description: str
    files: list[str]           # e.g., ["spec.yaml", "test-cases.yaml", "layout.json"]
    variables: list[SkeletonVariable]  # Customizable variables with prompts & defaults


class GeneratedFiles(BaseModel):
    """Result of skeleton generation."""
    output_dir: Path
    files: list[Path]


class SkeletonProvider(Protocol):
    """Protocol for skeleton providers."""

    @property
    def name(self) -> str:
        """Provider namespace, e.g., 'ecoscope'."""
        ...

    @property
    def description(self) -> str:
        """Provider description."""
        ...

    def list_skeletons(self) -> list[SkeletonMetadata]:
        """List available skeletons."""
        ...

    def generate(
        self,
        skeleton_id: str,
        output_dir: Path,
        context: dict[str, str]
    ) -> GeneratedFiles:
        """Generate skeleton files."""
        ...
```

### Phase 3: Ecoscope Skeleton Provider (ecoscope-workflows-core)

**In ecoscope-workflows-core repo:**
```
src/ecoscope_workflows/
└── skeletons/
    ├── __init__.py
    ├── provider.py           # EcoscopeSkeletonProvider class
    └── templates/
        ├── dashboard-events/
        │   ├── spec.yaml
        │   ├── test-cases.yaml
        │   └── layout.json
        ├── dashboard-patrols/
        │   └── ...
        └── dashboard-subject-tracking/
            └── ...
```

**Entry point registration:**
```toml
# ecoscope-workflows-core/pyproject.toml
[project.entry-points."wt.skeleton_providers"]
ecoscope = "ecoscope_workflows.skeletons:EcoscopeSkeletonProvider"
```

### Phase 4: Documentation Updates

**Changes to DOCS_PLAN.md:**

1. **wt-* docs: Add wt-cli reference**
   ```
   docs/reference/wt-cli/
   ├── index.md           # Package overview
   ├── init.md            # `wt init` command reference
   └── extension.md       # How to create skeleton providers
   ```

2. **Ecoscope docs: Update skeleton approach**
   - Primary: `wt init ecoscope/dashboard-events` command
   - Secondary: Link to raw template files for transparency
   - Remove copy-paste as primary method

3. **Ecoscope docs: skeleton.md pages**
   ```markdown
   ## Quick Start

   ```bash
   wt init ecoscope/dashboard-events --name my-workflow
   cd my-workflow
   wt compile spec.yaml
   ```

   ## What's Generated

   | File | Purpose |
   |------|---------|
   | spec.yaml | Workflow definition |
   | test-cases.yaml | Test parameters |
   | layout.json | Dashboard grid layout |

   ## Template Source

   [View the template source →](link-to-github)

   ```yaml
   # spec.yaml (included from template)
   ... actual template content ...
   ```
   ```

4. **CI validation**
   - Test that `wt init` generates valid files
   - Test that generated spec.yaml compiles successfully
   - Test that docs include statements resolve

## Files to Modify

### This repo (wt-*)

| File | Action | Description |
|------|--------|-------------|
| `wt-cli/` | Create | New package directory |
| `wt-cli/pyproject.toml` | Create | Package config with `wt` entry point |
| `wt-cli/src/wt_cli/main.py` | Create | Click CLI main entry point |
| `wt-cli/src/wt_cli/commands/init.py` | Create | `wt init` implementation |
| `wt-cli/src/wt_cli/skeleton_registry.py` | Create | Provider discovery |
| `wt-contracts/src/wt_contracts/skeleton.py` | Create | SkeletonProvider protocol |
| `wt-contracts/src/wt_contracts/__init__.py` | Modify | Export skeleton types |
| `plans/DOCS_PLAN.md` | Modify | Update skeleton strategy section |

### ecoscope-workflows-core repo (separate)

| File | Action | Description |
|------|--------|-------------|
| `src/ecoscope_workflows/skeletons/` | Create | Skeleton provider directory |
| `src/ecoscope_workflows/skeletons/provider.py` | Create | Provider implementation |
| `src/ecoscope_workflows/skeletons/templates/` | Create | Template files |
| `pyproject.toml` | Modify | Add entry point registration |

## Verification

1. **Unit tests for wt-cli**
   - Provider discovery works
   - Skeleton listing works
   - Generation produces expected files

2. **Integration test**
   - Install wt-cli + ecoscope-workflows-core
   - Run `wt init --list` shows ecoscope skeletons
   - Run `wt init ecoscope/dashboard-events`
   - Run `wt compile spec.yaml` on generated files
   - Verify compilation succeeds

3. **Documentation validation**
   - Docs include statements resolve
   - Example commands in docs work
   - Links to template source work

## Design Decisions (Resolved)

1. **Template variables**: Each skeleton defines its own customizable variables in metadata
   - Stored in skeleton metadata, not hardcoded
   - Examples: name, description, data_source, time_range_default, etc.

2. **Interactive mode**: Yes, full wizard
   - `wt init` (no args) prompts for skeleton selection
   - Then prompts for all skeleton-defined variables
   - `wt init <skeleton>` skips selection, prompts only for variables
   - `wt init <skeleton> --name foo --var bar` non-interactive with all args

3. **Template format**: Jinja2
   - Consistent with wt-compiler's existing template infrastructure
   - Supports conditionals for optional sections
   - Variables accessed as `{{ name }}`, `{{ description }}`, etc.

4. **Sidecar files**: Determined per-skeleton in template directory
   - Each skeleton's template directory contains all files to generate
   - Common examples: spec.yaml, test-cases.yaml, layout.json
   - Provider scans directory to determine file list

## Remaining Questions (for implementation)

1. What interactive prompt library to use? (click prompts, questionary, inquirer?)
2. Should providers support skeleton inheritance/composition in the future?
