# Caching

`wt` can cache the result of every step in a compiled workflow. A step that has
already run with the same code and the same inputs is not run again — its
stored result is returned instead.

This page describes the behaviour and the contracts. For implementation detail,
follow the links to the source modules.

---

## What it is, and when to use it

The step cache is **content-addressed**: a step is keyed by the code it runs and
by the exact content of everything it receives, and its result is stored under
the digest of that content. Two steps that compute the same value share one
stored payload.

It is **opt-in at compile time**:

```bash
wt-compiler compile --spec spec.yaml --with-caching
```

Without the flag, nothing about the generated DAG changes. With it, every step
is wrapped in `.cached(...)` — and the wrapping is still **inert** at run time
unless `WT_CACHE__STORE` names a store, so a cached build runs exactly like an uncached
one by default.

Three limits are worth knowing up front:

- **Sequential DAGs only.** An async method hands back a future, which has no
  stored form, so async runs report every step as `uncacheable`.
- **Mocked tasks are never cached.** They return canned fixtures; storing one
  under an identity that claims to describe real work would be a lie.
- **A task must come from an installed distribution.** The cache pins code to a
  version, and a function that belongs to no distribution cannot be pinned, so
  it is not cached. See [Gotchas](#gotchas).

Use it when steps are expensive and deterministic — fetching data, reshaping
frames, rendering — and when you re-run similar workflows often. Do not use it
to skip side effects; see [`no-cache`](#tags-that-matter).

---

## How a key is built

A step's key is a digest over six things. Any one of them moving is a miss.

| Part | Where it comes from |
|------|---------------------|
| **Code identity** | the task's distribution and its dependencies (below) |
| **Return structure** | a digest of the step's declared return structure, so a return type that changes shape misses even when no version moved |
| **`fixed_inputs`** | compile-time hash of the arguments and `skipif` conditions bound in `spec.yaml` |
| **`upstream_inputs`** | the **output digests** of the steps feeding this one |
| **`env`** | the values of the environment variables bound to arguments |
| **`params`** | the run's parameters for this step |

Plus `WT_CACHE__SCOPE`, but only for [io-tagged](#tags-that-matter) steps —
which are never served while it is unset.

### Code identity

Four pieces, combined by
[`task_identity`](https://github.com/wildlife-dynamics/wt/blob/main/wt-task/src/wt_task/cache/_key.py):

- the **installed version** of the distribution the task function comes from;
- a **dependency-closure fingerprint** — a digest of every installed
  distribution transitively reachable from it. Without this, upgrading pandas
  or geopandas under an unchanged task library would move no key and serve
  results the new code would not produce;
- the **signature hash**, over the task's module, function name and JSON
  schema, so a signature change invalidates within a release;
- **`WT_CACHE__EPOCH`**, the manual invalidator.

Only *installed* requirements are followed, so a missing optional dependency is
skipped rather than being an error. An extra counts as in use when all of its
own requirements are installed — which picks up `ecoscope[platform]` in a
platform environment and leaves `[gcp]` out of a local one.

The closure, rather than the workflow's lock hash, because every workflow
resolves its own environment: a lock hash would give each workflow a private
cache and nothing would ever be shared.

### Early cutoff

A step contributes the **digest of its output** to its dependents' keys, not its
own key. That is what makes a re-run cheap: a step whose own key moved will
execute, but if it produces the same data as last time, every step below it
still hits.

This is the common case for a source read under a new token, or for a step whose
changed argument does not affect what it returns.

### No workflow or step identity in the key

Keys contain no workflow id, no step id, and no upstream step *names* — only
content. Two workflows that call the same task with the same inputs share one
entry, however their specs happen to name things. Renaming a step moves nothing.

### Uncacheability propagates

If a step cannot be cached, every step below it is uncacheable too: a key that
omitted an unknown input would collide across genuinely different runs. The
reports say which step started it.

---

## For task authors: declaring how results are cached

Whether a step can be cached is decided by **the task's return type**. wt walks
the annotation once, when the registry is serialized, and the compiler records
what it found. There is no runtime value inspection and no global registry of
codecs.

The walk lives in
[`wt_contracts.codecs`](https://github.com/wildlife-dynamics/wt/blob/main/wt-contracts/src/wt_contracts/codecs.py).

### What already works

These need no annotation at all:

- JSON-native scalars — `int`, `float`, `str`, `bool`, `None`, `Literal[...]`
- `bytes`, `pathlib.Path`, `pydantic_core.Url`, any `enum.Enum` subclass
- `list[X]`, `tuple[A, B]`, `tuple[X, ...]`, `dict[K, V]`, unions — if every
  member resolves
- `@dataclass` types — if every field resolves and none is `init=False`

```python
@register(title="Count rows", description="...")
def count_rows(path: Path) -> int: ...          # cacheable

@register(title="Split", description="...")
def split(path: Path) -> dict[str, list[Path]]: ...   # cacheable, structurally
```

### What does not, and why

Anything the walk does not recognise resolves to "not cacheable", and that
propagates: a union with one unknown arm, a list of unknown, a dataclass with
one unknown field are all uncacheable. `Any`, bare `list`/`dict`, `object`,
`TypedDict` and a plain `BaseModel` are all unknown.

This is deliberately strict. The walker is a third type interpreter beside
pydantic and pandera, and a wrong guess silently mis-encodes a result.

### Declaring a codec for a type you own

Two ways, depending on whether you own the class.

**On a type alias** — the right place for a third-party type:

```python
from typing import Annotated
from wt_contracts import CodecRef

DataFrame = Annotated[pd.DataFrame, CodecRef("mylib.codecs:FRAME")]
```

Every return annotated with the alias is now cacheable, at the cost of one
edit. `CodecRef` anywhere in an `Annotated` overrides the walk below it, so it
also works to say "trust me, this loosely-typed return really is JSON":
`Annotated[dict[str, Any], CodecRef("wt_task.cache:JSON")]`.

**On a class you own** — via the `Cacheable` mixin:

```python
from pydantic import BaseModel
from wt_contracts import Cacheable

class ModelCodec(Cacheable):
    __wt_codec__ = "mylib.codecs:model_codec"

class TimeRange(BaseModel, ModelCodec):
    since: datetime
    until: datetime
```

A mixin rather than a base class, so one mechanism covers pydantic models,
dataclasses and enums and composes with whatever base a class already has. The
dunder name keeps it out of pydantic's field collection.

The ref is `"pkg.mod:NAME"`, naming either a `Codec` or — when the structure
also names a class — a callable `(type) -> Codec`. Refs are strings, resolved by
`importlib` at run time, so wt-contracts never imports a codec.

### The model round-trip check

A pydantic model declaring `__wt_codec__` is checked once, at serialization
time, for things that break a `model_dump` → `model_validate` round trip:
private attributes, a `model_serializer` or `field_serializer`, or any field
with `exclude=True`. Failing the check raises `CodecDeclarationError` naming the
field.

The check guards the *generic* dump/validate codec. A codec that encodes the
model itself opts out:

```python
class GrouperCodec(Cacheable):
    __wt_codec__ = "mylib.codecs:grouper_codec"
    __wt_codec_owns_round_trip__ = True
```

A declaration error does not break a non-caching compile: wt-registry carries it
as data (`cache_structure_error`) and `--with-caching` turns it into an error.

### Codecs and trees

A **`Codec`** encodes one family of leaf values: bytes in, bytes out, plus a
`digest` that must be stable across encodings. `digest` is separate from
`encode` because an unstable digest silently invalidates every downstream entry
on every run — parquet is not byte-stable, so a frame codec digests a canonical
form rather than the bytes it writes.

A **`Tree`** is the codec for a whole step: one encoder, one digest rule, one
union-arm rule, built from the declared structure with the leaf codecs resolved
into it. A bare frame is a one-leaf tree. A tree can also be a leaf of another
tree, which is how a library declares a codec for a container type it owns.

A codec may decline a value by raising `Undigestible` — an unhashable cell, a
subclass an exact codec does not cover. The step then runs and records itself
`refused`; nothing fails.

Both live in
[`wt_task.cache`](https://github.com/wildlife-dynamics/wt/blob/main/wt-task/src/wt_task/cache/).
Real-world examples: ecoscope's `FRAME` (parquet, with a canonical digest) and
its class-parameterized `model_codec` and `grouper_codec`.

---

## Tags that matter

Two `@register` tags change how a step is cached.

### `no-cache`

A stored result may never be served for this task. It always executes — but it
still digests and promotes its output, so **everything below it keeps hitting**.
The claim stays about this task rather than silently disabling its whole subtree.

Use it for side effects: a task that persists a file has to run for the file to
exist, even when its return value would have been identical.

### `io`

The step reads the world, so `WT_CACHE__SCOPE` is folded into its key. Derived
steps are *not* scoped: they are pure functions of their input digests, and
nobody can reach one without already holding the same content. A fresh token
therefore costs one source refetch, not a whole cold run.

With `WT_CACHE__SCOPE` unset, an io step is **never served or stored**: two
tenants sharing a connection name would otherwise share its key. It still runs
and promotes its digest, so the steps below it keep hitting on identical
content. Set any scope — `local` will do on a workstation — to cache sources.

Getting the tag wrong is the same class of error as a missing `no-cache`, and
is found the same way — [verify mode](#verify-mode) against a second principal.

---

## Running and operating

| Variable | What it does |
|----------|--------------|
| `WT_CACHE__STORE` | Store location: a local path or an object-store URL. Unset means the cache is inert and every step runs. A remote URL needs `wt-task[cache]` (obstore). |
| `WT_CACHE__EPOCH` | Manual invalidator, mixed into every key. For when a version cannot move. |
| `WT_CACHE__SCOPE` | Folded into io-tagged steps' keys. Separates principals that share a connection name. Unset, io steps always refetch. |
| `WT_CACHE__IO_TTL` | How long an io-tagged step's stored result may be served: `forever` (default), `never` / `0` to always refetch, or a duration — `90`, `45s`, `30m`, `1h`, `7d`. Derived steps never expire. |
| `WT_CACHE__VERIFY` | Re-run everything and compare against what is stored, without serving or writing. See below. |
| `WT_CACHE__STRICT` | Raise on a codec declaration that will not resolve, a setting that will not parse, or a stored payload that will not decode, instead of degrading. |

### Where settings come from

All six are fields of one `CacheSettings` model, read **once per run** — a DAG
does not re-read the environment per step, and changing a variable mid-run
takes effect at the next run, not the next step.

Four sources, highest precedence first:

1. explicit arguments (`run_scope(settings=CacheSettings(...))`)
2. environment variables
3. a `.env` file in the working directory
4. a `[tool.wt.cache]` table in `pyproject.toml` in the working directory

The two file sources are for local development; a deployment sets environment
variables. Both use the same field names:

```bash
# .env
WT_CACHE__STORE=/tmp/wt-cache
WT_CACHE__EPOCH=dev-7
WT_CACHE__STRICT=1
```

```toml
# pyproject.toml
[tool.wt.cache]
store = "/tmp/wt-cache"
io_ttl = "30m"
strict = true
```

These are **runtime settings, not authoring settings**. There is deliberately
no way to set them from `spec.yaml`: a workflow author should not be deciding
another deployment's freshness policy or where its store lives.

Recommended settings:

| | `WT_CACHE__EPOCH` | `WT_CACHE__STRICT` | `WT_CACHE__SCOPE` | `WT_CACHE__IO_TTL` |
|---|---|---|---|---|
| **Dev** | the task checkout's git sha, or bump by hand | `1` | any value, e.g. `local`, to cache sources | — |
| **CI** | — | `1` | any value, to cache sources | — |
| **Prod** | the **task-library** build (image layer or lock hash) | unset | per principal, e.g. server + `sha256(token)` | a duration, for anything expected to be current |

Two of those deserve the reasoning:

- **The epoch comes from the task library, not the workflow image.** An
  image-digest epoch flushes every environment on every deploy, and two
  workflows shipping the same library as different images would never share an
  entry.
- **Strict in CI, degrade in production.** The environment that compiled a spec
  and the one running it can skew, and caching must never fail a run. Locally
  and in CI you want the opposite: a declaration that stopped resolving should
  shout.

Give the store a lifecycle policy on both `keys/` and `content/` from day one —
a dangling key already reads as a miss. wt has no garbage collection of its own.

### Freshness for io steps

`WT_CACHE__IO_TTL` bounds how old an io-tagged step's stored result may be
before it is refetched. It applies to io steps only: a derived step is a pure
function of its input digests, so the same key cannot describe different
content and its age says nothing.

Unset, or `forever`, serves indefinitely — the default, and the behaviour
before this existed. A duration (`30m`, `1h`, `7d`, or bare seconds) serves
while the entry is younger than that. Age is judged from the entry, before the
payload is read, so an expired entry costs nothing to reject.

`never` (or `0`) never serves an io step — but it still digests, promotes and
**writes** the fresh entry. That makes it the force-refresh recipe: one run
with `WT_CACHE__IO_TTL=never` refreshes every source, and the next run with a
TTL uses what it wrote.

An expired step re-executing does not mean its subtree does. [Early
cutoff](#early-cutoff) still applies: if the refetch yields the same content,
every step below it hits.

A value that is not a duration warns once and is treated as `never` — a
refetch costs time, but serving something older than you asked for is the
failure that matters. Under `WT_CACHE__STRICT=1` it raises instead. The same
holds for any setting that will not parse, each falling back to whatever costs
time rather than risking a wrong serve: `verify` to on, `scope` to unset, and
an unreadable `store` or `epoch` — which may have been the invalidation you
needed — to an inert cache. `strict` is resolved on its own first, so a broken
neighbour cannot hide it; if `strict` itself will not parse, it reads as off.

### Verify mode

With `WT_CACHE__VERIFY=1` every step executes, nothing is served and nothing is
written, and each result is compared against what is stored. A mismatch warns
with `CacheMismatchWarning`, naming the task instance.

This is the empirical way to find tasks that need `no-cache`: a mismatch is
proof that identical declared inputs produced different output.

---

## Reports

Two reports, answering two different questions.

### At compile time

`DagCompiler.cache_report()` returns one row per step — `task_instance_id`,
`status`, `reason` — and `wt-compiler compile --with-caching` prints every step
with its status, the reason for any that is not cacheable, and a summary count.

| Status | Meaning |
|--------|---------|
| `cacheable` | Can be served |
| `unservable` | `no-cache` tag: always runs, dependents still hit |
| `uncacheable` | No codec for the return type, a bad declaration, or an uncacheable upstream |

This is a claim about *declared types*, computed before anything runs.

### At run time

A package compiled `--with-caching` writes `cache-report.json` into the same
results store as `result.json`, which itself carries no cache information:

```json
{
  "status": "failed",
  "error": "Task instance 'broken' raised ValueError('boom')",
  "failed_step": "broken",
  "summary": {"hit": 1, "miss": 1},
  "settings": {
    "store": {"configured": true, "scheme": "gs"},
    "io_ttl": "1800s",
    "verify": false,
    "strict": false,
    "epoch_set": true,
    "scope_set": true
  },
  "steps": {
    "source": {"digest": "json/v1/3f2a…", "outcome": "hit", "reason": null},
    "shaped": {"digest": "json/v1/9c41…", "outcome": "miss", "reason": null}
  }
}
```

- **`status`** is `completed` or `failed`. The report is written **even when the
  run fails**, and is written before `result.json`: a failed run's report holds
  every row recorded up to the failure, the error, and — when the error names
  one, as every generated step's does — the `failed_step`. Writing the report
  never raises, so it cannot replace the run's own result or error.
- **`summary`** counts the rows by outcome.
- **`settings`** is redacted: whether a store is configured and its scheme, but
  never its URL, which can name a bucket path; whether `epoch` and `scope` are
  set, but never their values, since a scope is often derived from a token.
- **`steps`** has one row per step that recorded an outcome, keyed by
  task-instance id.

In-process, `wt_task.cache.run_report()` returns the `steps` rows alone, and
`cache_report()` the whole document — inside an open `run_scope` it describes
the run so far, with status `running`.

| Outcome | Meaning |
|---------|---------|
| `hit` | Served from the store; the step did not execute |
| `miss` | Executed, and the result was stored |
| `expired` | An io step whose entry was older than `WT_CACHE__IO_TTL`, or that is set to always refetch. Executed and overwritten; the digest is still promoted |
| `unservable` | `no-cache`, or an io step with `WT_CACHE__SCOPE` unset: executed, digested and promoted, not stored |
| `uncacheable` | No codec, unpinnable distribution, or an uncacheable upstream |
| `refused` | A codec declined the value, or a declared ref would not import |
| `inert` | No store configured |

A declared type can claim cacheable and still be refused at run time — an exact
codec handed a subclass, a union with no matching arm, an unhashable cell. That
only shows here.

---

## On-disk layout

```
<WT_CACHE__STORE>/
  keys/<hex>                 entry: {content_id, codec_id, media_type, created_at}
  content/<codec>/<hex>      the payload
```

For example:

```
content/
  ecoscope.frame/v1/9c41…    a step returning one frame
  tree/v2/3f2a…              a step returning a list, a dict, a dataclass, …
```

Keys are flat. Payloads are filed under the step's **root codec**: when its
return type is one declared leaf — a `CodecRef` alias, a `Cacheable` class, or a
builtin like `PATH` — that leaf codec's id, nested at each `/`; for anything
structural, and for mapped steps, the tree's own `tree/v2`. That keeps a store's
frames together, so lifecycle rules and size accounting can target them. A
codec id that is not a safe relative path (an empty segment, `..`, anything
beyond letters, digits, `.`, `_` and `-`) falls back to `tree/v2`.

An entry's `content_id` is `<codec>/<hex>`, and it is what a step promotes to
its dependents' keys. The same value encoded under two root codecs therefore
lives in two places, which costs storage, not correctness. An entry whose
`content_id` is not of that form is read as a miss, never followed.

Keys and payloads are separate so that two steps computing the same value share
one payload, and so that an entry still describes what a step produced after
its payload has been evicted.

The payload format's version is folded into the content digest, so a future
encoding of the same value cannot land on the old bytes. A payload written by a
format this build no longer reads is a **miss**, not an error.

---

## Gotchas

**Editable installs freeze the key.** Code identity is the task distribution's
*installed* version plus its dependency fingerprint. An editable install — a
local checkout wired in through `wt-compiler-env-overrides.toml`, say — freezes
that version string at install time, so editing task code afterwards moves no
key and a warm run keeps serving what the old code produced. This is intended:
changing a task's *signature* or the shape of its *return type* still
invalidates, through the signature hash and the return structure, but changing
its *body* does not. Set `WT_CACHE__EPOCH` to something that moves with
the code, or clear the store.

**Return builtins inside a dataclass.** Return validation coerces a task's
result before the cache sees it, so a miss and a hit agree — except inside a
stdlib dataclass, which pydantic passes through as-is. A field holding an
`np.float64` comes back from a hit as a `float`. Convert in the task.

**Tasks outside an installed distribution are never cached.** Without a version
the cache cannot pin the code, and a code change would not move the key. It
fails closed. This bites functions defined in test modules and in notebooks.

**`.cached()` must come before `.partial()`** in a hand-written chain.
`.cached()` reads the wrapped function to work out where the task lives and how
its result encodes; `.partial()` replaces that function with a
`functools.partial`, which carries neither `__module__` nor `__name__`. The
generated DAG already orders them correctly.

**A path under a per-run output root defeats early cutoff.** If each run writes
its results under a fresh directory, a step that returns an absolute path into
it produces a new value every run, and everything below it misses. Return paths
relative to the root, and resolve them in the step that hands results to their
reader — ecoscope's `persist_*` tasks and `gather_dashboard` do this.

**Mapped steps cache as one entry**, not one per element. One changed group
recomputes all of them. Acceptable while mapped steps sit at the tail of a
workflow; revisit if a mapped source appears.

**`mapvalues` keys keep their tuples.** JSON has no tuple, so the cache tags
them explicitly — a hit that handed back a list would be unhashable the moment a
downstream step grouped by it.

**No pickle, ever.** Pickle would couple every stored entry to the exact version
of the code that wrote it and make the cache a deserialization surface.
Refusing to cache is always safe.

---

## Troubleshooting

**"Why didn't this step hit?"** Read its row in `cache-report.json` and follow
its `reason`:

| Reason | What to do |
|--------|-----------|
| *no cache store configured* | Set `WT_CACHE__STORE`. |
| *return type declares no codec* | Annotate the return type — see [declaring a codec](#declaring-a-codec-for-a-type-you-own). |
| *upstream `<id>` uncacheable* | Fix that step; this one cannot be cached until it is. |
| *no distribution version for `<anchor>`* | The task's package is not installed as a distribution. |
| *declared codec refs could not be imported* | The running environment lacks the codec the registry recorded. Run with `WT_CACHE__STRICT=1` to see the failure. |
| *`Undigestible(...)`* | A codec declined the actual value. The declared type is wider than what the task returns. |
| *older than `<n>`s (age `<n>`s)* | Working as configured: the io step's entry outlived `WT_CACHE__IO_TTL`. Raise the TTL if that is too eager. |
| *`WT_CACHE__IO_TTL` is zero: io steps always refetch* | Every io step refetches by design. Unset the variable, or give it a duration. |
| *io step with `WT_CACHE__SCOPE` unset* | Working as designed: unscoped sources are never served. Set a scope. |
| *Could not decode `content/...` (warning)* | A stored payload is present but unreadable. The step recomputed and rewrote it; `WT_CACHE__STRICT=1` raises `CacheCorruptionError` instead. |
| *Ignoring unusable cache settings (...)* | A setting would not parse and was dropped to its safest value. Fix it, or set `WT_CACHE__STRICT=1` to make it fail loudly. |

**Everything misses on a warm run.** Check `WT_CACHE__EPOCH` and
`WT_CACHE__SCOPE` are what you expect, and that the environment matches the one
that wrote the entries — a dependency upgrade moves every key by design.

**A step hits when it should not.** Run with `WT_CACHE__VERIFY=1`. If it reports
a mismatch, that task needs the `no-cache` tag (or the `io` tag, if the
difference is per-principal).

**A compile fails with "Cannot compile with caching".** A task in the spec
declares a codec its type cannot honour. The message names the task and the
field; see [the round-trip check](#the-model-round-trip-check).

---

## Not yet built

- Garbage collection — use your object store's lifecycle rules. (Freshness for
  io steps *is* built: see `WT_CACHE__IO_TTL` above.)
- Caching for composites and meta-tasks.
- Per-element caching for mapped steps.
