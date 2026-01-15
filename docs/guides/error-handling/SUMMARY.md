# Subprocess-Based Discovery: Prevention & Best Practices Summary

## Generated Documentation

This directory now contains comprehensive guidance on preventing and handling errors in subprocess-based discovery patterns, based on the real-world fix to wt-compiler's task discovery mechanism.

### Documents

1. **PREVENTION_STRATEGIES.md** (Primary Document)
   - Comprehensive prevention strategies for subprocess-based discovery errors
   - Five core strategies with implementation examples
   - Best practices for error handling in subprocess patterns
   - Three-layer error handling architecture
   - Testing recommendations and checklist
   - Documentation improvements and examples

2. **ERROR_HANDLING_PATTERNS.md** (Quick Reference)
   - Side-by-side before/after code comparisons
   - Five actionable error handling patterns
   - Exception hierarchy design
   - Subprocess safety checklist
   - Docstring templates
   - Real-world complete implementation example
   - Code review checklist for subprocess code

3. **TESTING_ERROR_PATHS.md** (Testing Guide)
   - Why and how to test error cases
   - Four-part test structure pattern
   - Complete test examples for each error type
   - Test coverage checklist
   - Common testing mistakes and fixes
   - How to debug failing tests
   - Coverage measurement techniques

## The Problem & Solution

### Original Issue
Users received cryptic errors when the wt-registry CLI wasn't available in ephemeral environments:
```
CalledProcessError: Command [...] returned non-zero exit status 127
```

Users couldn't understand:
- What dependency was missing?
- Where to look to fix it?
- Why isn't the thing that should exist there?

### The Fix
Added explicit existence checks and domain-specific exceptions with actionable error messages:
```
RegistryNotFoundError: wt-registry executable not found at '...'

The ephemeral environment was created with the following packages:
  - my-tasks>=1.0.0

The wt-registry CLI is required for task discovery but was not installed
because none of the specified packages depend on wt-registry.

To fix this issue, ensure your task packages include wt-registry as a dependency:
  1. Add 'wt-registry' to your package's conda dependencies, OR
  2. Add 'wt-registry' to the requirements in your spec.yaml
```

Users now understand:
- What the problem is (executable not found)
- Why it happened (dependency is missing)
- What to do about it (add the dependency)

## Key Strategies

### 1. Explicit Precondition Checks
Check that all required files/executables exist BEFORE calling subprocess, rather than hoping subprocess succeeds and catching cryptic errors.

### 2. Rich Error Context
Include (1) what failed, (2) why it failed, and (3) how to fix it in error messages.

### 3. Exception Hierarchy
Create domain-specific exceptions that mirror your problem domain, not Python's built-ins.

### 4. Three-Layer Error Handling
- **Layer 1:** Validate inputs before expensive operations
- **Layer 2:** Handle subprocess execution failures with captured output
- **Layer 3:** Validate subprocess output matches schema

### 5. Comprehensive Testing
Test every error path, not just the happy path. Verify error messages are actually helpful.

## Implementation References

See real code examples in the wt-compiler package:

**File:** `/wt-compiler/src/wt_compiler/discovery.py`
- Lines 85-90: Explicit executable existence check
- Lines 93-107: Safe subprocess call with explicit error handling
- Lines 109-148: Output validation and parsing

**File:** `/wt-compiler/src/wt_compiler/exceptions.py`
- Lines 40-86: RegistryNotFoundError with rich context
- Lines 88-148: RegistryExecutionError with subprocess output

**File:** `/wt-compiler/tests/test_exceptions.py`
- Lines 28-84: Tests for RegistryNotFoundError message quality
- Lines 86-158: Tests for RegistryExecutionError message quality

**File:** `/wt-compiler/tests/test_discovery_integration.py`
- Lines 303-368: Integration tests for error paths
- Lines 309-331: Test that missing executable error is descriptive
- Lines 337-368: Test that execution failure error includes stderr

## Quick Start: Applying These Patterns

### For Your Project

If you're implementing subprocess-based discovery or similar patterns:

1. **Read:** ERROR_HANDLING_PATTERNS.md for the five key patterns
2. **Design:** Exception hierarchy that matches your problem domain
3. **Implement:** Three-layer error handling (preconditions, execution, output)
4. **Test:** Follow the patterns in TESTING_ERROR_PATHS.md
5. **Document:** Use the docstring templates from ERROR_HANDLING_PATTERNS.md

### For Code Review

Use the checklist in ERROR_HANDLING_PATTERNS.md (Code Review Checklist) to review any subprocess-based code.

## Key Takeaways

### What Makes a Good Error Message

✓ Clear problem statement: "wt-registry executable not found"
✓ Relevant context: What packages were installed
✓ Root cause: Why the problem occurred
✓ Actionable solution: Exactly what to do to fix it

### What Makes Good Error Handling

✓ Preconditions checked before expensive operations
✓ Domain-specific exceptions with rich attributes
✓ Exception hierarchy enables selective catching
✓ Subprocess output captured and included in errors
✓ All error cases tested, not just happy path

### What Makes Good Testing

✓ Happy path tests (the function works correctly)
✓ Unhappy path tests (each error case is tested)
✓ Message quality tests (error messages are helpful)
✓ Attribute tests (exception stores context for programmatic access)
✓ Hierarchy tests (exception inheritance works correctly)

## The Problem This Solves

**Without these patterns:**
- Users get cryptic exit codes from subprocess failures
- Support team spends time explaining what went wrong
- Error messages aren't actionable
- Each user has to figure out the fix themselves

**With these patterns:**
- Users get clear explanations of what went wrong
- Users get actionable steps to fix the problem
- Support load decreases
- Users can self-serve

## Commit Reference

This documentation was created to support commit **4158ff3**: "Improve error messages when wt-registry CLI is not found"

The commit added:
- Explicit `Path.exists()` checks before subprocess calls
- Two new exception classes: `RegistryNotFoundError` and `RegistryExecutionError`
- Comprehensive tests for all error paths
- User-friendly error messages with fix suggestions

## Next Steps

1. **Review:** Read ERROR_HANDLING_PATTERNS.md for patterns you can apply
2. **Test:** Use the test patterns from TESTING_ERROR_PATHS.md in your code
3. **Document:** Add WHAT-WHY-HOW error messages to your exceptions
4. **Share:** Use PREVENTION_STRATEGIES.md to educate your team

---

**Question:** Why are subprocess-based patterns used in wt-compiler?

See PREVENTION_STRATEGIES.md > Documentation Improvements > Architecture Decision Record for the design rationale.

**Question:** How do I add these patterns to my code?

See ERROR_HANDLING_PATTERNS.md > Pattern 1-5 for step-by-step implementation examples.

**Question:** How do I test error paths effectively?

See TESTING_ERROR_PATHS.md > Complete Error Path Tests for concrete examples you can copy.
