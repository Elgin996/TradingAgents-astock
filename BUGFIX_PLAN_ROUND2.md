# 修复计划 · 第二轮 (Round 2 Fix Plan)

**Scope:** defects introduced by, or left open after, the Round-1 fix commit `cb7e590`.
**Baseline review:** 33 of the 37 Round-1 findings verified as genuinely fixed. This
document covers the 4 that were not, plus 13 new defects the fixes introduced or exposed.

**Legend:** `P0` blocks release · `P1` fix this sprint · `P2` schedule · `P3` cleanup

| ID | Severity | Area | One-line |
|----|----------|------|----------|
| R1 | P0 | `agents/utils/rating.py` | Negation fix over-corrects; 不错/不俗/不小/不仅 kill valid Buy calls |
| R2 | P0 | `.github/workflows/test.yml` | CI never installs pytest — every run fails; SDK billing tests never execute |
| R3 | P0 | `agents/utils/structured.py:40` | `is not ()` is a `SyntaxWarning`, and a hard `SyntaxError` under `-W error` |
| R4 | P1 | `agents/utils/structured.py:32` | `_SCHEMA_ERRORS` re-widened to `ValueError`/`TypeError`/`AttributeError` |
| R5 | P1 | `dataflows/a_stock.py:871` | `get_fundamentals` mootdx snapshot ignores `curr_date` — residual lookahead |
| R6 | P1 | `graph/trading_graph.py:634` | `trace[-1]` still unguarded on empty stream |
| R7 | P1 | `agents/quality_gate.py:182` | Internal field name `data_quality_failed` leaks into the user-facing report |
| R8 | P2 | `llm_clients/claude_agent_sdk_client.py:311` | Timeout leaves an orphaned daemon thread + `claude` subprocess |
| R9 | P2 | `llm_clients/claude_agent_sdk_client.py:90` | `"401"` bare substring in `_AUTH_HINTS` → false auth classification |
| R10 | P2 | `graph/propagation.py:14` | `Propagator()` default is 100, config default is 250 |
| R11 | P2 | `dataflows/a_stock.py:342` | `_em_get` throttles request *starts*, not concurrency — can still trip the ≥10 concurrent rule |
| R12 | P2 | `tests/test_rating_parser.py` | 8 cases, none covering the class of input R1 breaks |
| R13 | P3 | `agents/utils/rating.py:61` | Duplicate/redundant entries in `_NEGATION_CUES` |
| R14 | P3 | `graph/trading_graph.py:56` | `_normalize_yfinance_ticker` now dead in production, kept alive only by tests |

---

## Phase 0 — Blockers

### R1 · `parse_rating` negation over-correction

**File:** `tradingagents/agents/utils/rating.py:60-82`, `110-136`

**Symptom.** Perfectly ordinary Chinese analyst prose now downgrades to `Hold`:

| Input | Expected | Round-1 actual |
|-------|----------|----------------|
| `公司基本面不错，我们给予买入评级。` | Buy | Hold |
| `营收增长不俗，维持买入。` | Buy | Hold |
| `风险不小，但我们仍建议买入。` | Buy | Hold |
| `不仅估值合理，且景气度向上，给予买入。` | Buy | Hold |
| `公司订单不断增加，给予买入。` | Buy | Hold |

This is worse than the bug it replaced. The Round-1 defect (missed negation) turned a
`Hold` into a `Buy` occasionally; this one silently neutralises a large fraction of all
genuine Buy/Overweight calls, because 不错/不俗/不小/不断/不仅 are high-frequency in
Chinese equity research writing.

**Root cause — two independent errors.**

1. **Bare `不` in `_NEGATION_CUES`** (line 63). `不` is not a word, it is a negating
   *morpheme*. It appears inside dozens of positive or neutral compounds. Matching it as
   a substring is guaranteed to over-trigger.
2. **Clause splitter omits the Chinese comma** (line 78, `re.split(r"[。；;.!?\n]", …)`).
   Chinese prose separates clauses with `，` and `、`, which the splitter treats as
   ordinary text. So a cue anywhere earlier in a long sentence poisons every rating term
   after it, even across a clause boundary.

There is a third, latent bug in the same function:

3. **Fragile line→offset reconstruction** (lines 119-127). `abs_start =
   text.lower().rfind(line_lower)` finds the *last* occurrence of the line's text, which
   is not necessarily the line currently being scanned. Any repeated line (blank lines,
   repeated headings, a `sell` bullet appearing twice) yields an offset pointing at the
   wrong place, so `_disqualified` inspects unrelated context. It also silently falls
   back to `abs_start = 0` — i.e. it evaluates the negation context of the *document
   start* — whenever the lookup fails.

**Fix.** Replace cues, splitter, and the English scan pass. The compound-noun check also
becomes directional: `龙虎榜卖出` is a market fact by its *prefix*, `卖出席位` by its
*suffix*. A single bidirectional window is wrong — it would kill
`建议买入，北向资金持续流入`.

```python
# Cues that invert or disqualify a nearby rating word.
#
# Never list a bare `不`: it is a negating morpheme, not a word, and it occurs
# inside 不错 / 不俗 / 不小 / 不断 / 不仅 — all common in bullish A-share prose.
# Only explicit negating constructions belong here. English cues keep a trailing
# space or apostrophe so "not" does not match inside "nothing" / "notable".
_NEGATION_CUES = (
    # English
    "not ", "n't", "avoid", "refrain", "rather than", "instead of",
    "no longer", "would not", "do not", "cannot",
    # Chinese — explicit negating verbs/constructions only
    "不建议", "不推荐", "不宜", "不应", "不要", "不看好", "不值得", "不考虑",
    "无需", "勿", "避免", "而非", "并非", "谈不上", "谈不到", "反对",
)

# Chinese prose delimits clauses with ，and 、. Omitting them let a cue at the
# start of a long sentence poison every rating term after it.
_CLAUSE_SPLIT_RE = re.compile(r"[。；;.!?\n，、]")

# Rating terms that double as ordinary domain nouns. Direction matters:
# "龙虎榜卖出" is a market fact by its prefix, "卖出席位" by its suffix.
_COMPOUND_PREFIX = {
    "减持": ("股东", "高管", "董监高", "实控人"),
    "卖出": ("龙虎榜", "前五", "机构专用"),
    "买入": ("龙虎榜", "前五", "北向", "机构专用"),
}
_COMPOUND_SUFFIX = {
    "减持": ("计划", "公告", "股份", "比例"),
    "卖出": ("席位", "营业部", "金额", "占比"),
    "买入": ("席位", "营业部", "金额", "占比"),
}

_EN_WORD_RE = re.compile(r"[A-Za-z']+")


def _disqualified(text: str, start: int, end: int, term: str) -> bool:
    """True when the match at ``start`` is negated or part of a compound noun."""
    clause = _CLAUSE_SPLIT_RE.split(text[:start])[-1].lower()
    if any(cue in clause for cue in _NEGATION_CUES):
        return True
    prefix = text[max(0, start - 6):start]
    if any(ctx in prefix for ctx in _COMPOUND_PREFIX.get(term, ())):
        return True
    return text.startswith(_COMPOUND_SUFFIX.get(term, ()), end)
```

Then replace pass 3 (lines 110-136) — iterating real match offsets in the full text
removes the `rfind` reconstruction entirely:

```python
    # 3. Bare English rating word — last non-disqualified match wins
    #    (conclusion-first). Iterating offsets in the full text avoids
    #    reconstructing a line's position, which broke on repeated lines.
    last_en = None
    for m in _EN_WORD_RE.finditer(text):
        word = m.group(0).lower()
        if word in _RATING_SET and not _disqualified(text, m.start(), m.end(), word):
            last_en = word
    if last_en is not None:
        rating = last_en.capitalize()
        logger.warning(
            "parse_rating: no explicit rating label found; inferred %r from bare term. "
            "Text begins: %.120s",
            rating, text,
        )
        return rating
```

Update both `_disqualified` call sites in pass 4 to pass `m.end()`.

**Verification status.** This exact implementation was prototyped and run against 28
cases: the 8 currently in `tests/test_rating_parser.py`, the 6 regressions above, and 14
new guard cases. **All 28 pass.** Notably `Nothing here is notable; we buy.` → `Buy`
(the `"not "` cue no longer matches inside words) and
`买入席位为机构专用，卖出席位为游资。` → `Hold` (suffix compound check).

**Tests.** See R12 — this fix and its test expansion should land in one commit.

**Effort:** 1.5h including tests.

---

### R2 · CI is broken and the billing tests never run

**File:** `.github/workflows/test.yml:19-23`, `pyproject.toml`

**Symptom.** Two separate failures.

1. The workflow runs `pip install -e .` then `pytest`. `pytest` is not in `dependencies`
   and there is no dev extra or `[dependency-groups]`, so the runner has no pytest
   binary. **Every CI run fails at the "Unit tests" step with `pytest: command not
   found`.** The green-checkmark signal the Round-1 fixes were validated against does
   not exist.
2. The workflow never installs the `agentsdk` extra. The Claude Agent SDK billing tests —
   which guard the single highest-severity finding of Round 1, *auth failure must never
   silently start paid billing* — skip on import error. Even once R2.1 is fixed, that
   guarantee stays unverified in CI.

**Fix.** Declare a dev extra and install both extras in CI.

```toml
# pyproject.toml
[project.optional-dependencies]
agentsdk = ["claude-agent-sdk>=0.2.82"]
dev = ["pytest>=8.0", "pytest-cov>=5.0"]
```

```yaml
# .github/workflows/test.yml
      - name: Install package
        run: pip install -e ".[dev,agentsdk]"

      - name: Unit tests
        run: pytest -ra --strict-markers
```

**Do not** rely on `pyproject.toml`'s `addopts` to also carry `-m "not integration"` here
— the workflow already passes explicit flags, and pytest merges rather than replaces
`addopts`, so the marker filter still applies. Confirm this by asserting the collected
count in the first green run.

**Tests.** Push a branch and confirm the workflow goes green, then confirm the SDK
billing tests report as *run*, not *skipped*:

```bash
pytest -ra --strict-markers -k "billing or auth" -v
```

If they still skip, the extra is not resolving — check that `claude-agent-sdk` publishes
a wheel for the CI Python (3.12).

**Effort:** 30min, plus one CI round-trip.

---

### R3 · `SyntaxWarning` in `structured.py`

**File:** `tradingagents/agents/utils/structured.py:40`

**Symptom.** `if OutputParserException is not ():` compares against a literal. CPython
emits `SyntaxWarning: "is not" with a literal. Did you mean "!="?` on import. Under
`python -W error::SyntaxWarning` it is a hard `SyntaxError` and the module will not
import at all — which will bite any downstream consumer running with strict warnings.

The intent is "did the langchain import succeed", and the `except ImportError` branch
sets the name to `()`. Truthiness expresses that directly.

**Fix.**

```python
if OutputParserException:
    _SCHEMA_ERRORS = _SCHEMA_ERRORS + (OutputParserException,)  # type: ignore[arg-type]
```

**Tests.** Add a guard so this class of warning cannot reappear anywhere:

```python
# tests/test_no_syntax_warnings.py
import compileall
import warnings


def test_package_compiles_without_syntax_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        assert compileall.compile_dir(
            "tradingagents", quiet=2, force=True
        ), "SyntaxWarning raised during compile"
```

**Effort:** 15min.

---

## Phase 1 — High

### R4 · `_SCHEMA_ERRORS` re-widened

**File:** `tradingagents/agents/utils/structured.py:32-39`

**Symptom.** The Round-1 goal was to *narrow* the fallback net so genuine provider faults
propagate instead of being silently downgraded to free text. The landed tuple is
`(ValidationError, JSONDecodeError, KeyError, TypeError, AttributeError, ValueError)`.
`ValueError` is a superclass of `JSONDecodeError` and of many provider-side errors;
`TypeError`/`AttributeError` catch ordinary programming mistakes in our own rendering
code. A `TypeError` from a typo in a render function now looks identical to "the model
returned a bad schema", and the run continues on degraded output rather than failing loudly.

**Fix.** Keep only errors that genuinely mean *the model's output did not match the
schema*:

```python
_SCHEMA_ERRORS: Tuple[Type[BaseException], ...] = (
    ValidationError,   # pydantic: shape mismatch
    JSONDecodeError,   # provider returned non-JSON where JSON was required
)
if OutputParserException:
    _SCHEMA_ERRORS = _SCHEMA_ERRORS + (OutputParserException,)
```

If a specific provider is observed raising bare `KeyError`/`TypeError` for schema
failures, re-add it **with a comment naming the provider and the observed message** —
not speculatively.

**Tests.** Assert that a programming error propagates rather than falling back:

```python
def test_typeerror_is_not_swallowed_as_schema_failure():
    llm = _StubStructuredLLM(raises=TypeError("render bug"))
    with pytest.raises(TypeError):
        invoke_structured_or_freetext(llm, ..., render=lambda r: r.nope())
```

**Effort:** 45min. **Risk:** medium — may surface real provider faults that were
previously masked. Land it early in a sprint, not before a release.

---

### R5 · `get_fundamentals` mootdx snapshot is not point-in-time

**File:** `tradingagents/dataflows/a_stock.py:848-895`

**Symptom.** `_reject_if_not_point_in_time` correctly suppresses the live Tencent /
Eastmoney / 同花顺 sections for a past `curr_date`. But the mootdx block immediately
above it does `fin = client.finance(symbol=code)` then `row = fin.iloc[0]` —
unconditionally the *most recent* quarterly filing, whatever today's date is. The comment
on line 871 calls it "quarterly, usable historically", and the docstring on line 854 says
mootdx snapshots "are still returned". Both are wrong as a lookahead guarantee: for a
backtest dated 2023-03-01 the agent receives EPS/ROE/net-profit from the latest available
filing, which may be years in the future.

This is the last surviving instance of the Round-1 lookahead class, and it is in the
fundamentals path — the one most likely to carry decisive information.

**Fix.** Filter mootdx rows by report date before selecting.

```python
        try:
            client = _get_mootdx_client()
            fin = client.finance(symbol=code)
            row = _latest_report_at_or_before(fin, curr_date)
            if row is not None:
                ...
```

with a helper alongside the other date utilities:

```python
def _latest_report_at_or_before(fin, curr_date: str | None):
    """Most recent mootdx quarterly row whose report date is <= curr_date.

    mootdx returns filings newest-first with no date filter, so an unfiltered
    iloc[0] leaks future fundamentals into a backtest.
    """
    if fin is None or not isinstance(fin, pd.DataFrame) or fin.empty:
        return None
    if not curr_date:
        return fin.iloc[0]
    date_col = next(
        (c for c in ("report_date", "date", "reportdate") if c in fin.columns), None
    )
    if date_col is None:
        logger.warning(
            "mootdx finance for this symbol has no report-date column %s; "
            "omitting the historical block rather than risking lookahead",
            list(fin.columns),
        )
        return None
    dates = pd.to_datetime(fin[date_col], errors="coerce")
    eligible = fin[dates <= pd.Timestamp(curr_date)]
    return None if eligible.empty else eligible.iloc[0]
```

**Note the fail-closed default:** if the report-date column cannot be identified, omit
the block. Returning possibly-future fundamentals is strictly worse than returning none.

**Before writing the helper,** confirm the actual column name — print
`client.finance(symbol="600519").columns` once against the live source and pin the real
name rather than guessing across three candidates.

Also correct the two stale comments (lines 854, 860, 871) once the guard is in place.

**Tests.**

```python
def test_get_fundamentals_omits_future_quarterly_rows(monkeypatch):
    frame = pd.DataFrame(
        {"report_date": ["2024-09-30", "2023-12-31"], "eps": [9.9, 1.1]}
    )
    ...
    out = get_fundamentals("600519", curr_date="2024-01-15")
    assert "1.1" in out and "9.9" not in out


def test_get_fundamentals_omits_block_when_no_date_column(monkeypatch):
    frame = pd.DataFrame({"eps": [9.9]})
    ...
    assert "EPS" not in get_fundamentals("600519", curr_date="2024-01-15")
```

**Effort:** 2h including a live column-name check.

---

### R6 · Unguarded `trace[-1]` in `_run_graph`

**File:** `tradingagents/graph/trading_graph.py:621-638`

**Symptom.** The CLI path got empty-stream guards in Round 1; the library path did not.
`final_state = trace[-1]` raises `IndexError` when the stream yields nothing — which
happens on an immediate recursion-limit trip, a provider auth failure on the first node,
or a quality-gate block that ends the graph before any chunk is emitted. The last case is
newly reachable *because of* the Round-1 quality-gate fix, so this is a live interaction
between two Round-1 changes, not a theoretical edge.

The failure mode is an opaque `IndexError` from deep inside the graph, with none of the
run context a user needs.

**Fix.**

```python
                if not trace:
                    raise RuntimeError(
                        f"Graph produced no state for {company_name} on {trade_date}. "
                        "This usually means the quality gate blocked the run, the "
                        "recursion limit was hit immediately, or the first node's "
                        "provider call failed. Check the log above for the cause."
                    )
                final_state = trace[-1]
```

Then audit the sibling path: `finalize_graph_run` should tolerate a `final_state` that is
missing the keys it reads, mirroring the guards already added to the CLI.

**Tests.**

```python
def test_run_graph_raises_actionable_error_on_empty_stream(monkeypatch):
    ta = _stub_graph(stream=iter([]))
    with pytest.raises(RuntimeError, match="produced no state"):
        ta.propagate("600519", "2024-01-15")
```

**Effort:** 45min.

---

### R7 · Internal field name leaks into the user-facing report

**File:** `tradingagents/agents/quality_gate.py:176-184`

**Symptom.** The quality-gate summary is otherwise clean Chinese markdown, then ends with
a raw Python identifier and its `str().lower()` boolean:

```
**data_quality_failed**: true (fail_count=2, threshold=3)
```

Users see `data_quality_failed`, `fail_count`, `threshold` — internal state-dict keys — in
a report the rest of which is written for a human. It also renders `true`/`false` rather
than 是/否, which reads as a bug even to a reader who does not know the codebase.

**Fix.** Render the verdict in the report's own language; keep the machine-readable value
in the returned dict, which is where consumers already read it from (line 188).

```python
        verdict = "未通过 ❌" if data_quality_failed else "通过 ✅"
        summary = (
            f"## 数据质量门控结果\n\n"
            f"**标的**: {ticker} | **交易日**: {trade_date}\n\n"
            f"### 硬检查结果\n{hard_summary}\n\n"
            f"### LLM 复审\n"
            f"{llm_review if llm_review else '（跳过 — 多数报告未通过硬检查）'}\n\n"
            f"### 门控判定\n"
            f"**{verdict}** — {fail_count} 项硬检查未达标，阈值为 {threshold} 项。\n"
        )
```

**Tests.**

```python
def test_quality_gate_summary_has_no_internal_identifiers():
    out = _run_gate(fail_count=2, threshold=3)["data_quality_summary"]
    assert "data_quality_failed" not in out
    assert "fail_count" not in out
    assert "通过" in out
```

**Effort:** 30min.

---

## Phase 2 — Medium

### R8 · SDK timeout orphans a thread and a subprocess

**File:** `tradingagents/llm_clients/claude_agent_sdk_client.py:303-337`

The `thread.join(timeout)` fix correctly stops the caller blocking forever. But when the
timeout fires, the daemon thread keeps running with its `claude` CLI subprocess attached.
The error message even says so — *"check for orphaned processes"* — which puts the
cleanup on the user. Across a multi-agent batch run, each timeout leaks one thread and one
subprocess for the life of the process.

Both `_worker_no_loop` and `_worker` have this shape; fix them together, ideally by
extracting the duplicated join/raise logic into one helper.

**Fix direction.** Give the worker a cancellation handle so the timeout can tear the
subprocess down:

```python
    cancel = threading.Event()
    ...
    thread.join(timeout)
    if thread.is_alive():
        cancel.set()
        _terminate_sdk_subprocess()   # kill the client's transport / child proc
        thread.join(5)                # brief grace period
        raise _SDKResultError(
            f"Agent SDK call exceeded {timeout}s; the `claude` subprocess was "
            f"terminated."
        )
```

`_terminate_sdk_subprocess` needs to reach the SDK's transport handle. **Check the
`claude-agent-sdk` API first** — if it exposes an async `close()`/`disconnect()` on the
client, prefer scheduling that on the worker's loop over killing a PID. This step is why
the item is P2 rather than P1: the correct fix depends on an SDK surface we have not yet
confirmed, and the current state is a leak rather than a correctness bug.

**Effort:** 2-3h including SDK API investigation.

---

### R9 · `"401"` as a bare substring in `_AUTH_HINTS`

**File:** `tradingagents/llm_clients/claude_agent_sdk_client.py:89-94`

`_exc_looks_like_auth` does a substring test, so `"401"` matches `HTTP 1401`, `error
4010`, a request ID containing those digits, or a timestamp. `"credentials"` is similarly
broad.

The direction of failure is safe — a false positive raises `_AuthError` and *refuses* to
fall back to paid billing, which is the conservative outcome and the whole point of the
Round-1 fix. So this is not a money bug. It is a usability bug: a transient network error
whose text happens to contain `401` blocks a legitimate fallback and tells the user to
re-authenticate when their auth is fine.

**Fix.** Require a word boundary for the numeric code, and keep the substring test for
the genuinely distinctive phrases:

```python
_AUTH_STATUS_RE = re.compile(r"\b401\b")

def _exc_looks_like_auth(exc_or_msg: Any) -> bool:
    """True when exception/string content indicates a subscription auth failure."""
    blob = str(exc_or_msg).lower()
    return bool(_AUTH_STATUS_RE.search(blob)) or any(h in blob for h in _AUTH_HINTS)
```

and drop `"401"` from `_AUTH_HINTS`. Leave the explicit `status == 401` check at line 625
alone — that one reads a real status field and is correct.

**Tests.** `assert not _exc_looks_like_auth("connection reset, request id 8814012")`
alongside `assert _exc_looks_like_auth("HTTP 401 Unauthorized")`.

**Effort:** 30min.

---

### R10 · `Propagator` default disagrees with the config default

**File:** `tradingagents/graph/propagation.py:14`

`Propagator(max_recur_limit=100)` while `DEFAULT_CONFIG["max_recur_limit"] = 250` and
`trading_graph.py:265` passes `self.config.get("max_recur_limit", 250)`. Three places,
two values. Any caller constructing a bare `Propagator()` — `tests/test_memory_log.py:724`
and `:730` do exactly this — silently gets a 2.5× tighter step budget than a real run,
so a test can pass or fail for reasons unrelated to what it is asserting.

**Fix.** Import the single source of truth:

```python
from tradingagents.default_config import DEFAULT_CONFIG

class Propagator:
    def __init__(self, max_recur_limit=DEFAULT_CONFIG["max_recur_limit"]):
```

If that import would be circular, use a module constant in `propagation.py` and have
`default_config.py` reference *it* instead — but keep exactly one literal `250` in the
codebase.

**Tests.** `assert Propagator().max_recur_limit == DEFAULT_CONFIG["max_recur_limit"]`.

**Effort:** 20min.

---

### R11 · `_em_get` throttles starts, not concurrency

**File:** `tradingagents/dataflows/a_stock.py:342-362`

The slot-reservation rewrite is a real improvement over the previous
read-sleep-write-under-lock pattern, and it correctly serialises the *schedule*. But it
spaces request **starts** by ~1.0-1.5s and then releases the lock before the HTTP call. It
never observes completions. The documented Eastmoney limit that this function exists to
respect (comment, line 320) includes **单 IP 并发 ≥10** — concurrency, not rate.

If a batch run has 12 agent threads and Eastmoney responses slow to 15s (the `timeout`
default), starts at 1.2s intervals put ~12 requests in flight simultaneously. The
per-second and per-minute rules hold; the concurrency rule is breached, which is one of
the documented ban triggers.

**Fix.** Add a semaphore capping in-flight requests, independent of the interval:

```python
# The documented Eastmoney limits are both a *rate* and a *concurrency* rule.
# The interval below spaces request starts; this semaphore bounds requests
# actually in flight, which slow responses would otherwise let pile up.
_EM_MAX_INFLIGHT = int(os.environ.get("EM_MAX_INFLIGHT", "4"))
_em_inflight = threading.Semaphore(_EM_MAX_INFLIGHT)
```

```python
    delay = start_at - time.time()
    if delay > 0:
        time.sleep(delay)
    with _em_inflight:
        return _em_session().get(
            url, params=params, headers=headers, timeout=timeout, **kwargs
        )
```

4 is comfortably under the documented 10 and leaves headroom for any Eastmoney call that
does not route through `_em_get`.

**Tests.** Drive `_em_get` from 12 threads against a stub that sleeps 0.5s and records
concurrent entries; assert the observed peak never exceeds `_EM_MAX_INFLIGHT`.

**Effort:** 1h.

---

### R12 · `test_rating_parser.py` does not cover the failure class

**File:** `tests/test_rating_parser.py`

Eight cases, all of which pass both before and after R1. The suite gave a green signal
for a change that broke a large fraction of real inputs, because it contains no example of
the one construction that matters: **a rating term in a sentence that contains 不 as part
of a positive compound.** A test suite that cannot distinguish the bug from the fix is not
providing coverage of this function.

**Fix.** Land these with R1. All 28 were verified passing against the R1 implementation.

```python
@pytest.mark.parametrize("text,expected", [
    # --- existing 8, unchanged ---
    ("We would not buy this stock at these levels.", "Hold"),
    ("不建议卖出，继续观察。", "Hold"),
    ("大股东减持压力较大，但基本面稳健。", "Hold"),
    ("龙虎榜卖出席位以游资为主。", "Hold"),
    ("Rating: Sell\nWe would not buy this stock.", "Sell"),
    ("最终评级：卖出", "Sell"),
    ("综合来看，我们给予买入评级。", "Buy"),
    ("The bear case is strong; we sell.\n\nRating: Hold", "Hold"),

    # --- R1: 不 inside a positive compound must NOT negate ---
    ("公司基本面不错，我们给予买入评级。", "Buy"),
    ("营收增长不俗，维持买入。", "Buy"),
    ("风险不小，但我们仍建议买入。", "Buy"),
    ("不仅估值合理，且景气度向上，给予买入。", "Buy"),
    ("公司订单不断增加，给予买入。", "Buy"),
    ("短期波动不少，长期给予增持。", "Overweight"),

    # --- genuine negation must still negate ---
    ("我们不看好该标的，不建议买入。", "Hold"),
    ("估值已高，不宜买入。", "Hold"),
    ("We cannot buy at this price.", "Hold"),

    # --- 'not' must not match inside a longer word ---
    ("Nothing here is notable; we buy.", "Buy"),

    # --- compound nouns, both directions ---
    ("买入席位为机构专用，卖出席位为游资。", "Hold"),
    ("大股东拟减持不超过2%股份，我们维持买入评级。", "Buy"),
    ("减持计划已完成，基本面改善，给予增持。", "Overweight"),
    ("北向买入居前，但估值偏高，建议减持。", "Underweight"),

    # --- clause scoping: a cue must not cross ，---
    ("我们建议买入，而非卖出。", "Buy"),

    # --- labels and ordering ---
    ("估值偏高，建议卖出。", "Sell"),
    ("buy\nsomething else\nsell\n", "Sell"),
    ("Rating: BUY\n", "Buy"),
    ("投资建议：买入", "Buy"),
    ("", "Hold"),
])
def test_parse_rating(text, expected):
    assert parse_rating(text) == expected
```

**Effort:** included in R1.

---

## Phase 3 — Cleanup

### R13 · Duplicate and redundant negation cues

**File:** `tradingagents/agents/utils/rating.py:61-65`

`"并非"` is listed twice (lines 63 and 64), and `"不建议"` / `"不要"` / `"不宜"` are all
unreachable while bare `"不"` precedes them in the tuple. Harmless at runtime, but it is
the visible fingerprint of the R1 bug — the author added specific cues *and* the bare
morpheme, and the morpheme swallowed them. Resolved automatically by the R1 rewrite; this
entry exists so the tuple is reviewed rather than merged.

**Effort:** 0 — folded into R1.

### R14 · `_normalize_yfinance_ticker` is production-dead

**File:** `tradingagents/graph/trading_graph.py:56`, `:112`

Once reflection was ported off yfinance in Round 1, `_normalize_yfinance_ticker` and
`_is_unsupported_by_yfinance` lost all production callers. The only remaining references
are six assertions in `tests/test_memory_log.py:463-478` — i.e. tests that now exist
solely to test dead code, which is how dead code survives cleanup passes indefinitely.

Confirm nothing outside the repo imports them, then delete both functions and their tests,
and note the removal in `CHANGELOG.md` next to the entry that introduced them (line 128).
If they are worth keeping for a future US-equity path, move them to the dataflows layer
where a yfinance caller would actually live, and say so in a comment.

**Effort:** 30min.

---

## Sequencing

**Commit 1 — release blockers (~2.5h)**
R3 (SyntaxWarning) → R2 (CI) → verify CI is green *before* touching anything else, so the
rest of the work has a working signal. Then R1 + R12 together.

**Commit 2 — correctness (~4h)**
R5 (fundamentals lookahead), R6 (empty stream), R7 (report leak). Independent of each
other; parallelisable.

**Commit 3 — hardening (~2h)**
R9 (401 boundary), R10 (recursion default), R11 (concurrency semaphore).

**Commit 4 — behaviour change, land early in a cycle (~1h)**
R4 (`_SCHEMA_ERRORS` narrowing). Expect this to surface previously-masked provider faults;
budget time to triage what it exposes.

**Backlog**
R8 (SDK subprocess teardown — needs SDK API investigation), R14 (dead code).

**Total: ~10h** excluding R8.

## Exit criteria

- [ ] CI green on a clean runner, with SDK billing tests reported as run, not skipped
- [ ] `pytest -W error::SyntaxWarning` imports every module cleanly
- [ ] All 28 `parse_rating` cases pass
- [ ] `get_fundamentals("600519", curr_date="2023-03-01")` contains no post-2023-03-01 filing
- [ ] An empty graph stream raises a message naming the ticker, the date, and the likely cause
- [ ] The quality-gate report contains no Python identifiers
- [ ] 12-thread `_em_get` load test never exceeds 4 concurrent in-flight requests

## Round-1 items confirmed fixed

Recorded so a future reviewer does not re-litigate them: Agent SDK billing guarantee,
greedy JSON extraction, `_em_get` thread safety, BSE routing, `get_global_news` filter,
`get_news` fail-open, lockup history, market-cap units, `get_dragon_tiger_board`
`UnboundLocalError`, Alpha Vantage HTTP timeout and dead type guard, `alpha_vantage_common`
CSV fail-open, `stockstats_utils` `ffill().bfill()`, `print()` → logger in `utils.py` and
`y_finance.py`, `max_recur_limit` wiring, A-share reflection, mutable default arguments,
`log_states_dict` growth, quality-gate halt policy and scaled threshold, conditional-edge
wiring, memory lookahead and pending-entry pruning, `FileLock` (no self-deadlock),
`--checkpoint` resume, 7 analysts exposed, `full_states_log_*.json` persistence, CLI
empty-stream and missing-key guards, `ANALYST_ORDER` de-duplication, web future-date
rejection, report XSS escaping, PDF caching, and the web stop/incomplete-task race.
