# Subprocess Error Handling: Complete Documentation Index

**Purpose:** Prevention strategies and best practices for subprocess-based discovery errors in distributed systems.

**Based on:** Commit 4158ff3 - "Improve error messages when wt-registry CLI is not found"

**Total documentation:** ~2,000 lines across 4 documents

---

## Document Overview

### 1. SUMMARY.md (START HERE)
**Length:** 194 lines | **Time to read:** 5 minutes

Quick reference guide covering:
- The problem and solution overview
- Five key strategies at a glance
- Key takeaways
- Quick start guide for applying patterns
- References to implementation code

**Read this first** to understand the big picture.

---

### 2. ERROR_HANDLING_PATTERNS.md (PATTERNS & IMPLEMENTATION)
**Length:** 606 lines | **Time to read:** 20 minutes

Practical patterns you can apply immediately:

**Sections:**
- Pattern 1: Precondition Checking (before/after comparison)
- Pattern 2: Rich Error Context (structure and examples)
- Pattern 3: Exception Hierarchy (design principles)
- Pattern 4: Three-Layer Error Handling (detailed walkthrough)
- Pattern 5: Subprocess Safety (anti-patterns and best practices)
- Docstring Template (ready-to-use format)
- Code Review Checklist (what to look for)
- Real-world Complete Implementation (copy-paste ready)

**Use this** when implementing subprocess-based code or reviewing others' code.

**Key code examples:**
```python
# Before: Cryptic subprocess error
result = subprocess.run([executable], check=True)

# After: Explicit checks and rich errors
if not executable.exists():
    raise RegistryNotFoundError(
        executable_path=executable,
        requirements=requirements,
    )
result = subprocess.run(
    [str(executable), "--format", "json"],
    capture_output=True,
    text=True,
    check=False,
    timeout=30,
)
if result.returncode != 0:
    raise RegistryExecutionError(...)
```

---

### 3. TESTING_ERROR_PATHS.md (TESTING GUIDE)
**Length:** 610 lines | **Time to read:** 20 minutes

Comprehensive testing strategies:

**Sections:**
- Why Test Error Cases (motivation)
- Test Structure Pattern (four parts: setup, act, assert, verify)
- Complete Error Path Tests (ready-to-copy test classes)
  - Test 1: Missing Executable
  - Test 2: Executable Fails at Runtime
  - Test 3: Invalid Output Format
  - Test 4: Exception Hierarchy
- Test Coverage Checklist (verification)
- Testing Patterns Summary (mocking strategies)
- Common Testing Mistakes (and how to fix them)
- Debugging Failing Tests
- Measuring Test Quality

**Use this** when writing tests for subprocess-based code.

**Key test pattern:**
```python
# Setup: Create conditions for error
mock_tmpdir.return_value.__enter__ = MagicMock(return_value="/fake")

# Act: Call the function
with pytest.raises(RegistryNotFoundError) as exc_info:
    await discover_tasks(...)

# Assert: Verify exception type
error = exc_info.value
assert isinstance(error, RegistryNotFoundError)

# Verify: Check message is helpful
error_msg = str(error)
assert "wt-registry executable not found" in error_msg
assert "package-name" in error_msg  # Context
assert "wt-registry" in error_msg  # Fix suggestion
```

---

### 4. PREVENTION_STRATEGIES.md (COMPREHENSIVE GUIDE)
**Length:** 642 lines | **Time to read:** 30 minutes

Deep dive into prevention and best practices:

**Sections:**
1. Prevention Strategies (5 core strategies)
   - Strategy 1: Explicit Existence Checks
   - Strategy 2: Comprehensive Context in Error Messages
   - Strategy 3: Exception Hierarchy
   - Strategy 4: Pair Error Checking with Input Validation
   - Strategy 5: Test the Unhappy Path

2. Best Practices for Subprocess-Based Discovery Patterns
   - Three-Layer Error Handling
   - Always Capture and Expose Subprocess Output
   - Document All Failure Modes
   - Use Type-Safe Subprocess Patterns
   - Environment-Aware Error Messages

3. Testing Recommendations
   - Test Categories (preconditions, execution, output, hierarchy)
   - Test Coverage Checklist

4. Documentation Improvements
   - Troubleshooting Guide Example
   - Architecture Decision Record
   - Dependency Declaration Best Practices

5. Summary Checklist (quick verification)

**Use this** when designing systems with subprocess-based patterns or educating your team.

**Key strategy: WHAT-WHY-HOW Error Messages**
```
WHAT: "wt-registry executable not found at '/path/to/env/bin/wt-registry'"

CONTEXT: The ephemeral environment was created with:
  - my-package>=1.0.0
  - python>=3.10

WHY: "wt-registry CLI is required for task discovery but was not installed
      because none of the specified packages depend on wt-registry"

HOW: "To fix this issue, ensure your task packages include wt-registry:
      1. Add 'wt-registry' to your package's conda dependencies, OR
      2. Add 'wt-registry' to the requirements in your spec.yaml"
```

---

## Reading Paths

### For Different Audiences

**Developer implementing subprocess-based code:**
1. Read SUMMARY.md (5 min)
2. Read ERROR_HANDLING_PATTERNS.md (20 min)
3. Reference TESTING_ERROR_PATHS.md while writing tests (20 min)
4. Done! You now know the patterns.

**Code reviewer reviewing subprocess code:**
1. Read ERROR_HANDLING_PATTERNS.md > Code Review Checklist (5 min)
2. Check the code against the checklist (varies)
3. Reference other sections as needed

**Team lead / architect:**
1. Read SUMMARY.md (5 min)
2. Read PREVENTION_STRATEGIES.md (30 min)
3. Share with team and use as reference in code reviews

**QA / tester:**
1. Read SUMMARY.md (5 min)
2. Read TESTING_ERROR_PATHS.md (20 min)
3. Use test patterns in your test suite

**Technical writer / documentarian:**
1. Read PREVENTION_STRATEGIES.md > Documentation Improvements (10 min)
2. Use as template for your troubleshooting guides

---

## Key Concepts

### The Five Prevention Strategies

| # | Strategy | Key Idea | Location |
|---|----------|----------|----------|
| 1 | Explicit Existence Checks | Check preconditions before subprocess | PREVENTION_STRATEGIES.md § 1 |
| 2 | Rich Error Context | Include WHAT-WHY-HOW in errors | PREVENTION_STRATEGIES.md § 2 |
| 3 | Exception Hierarchy | Domain-specific exception classes | PREVENTION_STRATEGIES.md § 3 |
| 4 | Input Validation | Validate early, fail fast | PREVENTION_STRATEGIES.md § 4 |
| 5 | Test Unhappy Path | Test every error case | PREVENTION_STRATEGIES.md § 5 |

### The Three-Layer Error Handling

| Layer | When | What to Do | Example |
|-------|------|-----------|---------|
| 1 | Before subprocess | Validate inputs, check preconditions | `if not executable.exists(): raise ...` |
| 2 | During subprocess | Handle execution failure explicitly | `if result.returncode != 0: raise ...` |
| 3 | After subprocess | Validate output matches schema | `RegistryOutput.model_validate_json(...)` |

See: ERROR_HANDLING_PATTERNS.md > Pattern 4 for detailed walkthrough

### The Four-Part Test Pattern

1. **Setup:** Create conditions for the error
2. **Act:** Call the function expecting an exception
3. **Assert:** Verify the correct exception type was raised
4. **Verify:** Check that the error message is helpful

See: TESTING_ERROR_PATHS.md > Test Structure for examples

---

## Cross-References

### Find information by topic:

**Subprocess safety:**
- ERROR_HANDLING_PATTERNS.md > Pattern 5
- PREVENTION_STRATEGIES.md > Best Practice: Always Capture Output
- TESTING_ERROR_PATHS.md > Pattern 3: Mocking Subprocess

**Error messages:**
- ERROR_HANDLING_PATTERNS.md > Pattern 2: Rich Error Context
- PREVENTION_STRATEGIES.md > Strategy 2: Comprehensive Context
- TESTING_ERROR_PATHS.md > Test 1-3: Verify Error Messages

**Exception design:**
- ERROR_HANDLING_PATTERNS.md > Pattern 3: Exception Hierarchy
- PREVENTION_STRATEGIES.md > Strategy 3: Exception Hierarchy
- TESTING_ERROR_PATHS.md > Test 4: Exception Hierarchy Tests

**Testing:**
- TESTING_ERROR_PATHS.md (entire document)
- PREVENTION_STRATEGIES.md > Testing Recommendations
- ERROR_HANDLING_PATTERNS.md > Real-world Complete Implementation

**Documentation:**
- PREVENTION_STRATEGIES.md > Documentation Improvements
- ERROR_HANDLING_PATTERNS.md > Docstring Template
- TESTING_ERROR_PATHS.md > Common Testing Mistakes

**Code review:**
- ERROR_HANDLING_PATTERNS.md > Code Review Checklist
- PREVENTION_STRATEGIES.md > Summary: Prevention Checklist

---

## Real Code Examples

All documentation references actual code from the wt-compiler package:

**Implementation examples:**
- `/wt-compiler/src/wt_compiler/discovery.py` - Complete implementation with three-layer error handling
- `/wt-compiler/src/wt_compiler/exceptions.py` - Exception classes with rich context

**Test examples:**
- `/wt-compiler/tests/test_exceptions.py` - 157 lines of exception testing
- `/wt-compiler/tests/test_discovery_integration.py` - Integration and error path tests

**Commit reference:**
- Commit 4158ff3: "Improve error messages when wt-registry CLI is not found"

---

## Quick Lookup

### I want to...

**Implement subprocess-based code properly**
→ ERROR_HANDLING_PATTERNS.md > Patterns 1-5

**Write tests for subprocess code**
→ TESTING_ERROR_PATHS.md > Complete Error Path Tests

**Review someone's subprocess code**
→ ERROR_HANDLING_PATTERNS.md > Code Review Checklist

**Design exception classes**
→ ERROR_HANDLING_PATTERNS.md > Pattern 3: Exception Hierarchy

**Write helpful error messages**
→ PREVENTION_STRATEGIES.md > Strategy 2: Comprehensive Context
→ ERROR_HANDLING_PATTERNS.md > Pattern 2: Rich Error Context

**Debug failing tests**
→ TESTING_ERROR_PATHS.md > Debugging Tests That Fail

**Measure test quality**
→ TESTING_ERROR_PATHS.md > Measure Test Quality

**Learn what not to do**
→ TESTING_ERROR_PATHS.md > Common Testing Mistakes
→ ERROR_HANDLING_PATTERNS.md > Anti-patterns

**Understand the problem this solves**
→ SUMMARY.md > The Problem & Solution

**Understand why subprocess-based patterns**
→ PREVENTION_STRATEGIES.md > Documentation Improvements > Architecture Decision Record

---

## Statistics

| Document | Lines | Sections | Code Examples | Tests |
|----------|-------|----------|----------------|-------|
| SUMMARY.md | 194 | 7 | 2 | — |
| ERROR_HANDLING_PATTERNS.md | 606 | 10 | 15+ | — |
| TESTING_ERROR_PATHS.md | 610 | 12 | 20+ | 4 complete test classes |
| PREVENTION_STRATEGIES.md | 642 | 15 | 10+ | — |
| **Total** | **2,052** | **44** | **45+** | **Test patterns throughout** |

---

## How These Documents Were Created

These comprehensive guides were generated by analyzing:
1. The actual problem (cryptic subprocess errors)
2. The implemented solution (commit 4158ff3)
3. Real code in wt-compiler
4. Production-grade test examples
5. Best practices from distributed systems research

Each document is self-contained but cross-references others for different depths of coverage.

---

## Next Steps

1. **Start here:** Read SUMMARY.md (5 minutes)
2. **Learn patterns:** Read ERROR_HANDLING_PATTERNS.md (20 minutes)
3. **Understand testing:** Read TESTING_ERROR_PATHS.md (20 minutes)
4. **Deep dive:** Read PREVENTION_STRATEGIES.md (30 minutes)
5. **Apply:** Use the patterns and checklists in your own code
6. **Share:** Use these documents to educate your team

---

## Version

Created: January 15, 2026
Based on: wt-compiler commit 4158ff3
Relevant branch: initial
Git status: Clean

---

## Document Purpose

These documents serve as:
- **Educational material** for team members learning subprocess error handling
- **Reference guide** for implementing and reviewing subprocess-based code
- **Testing template** for comprehensive error path coverage
- **Best practices** documentation for prevention of similar issues
- **Institutional knowledge** capturing lessons learned from production systems

The goal: Make subprocess-based discovery robust, user-friendly, and maintainable.
