# Bug Fix Plan

Derived from the full-project code review of commit `99c85a1` (37 confirmed findings:
4 Critical, 14 High, 15 Medium, 4 Low). Every item below was verified against source
before being written down; line numbers are from that commit and will drift as fixes land.

This document is meant to be worked top to bottom. Phases are ordered by
**damage prevented per unit of effort**, not by raw severity — Phase 1 and 2 are small,
contained edits that remove the worst failure modes, while Phase 4 is a multi-day audit.

---

## Contents

- [Guiding principles](#guiding-principles)
- [Phase 0 — Safety net before touching anything](#phase-0--safety-net-before-touching-anything)
- [Phase 1 — The output signal can be wrong (P0)](#phase-1--the-output-signal-can-be-wrong-p0)
- [Phase 2 — Broken guarantees: billing and throttling (P0)](#phase-2--broken-guarantees-billing-and-throttling-p0)
- [Phase 3 — Data integrity: routing, units, concurrency (P1)](#phase-3--data-integrity-routing-units-concurrency-p1)
- [Phase 4 — Time discipline / lookahead audit (P1)](#phase-4--time-discipline--lookahead-audit-p1)
- [Phase 5 — Pipeline robustness (P2)](#phase-5--pipeline-robustness-p2)
- [Phase 6 — Front-end parity and UX (P2)](#phase-6--front-end-parity-and-ux-p2)
- [Phase 7 — Cleanup (P3)](#phase-7--cleanup-p3)
- [Test plan](#test-plan)
- [PR sequencing](#pr-sequencing)

---

## Guiding principles

Three rules that most of the findings violate in one way or another. Applying them
consistently is more valuable than any individual fix.

**1. Never return plausible-but-wrong data.** An empty string, an explicit error marker, or
a raised exception are all recoverable. A zero, a stale price, or a default rating that
looks like a real answer is not — it propagates into an LLM prompt and comes back out as a
confident recommendation. Where the choice is between "fail loud" and "degrade quietly",
this codebase should choose loud.

**2. A parameter in a signature is a promise.** Six data functions accept `curr_date` and
ignore it. Either honour it or remove it and rename the function so callers can see what
they are getting.

**3. Degradation must be observable.** Silent fallbacks exist in three places (structured
output, subscription billing, Alpha Vantage filtering). Each one is defensible as a
behaviour and indefensible as a *silent* behaviour. Every fallback should leave a mark the
user can see in the final report, not just a line in a log nobody reads.

---

## Phase 0 — Safety net before touching anything

**Effort: ~1 day. Do this first.** The two files carrying the most Critical/High findings —
`tradingagents/dataflows/a_stock.py` (1,816 lines) and `cli/main.py` (1,107 lines) — have
essentially no test coverage. Refactoring them blind is how you trade known bugs for
unknown ones.

### 0.1 Record fixtures for the data layer

Capture real HTTP responses once, then test against them offline forever.

```
tests/fixtures/a_stock/
  tencent_quote_600519.json
  em_push2_info_600519.json
  em_push2_info_920819.json      # BSE — currently broken, capture the *correct* payload
  em_datacenter_lhb_600519.json
  em_datacenter_lift_600519.json
  sina_kline_sh600519.json
  sina_kline_bj920819.json
  ths_eps_600519.html
  cls_telegraph.json
```

Add `tests/conftest.py` helpers:

```python
@pytest.fixture
def em_fixture(monkeypatch):
    """Patch _em_get to serve recorded payloads by URL substring."""
    def _install(mapping: dict[str, str]):
        def fake_get(url, params=None, headers=None, timeout=15, **kw):
            for needle, path in mapping.items():
                if needle in url:
                    return _FakeResponse(_load_fixture(path))
            raise AssertionError(f"unmocked Eastmoney call: {url}")
        monkeypatch.setattr("tradingagents.dataflows.a_stock._em_get", fake_get)
    return _install
```

The `raise AssertionError` on unmocked calls is the important part — it is what will catch a
future edit that adds a network call bypassing `_em_get`.

### 0.2 Add a smoke test for the full graph

One end-to-end test with a stub LLM that returns canned responses, asserting the pipeline
reaches `Portfolio Manager` and produces a parseable signal. This is the regression net for
Phases 1, 5 and 7.

```python
# tests/test_graph_e2e.py
def test_full_pipeline_with_stub_llm(stub_llm, em_fixture, tmp_path):
    ...
    final_state, signal = ta.propagate("600519", "2026-05-12")
    assert signal in RATINGS_5_TIER
    assert final_state["market_report"]
```

### 0.3 Turn on CI

There is currently no workflow file. Minimum viable:

```yaml
# .github/workflows/test.yml
- run: pip install -e .
- run: pytest -ra --strict-markers
- run: python -m compileall tradingagents web cli
```

---

## Phase 1 — The output signal can be wrong (P0)

**Effort: ~1 day.** These three findings compose into a single failure: the framework can
hand the caller a BUY when the model said do not buy. Fix them together.

### F1.1 — `parse_rating` inverts on negated prose

**Severity: Critical** · `tradingagents/agents/utils/rating.py:80-90`

Passes 3 and 4 are bare substring scans with no negation handling:

```python
# 3. Bare English rating word
for line in text.splitlines():
    for word in line.lower().split():
        clean = word.strip("*:.,")
        if clean in _RATING_SET:
            return clean.capitalize()

# 4. Bare Chinese rating term
m = _CN_TERM_RE.search(text)
```

Three distinct failure classes, all confirmed:

| Input | Returns | Should be |
|---|---|---|
| `We would not buy this stock` | `Buy` | `Hold` (or the labelled rating) |
| `不建议卖出` | `Sell` | `Hold` |
| `大股东减持压力较大` | `Underweight` | not a rating at all |

The third is the nastiest: 大股东减持 ("major shareholder reduction") is a *fact* the lockup
analyst reports constantly, not a recommendation.

**Fix.** Keep the bare-term passes as a last resort, but make them defensive:

```python
# Cues that invert or disqualify a nearby rating word.
_NEGATION_CUES = (
    "not ", "n't", "avoid", "refrain", "rather than", "instead of",
    "不", "勿", "避免", "无需", "不宜", "而非", "并非", "谈不上",
)

# Rating terms that are also ordinary domain nouns. When the term is preceded by
# one of these, it is describing a market fact, not issuing a recommendation.
_COMPOUND_CONTEXTS = {
    "减持": ("股东", "大股东", "高管", "董监高", "计划", "公告"),
    "卖出": ("席位", "营业部", "前五", "龙虎榜"),
    "买入": ("席位", "营业部", "前五", "龙虎榜", "北向"),
}

def _disqualified(text: str, start: int, term: str) -> bool:
    """True when the match at `start` is negated or part of a compound noun."""
    clause = re.split(r"[。；;.!?\n]", text[:start])[-1].lower()
    if any(cue in clause for cue in _NEGATION_CUES):
        return True
    prefix = text[max(0, start - 6):start]
    return any(ctx in prefix for ctx in _COMPOUND_CONTEXTS.get(term, ()))
```

Then three behavioural changes to the passes themselves:

1. **Scan the conclusion first.** Iterate lines in reverse for pass 3 and use
   `finditer` taking the *last* non-disqualified match for pass 4. A recommendation lives at
   the end of a document; a stray rating word lives in the body.
2. **Skip disqualified matches** rather than returning on the first hit.
3. **Log when a rating comes from a bare word**, so operators can see how often the
   unreliable path is firing:

```python
logger.warning(
    "parse_rating: no explicit rating label found; inferred %r from bare term. "
    "Text begins: %.120s", rating, text,
)
```

**Tests** (`tests/test_rating_parser.py`, new file — there is currently no test for this
module at all):

```python
@pytest.mark.parametrize("text,expected", [
    ("We would not buy this stock at these levels.", "Hold"),
    ("不建议卖出，继续观察。", "Hold"),
    ("大股东减持压力较大，但基本面稳健。", "Hold"),
    ("龙虎榜卖出席位以游资为主。", "Hold"),
    ("Rating: Sell\nWe would not buy this stock.", "Sell"),   # label wins
    ("最终评级：卖出", "Sell"),
    ("综合来看，我们给予买入评级。", "Buy"),                    # bare term still works
    ("The bear case is strong; we sell.\n\nRating: Hold", "Hold"),
])
def test_parse_rating(text, expected):
    assert parse_rating(text) == expected
```

### F1.2 — Structured-output failure degrades silently and unrendered

**Severity: High** · `tradingagents/agents/utils/structured.py:62-73`

```python
if structured_llm is not None:
    try:
        result = structured_llm.invoke(prompt)
        return render(result)
    except Exception as exc:                    # <- catches everything
        logger.warning("%s: structured-output invocation failed (%s); ...", ...)

response = plain_llm.invoke(prompt)
return response.content                          # <- bypasses render()
```

Two problems. The bare `except Exception` swallows transient provider errors (rate limits,
timeouts) that should be retried or raised, treating them identically to a schema violation.
And the fallback return bypasses `render()`, so the structure every downstream consumer
assumes is gone — which is exactly what routes the decision into F1.1's heuristic parser.

**Fix.** Narrow the catch, and mark the degradation so it survives into the report:

```python
from json import JSONDecodeError
from pydantic import ValidationError

try:
    from langchain_core.exceptions import OutputParserException
except ImportError:
    OutputParserException = ()

_SCHEMA_ERRORS = (ValidationError, JSONDecodeError, OutputParserException, KeyError, TypeError)

FREETEXT_MARKER = "<!-- ta:structured_output=failed -->"

def invoke_structured_or_freetext(structured_llm, plain_llm, prompt, render, agent_name):
    if structured_llm is not None:
        try:
            return render(structured_llm.invoke(prompt))
        except _SCHEMA_ERRORS as exc:
            logger.warning(
                "%s: model returned output that does not match the schema (%s); "
                "falling back to free text — the rating for this run will be "
                "recovered heuristically and may be unreliable",
                agent_name, exc,
            )
        # Anything else (timeout, rate limit, auth) propagates: a transient
        # provider fault must not be laundered into a degraded-but-successful run.

    response = plain_llm.invoke(prompt)
    return f"{FREETEXT_MARKER}\n{response.content}"
```

Then surface the marker:

- `web/components/report_viewer.py` — render `st.warning("本次决策未通过结构化校验，评级为启发式解析，可能不准确")` when the marker is present.
- `cli/main.py` — same as a Rich warning panel before printing the decision.
- `tradingagents/agents/utils/memory.py` — record it on the entry tag so a degraded run
  cannot silently become training signal for future runs.

Strip the marker before the text reaches an LLM prompt (`memory._format_full`,
`quality_gate._build_review_prompt`) so it does not leak into model context.

**Call sites to check** (all three pass `render`, none inspect the return): Research Manager,
Trader, Portfolio Manager.

### F1.3 — Analyst prompts still emit the upstream 3-tier signal

**Severity: Medium** · all 7 analysts, e.g. `tradingagents/agents/analysts/market_analyst.py:82-83`

```python
" If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
" prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
```

Leftover from the US fork. The system uses a 5-tier scale at the Portfolio Manager, and
analysts are supposed to produce research, not verdicts. In combination with F1.1 these
stray words are exactly what the bare-word pass picks up.

**Fix.** Delete the sentence from all seven analyst prompt templates. It is a
`system_message` string constant in each file; grep for `FINAL TRANSACTION PROPOSAL` to find
every occurrence (also check `agent_utils.py` for a shared template).

Verify no code depends on the marker: `grep -r "FINAL TRANSACTION PROPOSAL"` should return
only prompt text, no parsing logic.

---

## Phase 2 — Broken guarantees: billing and throttling (P0)

**Effort: ~1 day.** Two features whose documented promise does not hold in code.

### F2.1 — Subscription auth failure can start paid billing

**Severity: High** · `tradingagents/llm_clients/claude_agent_sdk_client.py:152, 356-367, 519-531`

```python
# 认证失败**不在**此列表：只有限流/SDK 故障才降级到付费 provider。
_FALLBACK_ERRORS = (ClaudeSDKError, _RateLimitHit, _SDKResultError)
```

The intent is correct and `_AuthError` is properly excluded. The gap is that
`ClaudeSDKError` is the SDK's own **base exception class** — a CLI that fails to start
because credentials are missing raises it, and that lands squarely in the fallback tuple.
Separately, the `ResultMessage` branch only classifies `api_error_status == 401` as auth,
while the module's own comment at 496-498 acknowledges OAuth expiry can arrive with a
misleading subtype and no status code.

**Fix, three parts.**

1. Classify by content, not just by type:

```python
_AUTH_HINTS = (
    "oauth", "unauthorized", "401", "authentication", "authenticate",
    "invalid api key", "not logged in", "please log in", "setup-token",
    "credentials", "expired token",
)

def _looks_like_auth_failure(exc_or_msg) -> bool:
    return any(h in str(exc_or_msg).lower() for h in _AUTH_HINTS)
```

2. Gate every fallback through one shared helper, so the three adapters cannot drift:

```python
def _fallback_or_raise(exc, get_fallback, retry, desc):
    """Single decision point for 'should this failure start paid billing?'"""
    if isinstance(exc, _AuthError) or _looks_like_auth_failure(exc):
        raise _AuthError(_auth_failure_hint(exc)) from exc
    fallback = get_fallback()
    if fallback is None:
        raise
    logger.warning("claude_agent_sdk: %s; falling back to provider '%s'", exc, desc)
    return retry(fallback)
```

Replace the duplicated `except _FALLBACK_ERRORS` blocks in `AgentSDKChatModel.invoke`
(356-367), `_StructuredAgentSDK` (289-299) and `_BoundAgentSDK` (316-328) with calls to it.

3. Widen the `ResultMessage` check at 519-531 to run `_looks_like_auth_failure` over the
   full message (`stop_reason`, `subtype`, `result` text), not only `api_error_status`.

**Tests** — extend `tests/test_agent_sdk_provider.py`, which already has the right shape:

```python
def test_clientsdkerror_with_auth_text_does_not_fall_back():
    model = _model_with_fallback(raises=ClaudeSDKError("OAuth token expired"))
    with pytest.raises(_AuthError):
        model.invoke("hi")
    assert model._fallback_llm is None          # fallback never constructed

def test_result_message_auth_error_without_401_does_not_fall_back(): ...
def test_generic_sdk_error_still_falls_back(): ...   # guard against over-correcting
```

That last test matters: the fix must not break the legitimate quota-exhaustion fallback that
the feature exists for.

### F2.2 — Eastmoney throttle is not thread-safe

**Severity: High** · `tradingagents/dataflows/a_stock.py:281-303`

```python
_EM_SESSION = _requests.Session()
_em_last_call = [0.0]

def _em_get(url, params=None, headers=None, timeout=15, **kwargs):
    wait = _EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return _EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()
```

Read, sleep and write on `_em_last_call` happen with no lock, so concurrent threads all clear
the wait check together and fire simultaneously. `requests.Session` is also not thread-safe
for concurrent use. The module docstring calls multi-agent batch analysis "the number one
cause of IP bans" — that is precisely the workload where this does not hold.

**Fix.** Reserve the time slot under a lock but perform the sleep and the request outside it,
so throughput is preserved while the schedule is serialized. Give each thread its own
session:

```python
import threading

_em_lock = threading.Lock()
_em_next_free = 0.0                      # earliest wall-clock time the next call may start
_em_local = threading.local()

def _em_session() -> _requests.Session:
    session = getattr(_em_local, "session", None)
    if session is None:
        session = _requests.Session()
        session.headers.update({"User-Agent": _UA})
        _em_local.session = session
    return session

def _em_get(url, params=None, headers=None, timeout=15, **kwargs):
    global _em_next_free
    with _em_lock:
        now = time.time()
        start_at = max(now, _em_next_free)
        # Reserve this slot before releasing the lock so concurrent callers queue
        # behind it instead of all racing the same timestamp.
        _em_next_free = start_at + _EM_MIN_INTERVAL + random.uniform(0.1, 0.5)
    delay = start_at - time.time()
    if delay > 0:
        time.sleep(delay)
    return _em_session().get(url, params=params, headers=headers, timeout=timeout, **kwargs)
```

**Test** (`tests/test_em_throttle.py`, new):

```python
def test_concurrent_calls_are_serialized(monkeypatch):
    monkeypatch.setattr(a_stock, "_EM_MIN_INTERVAL", 0.2)
    stamps = []
    monkeypatch.setattr(a_stock, "_em_session", lambda: _RecordingSession(stamps))
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: a_stock._em_get("https://push2.eastmoney.com/x"), range(8)))
    gaps = [b - a for a, b in zip(sorted(stamps), sorted(stamps)[1:])]
    assert all(g >= 0.2 for g in gaps), gaps
```

Also audit that nothing bypasses the wrapper —
`grep -n "requests.get" tradingagents/dataflows/a_stock.py` currently shows at least one
direct call in `get_northbound_flow` (line ~1600) that should be routed through `_em_get`.

---

## Phase 3 — Data integrity: routing, units, concurrency (P1)

**Effort: ~2 days.**

### F3.1 — Beijing Stock Exchange tickers route to the wrong exchange

**Severity: High** · `a_stock.py:106, 370, 780-786, 914, 1782`

`_get_prefix()` (line 43) already handles BSE correctly, including the 920xxx case added for
issue #85, and there is a passing test for it. Five call sites ignore it and hardcode a
two-way split:

```python
prefix = "sh" if code.startswith("6") else "sz"           # 370 (Sina K-line), 914 (Sina financials)
market_code = 1 if code.startswith("6") else 0            # 780 (Eastmoney push2 info)
secid = f"1.{code}" if code.startswith("6") else f"0.{code}"   # 1782 (fund flow)
if not _re.match(r"^[036]\d{5}$", code): continue         # 106 (name↔code map)
```

**Fix.** Add two helpers next to `_get_prefix` and replace all five sites:

```python
# Eastmoney market ids. SH=1, SZ=0. BSE is served under the Shenzhen id on
# push2 — verify per endpoint before trusting this table (see F3.1 verification).
_EM_MARKET_ID = {"sh": 1, "sz": 0, "bj": 0}

def _em_secid(code: str) -> str:
    """Eastmoney `secid` for any A-share, including BSE."""
    return f"{_EM_MARKET_ID[_get_prefix(code)]}.{code}"

def _sina_symbol(code: str) -> str:
    """Sina symbol (`sh600519` / `sz000001` / `bj920819`)."""
    return f"{_get_prefix(code)}{code}"
```

For the name↔code map at 88-121, also add the Beijing market and widen the filter:

```python
for market in (0, 1, 2):          # 0=SZ, 1=SH, 2=BJ  — 2 was missing entirely
    ...
    if not _re.match(r"^(?:[036]\d{5}|8\d{5}|92\d{4})$", code):
        continue
```

**Verification — do this before writing the constants.** The `_EM_MARKET_ID["bj"]` value and
the mootdx market id `2` are the two things in this fix I could not confirm from source
alone. Check both empirically against a known BSE code (`920819`, `832000`) and record the
result in the code comment:

```bash
curl -s 'https://push2.eastmoney.com/api/qt/stock/get?secid=0.920819&fields=f57,f58,f116' | head -c 300
curl -s 'https://push2.eastmoney.com/api/qt/stock/get?secid=1.920819&fields=f57,f58,f116' | head -c 300
python -c "from mootdx.quotes import Quotes; print(Quotes.factory(market='std').stocks(market=2).head())"
```

**Tests.** Extend `tests/test_market_prefix_routing.py`, which already covers `_get_prefix`:

```python
@pytest.mark.parametrize("code,secid,sina", [
    ("600519", "1.600519", "sh600519"),
    ("000001", "0.000001", "sz000001"),
    ("300750", "0.300750", "sz300750"),
    ("920819", "0.920819", "bj920819"),
    ("832000", "0.832000", "bj832000"),
])
def test_market_routing(code, secid, sina): ...
```

### F3.2 — Market cap reported in two units in the same block

**Severity: High** · `a_stock.py:741-742, 797-800`

```python
f"Market Cap (100M CNY): {q['mcap_yi']}",     # Tencent — 亿 (1e8 CNY)
...
lines.append(f"总市值: {d['f116']}")           # Eastmoney push2 — raw CNY
lines.append(f"流通市值: {d['f117']}")
```

The fundamentals analyst receives two market caps for one company differing by 10^8.

**Fix.** Normalize everything to 亿 at the point of formatting, and make the unit part of the
label rather than an unwritten convention:

```python
def _fmt_yi(value_in_yuan) -> str:
    """Format a raw-CNY figure as 亿 with the unit attached."""
    try:
        return f"{float(value_in_yuan) / 1e8:,.2f} 亿元"
    except (TypeError, ValueError):
        return "N/A"

lines.append(f"总市值: {_fmt_yi(d.get('f116'))}")
lines.append(f"流通市值: {_fmt_yi(d.get('f117'))}")
```

Then sweep the file for other raw-yuan fields being printed unlabelled —
`grep -n "f116\|f117\|f20\|f21\|NET_AMT\|_AMT" a_stock.py` — and apply the same helper.
Note the existing `net_buy = round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1)` in the
dragon-tiger code is correct (万) and already labelled; keep that convention consistent.

### F3.3 — mootdx client singleton shared across agent threads

**Severity: High** · `a_stock.py:166-216`

One TDX TCP connection is shared by all agent threads. mootdx makes no thread-safety
guarantee and the protocol is request/response over a single socket, so interleaved
`bars`/`finance`/`F10` calls can return another request's payload — wrong data, not an
exception.

**Fix.** Make the client thread-local, reusing the existing server-selection logic:

```python
_mootdx_local = threading.local()

def _get_mootdx_client():
    client = getattr(_mootdx_local, "client", None)
    if client is not None:
        return client
    ...  # existing server probing, unchanged
    _mootdx_local.client = Quotes.factory(market="std", server=(ip, port))
    return _mootdx_local.client
```

Keep the *server selection* result cached globally (probing a server list per thread is
wasteful), but the connection object per thread:

```python
_mootdx_server: tuple[str, int] | None = None   # probed once, shared
_mootdx_server_lock = threading.Lock()
```

If per-thread TCP connections turn out to be too expensive, the fallback is a single client
behind a `threading.Lock` held for the duration of each call. That serializes TDX access,
which is acceptable — it is already the fastest source.

### F3.4 — Northbound flow cache is a non-atomic read-modify-write

**Severity: Medium** · `a_stock.py:1535-1554`

Full-file read, mutate, full-file rewrite with no lock and no atomic replace. Concurrent runs
lose rows; a crash mid-write truncates the file the 20-day average is computed from.

**Fix.** Reuse the temp-file + `os.replace()` pattern already used correctly in
`memory.update_with_outcome`, under the shared file lock from F5.2.

---

## Phase 4 — Time discipline / lookahead audit (P1)

**Effort: ~2-3 days. This is the largest and most important body of work.** This is a
backtestable trading framework, and nine separate defects let a historical run read present
or future data. Individually small; together they mean an analysis dated in the past is
substantially an analysis of today, presented under the requested date.

### F4.1 — Establish the contract first

Before fixing individual functions, make the property explicit and testable.

**Step 1.** Classify every public dataflow function into exactly one of:

- **point-in-time** — honours its date argument, safe for backtests
- **live-only** — returns a current snapshot, unsafe for any historical date

```python
# tradingagents/dataflows/a_stock.py
LIVE_ONLY_TOOLS = frozenset({
    "get_fundamentals",           # Tencent quote + EM push2 + THS — all live
    "get_profit_forecast",        # THS consensus + live price for forward PE
    "get_northbound_flow",        # EM hsgt dayChart — live session only
    "get_concept_blocks",         # Baidu PAE — current concept performance
    "get_fund_flow",              # EM push2 realtime + trailing 20d from now
    "get_industry_comparison",    # EM push2 clist — current sector ranking
})
```

**Step 2.** Add a guard the tools call on entry:

```python
def _reject_if_not_point_in_time(curr_date: str | None, fn_name: str) -> str | None:
    """Return a refusal string when a live-only tool is asked for a past date.

    Returns None (proceed) when strict mode is off or the date is today.
    """
    from .config import get_config
    if not curr_date or not get_config().get("strict_point_in_time", False):
        return None
    if curr_date >= datetime.now().strftime("%Y-%m-%d"):
        return None
    return (
        f"[{fn_name}] 该接口只提供实时快照，无法回溯到 {curr_date}。"
        f"strict_point_in_time 已开启，为避免前视偏差不返回数据。"
    )
```

**Step 3.** Add the config key with an honest default:

```python
# default_config.py
# When True, tools in a_stock.LIVE_ONLY_TOOLS refuse to answer for past dates
# instead of silently returning a current snapshot. Off by default because it
# degrades same-day analysis quality; turn it on for any backtest or research
# run where lookahead bias would invalidate the result.
"strict_point_in_time": False,
```

**Step 4.** Stop the headers from lying. Live-only functions must not print the requested
date as though the data belongs to it:

```python
# before
lines = [f"# 行业横向对比 | {code} | {trade_date}"]
# after
lines = [
    f"# 行业横向对比 | {code}",
    f"# ⚠️ 实时快照，数据截至 {datetime.now():%Y-%m-%d %H:%M}，不代表 {trade_date} 的历史状态",
]
```

**Step 5.** Lock the classification down with a test that fails when someone adds a new tool
without classifying it:

```python
def test_every_exported_tool_is_classified():
    exported = {n for n in dir(a_stock) if n.startswith("get_") and callable(getattr(a_stock, n))}
    unclassified = exported - a_stock.LIVE_ONLY_TOOLS - POINT_IN_TIME_TOOLS
    assert not unclassified, f"classify these in LIVE_ONLY_TOOLS or POINT_IN_TIME_TOOLS: {unclassified}"
```

### F4.2 — `get_global_news` never filters (real fix, not just labelling)

**Severity: Critical** · `a_stock.py:1206-1293`

```python
start_dt = datetime.strptime(curr_date, "%Y-%m-%d") - relativedelta(days=look_back_days)
start_date = start_dt.strftime("%Y-%m-%d")
# ... fetch CLS + Eastmoney wire, no comparison against start_dt/curr_date ...
return f"## China & Global Market News, from {start_date} to {curr_date}:\n\n" + news_str
```

`start_dt` is used only to build the header. Both feeds carry timestamps, so this one is
genuinely fixable rather than live-only. Model the fix on the sibling `get_news`
(1138-1183), which filters correctly.

```python
end_dt = datetime.strptime(curr_date, "%Y-%m-%d")
kept = []
for n in unique:
    pub_dt = _parse_news_time(n.get("time"))
    if pub_dt is None:
        logger.debug("global_news: dropping item with unparseable time %r", n.get("time"))
        continue                      # fail closed — see F4.3
    if start_dt <= pub_dt <= end_dt:
        kept.append(n)
for n in kept[:limit]:
    ...
```

Factor `_parse_news_time` out so `get_news` and `get_global_news` share one implementation
and cannot drift again.

### F4.3 — `get_news` fails open on unparseable dates

**Severity: Medium** · `a_stock.py:1162-1183`

```python
try:
    pub_dt = datetime.strptime(pub_time[:10], "%Y-%m-%d")
    if pub_dt < start_dt or pub_dt > end_dt:
        continue
except (ValueError, IndexError):
    pass          # falls through and appends the article anyway
```

The `except` skips the *filter*, not the *article*. Change `pass` to `continue` and log at
debug level. A dropped article is a smaller error than a lookahead leak.

### F4.4 — Alpha Vantage lookahead filter is dead code

**Severity: Critical** · `alpha_vantage_fundamentals.py:10-18`

```python
if not curr_date or not isinstance(result, dict):
    return result                    # always returns here
```

`_make_api_request` is annotated `-> dict | str` but its only return statement is
`return response_text` (`alpha_vantage_common.py:83`), a string. The guard has never been
true, so balance sheet, cash flow and income statement have never been filtered.

**Fix.** Parse before filtering, and re-serialize so the return type stays stable for callers:

```python
def _filter_reports_by_date(result, curr_date: str):
    if not curr_date:
        return result
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            return result            # genuine CSV payload — nothing to filter
    else:
        parsed = result
    if not isinstance(parsed, dict):
        return result
    for key in ("annualReports", "quarterlyReports"):
        if key in parsed:
            parsed[key] = [r for r in parsed[key]
                           if r.get("fiscalDateEnding", "") <= curr_date]
    return json.dumps(parsed) if isinstance(result, str) else parsed
```

Also fix the annotation on `_make_api_request` to `-> str`, which is what it actually returns.

**Test:**

```python
def test_filter_strips_future_fiscal_periods():
    payload = json.dumps({"quarterlyReports": [
        {"fiscalDateEnding": "2026-03-31"}, {"fiscalDateEnding": "2026-09-30"}]})
    out = json.loads(_filter_reports_by_date(payload, "2026-06-30"))
    assert [r["fiscalDateEnding"] for r in out["quarterlyReports"]] == ["2026-03-31"]
```

### F4.5 — Alpha Vantage CSV filter fails open

**Severity: Medium** · `alpha_vantage_common.py:119-122`

```python
except Exception as e:
    print(f"Warning: Failed to filter CSV data by date range: {e}")
    return csv_data
```

Returns the full unfiltered payload on any parse failure, silently widening the window past
`curr_date`. Raise instead of returning.

While here, replace `print` with `logger.warning`. There are five `print` calls left in the
data layer — `utils.py:53`, `y_finance.py:167,240`, `alpha_vantage_indicator.py:221` and this
one — all of which write diagnostics to stdout where the Streamlit UI cannot show them and
the CLI's Rich layout corrupts them. Convert all five.

### F4.6 — `bfill` pulls future prices backwards

**Severity: Medium** · `stockstats_utils.py:40-43`

```python
data = data.dropna(subset=["Close"])
data[price_cols] = data[price_cols].ffill().bfill()
```

`bfill` runs on the full downloaded window before the `curr_date` cutoff is applied, so a
NaN gap before the cutoff can be filled from a bar after it.

**Fix.** Drop `bfill` entirely — `ffill` alone is the only direction that is
information-preserving in a time series. If leading NaNs must be handled, slice to the
cutoff *first*, then fill:

```python
data = data[data["Date"] <= cutoff]
data[price_cols] = data[price_cols].ffill()
data = data.dropna(subset=price_cols)      # drop any remaining leading gap
```

### F4.7 — Lockup "history" section includes future unlocks

**Severity: High** · `a_stock.py:2031-2047`

The `RPT_LIFT_STAGE` query filters on `SECURITY_CODE` only, so upcoming unlock events appear
under a heading labelled 个股解禁记录 (historical records).

```python
filter_str=f'(SECURITY_CODE="{code}")(FREE_DATE<=\'{trade_date}\')'
```

Keep future unlocks if they are wanted — that is legitimate forward-looking supply
information a real analyst would have — but put them under a separate, correctly labelled
`## 未来解禁计划` heading so the model is not told the future is the past.

### F4.8 — Per-function work for the six live-only endpoints

For each of the six in `LIVE_ONLY_TOOLS`: add the `_reject_if_not_point_in_time` guard, fix
the header per F4.1 step 4, and update the docstring and the `Annotated[...]` tool
description so the LLM knows what it is getting. `get_profit_forecast` already documents
`curr_date` as "unused, for interface compat" — make the other five equally honest.

`get_fundamentals` (719-886) is the one worth splitting rather than just labelling: it mixes
genuinely point-in-time mootdx financial data with live Tencent/Eastmoney valuation. Separate
the two blocks under distinct headings so the historical half stays usable in strict mode.

Also in `get_fundamentals`, fix the EPS fallback at 818-821:

```python
try:
    mean_eps = float(mean_eps_val)
except (ValueError, TypeError):
    mean_eps = 0          # a parse failure becomes a real-looking number
```

Use `None` and skip the derived forward-PE/PEG lines entirely when it is missing, rather
than letting a partial HTML-table misparse produce a small positive value that flows into a
valuation ratio.

---

## Phase 5 — Pipeline robustness (P2)

**Effort: ~2 days.**

### F5.1 — Recursion limit is both dead config and too low

**Severity: High** · `trading_graph.py:261`, `propagation.py:14`, `default_config.py:63`

```python
self.propagator = Propagator()          # config["max_recur_limit"] never read
```

The documented config key is inert. And 100 is marginal for the default 7-analyst pipeline:
each analyst tool call costs two graph steps (analyst → tools → analyst), the market analyst
alone can spend ~18, and seven analysts plus the gate, four debate nodes, trader, nine risk
nodes and the PM lands between 80 and 135 depending on how many indicators the model
requests.

**Fix:**

```python
self.propagator = Propagator(
    max_recur_limit=self.config.get("max_recur_limit", 250)
)
```

```python
# default_config.py
# LangGraph step budget. Each analyst tool call costs 2 steps (analyst → tools →
# analyst); 7 analysts requesting ~8 indicators each plus the gate, debates, trader,
# risk trio and PM reaches ~135 in the worst case. 250 leaves headroom without
# masking a genuine loop.
"max_recur_limit": 250,
```

**Test:** assert the config value reaches `get_graph_args()`:

```python
def test_recursion_limit_is_configurable():
    ta = TradingAgentsGraph(config={**DEFAULT_CONFIG, "max_recur_limit": 42}, ...)
    assert ta.propagator.get_graph_args()["config"]["recursion_limit"] == 42
```

### F5.2 — Memory log: lookahead and unlocked appends

**Severity: High** · `memory.py:41-50, 71-96`

Two separate defects in one file.

**Lookahead.** `get_past_context` selects resolved entries by file order with no date
comparison, and `trading_graph.py:513` calls it without `trade_date`. Each entry carries
realized returns and a hindsight reflection, so a walk-forward backtest feeds the Portfolio
Manager the future.

```python
def get_past_context(self, ticker, n_same=5, n_cross=3, before_date: str | None = None):
    entries = [e for e in self.load_entries() if not e.get("pending")]
    if before_date:
        entries = [e for e in entries if e["date"] < before_date]
```

```python
# trading_graph.py:513
past_context = self.memory_log.get_past_context(company_name, before_date=str(trade_date))
```

**Unlocked append.** `store_decision` does a read-check-append with no lock while
`update_with_outcome` correctly uses temp-file + `os.replace()`. Concurrent ticker runs can
interleave bytes into the markdown log, and a corrupted log breaks `load_entries` for every
subsequent run — the damage outlives the race.

Add a small cross-platform lock (avoid `fcntl`, which does not exist on Windows — this
project is being developed on Windows):

```python
class _FileLock:
    """Advisory lock via O_CREAT|O_EXCL, with stale-lock recovery."""
    def __init__(self, target: Path, timeout: float = 10.0, stale_after: float = 60.0):
        self._path = target.with_suffix(target.suffix + ".lock")
        self._timeout, self._stale_after = timeout, stale_after

    def __enter__(self):
        deadline = time.time() + self._timeout
        while True:
            try:
                fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                age = time.time() - self._path.stat().st_mtime
                if age > self._stale_after:
                    self._path.unlink(missing_ok=True)
                    continue
                if time.time() > deadline:
                    raise TimeoutError(f"could not acquire {self._path}")
                time.sleep(0.05)

    def __exit__(self, *exc):
        self._path.unlink(missing_ok=True)
```

Wrap `store_decision`, `update_with_outcome` and `batch_update_with_outcomes` in it. Reuse it
for the northbound cache (F3.4).

**Test:**

```python
def test_concurrent_store_decision_does_not_corrupt(tmp_path):
    log = MemoryLog({"memory_log_path": str(tmp_path / "m.md")})
    with ThreadPoolExecutor(max_workers=8) as pool:
        pool.map(lambda i: log.store_decision(f"60000{i}", "2026-05-12", f"Rating: Hold #{i}"), range(8))
    assert len(log.load_entries()) == 8
```

### F5.3 — Quality gate never blocks, and mis-grades unselected analysts

**Severity: High** · `quality_gate.py:131-166`, `setup.py:164`

Two problems. The gate produces a summary string and has no path to halt the graph, so
analysts that returned empty content still flow into the debate and the final decision. And
it always grades all seven `REPORT_FIELDS` regardless of which analysts actually ran — with
three or fewer selected, the unselected ones grade F for being empty, `fail_count >= 4`
trips, and the LLM review is skipped on a false premise.

**Fix, part 1 — only grade what ran:**

```python
def create_quality_gate(llm, selected_analysts=None):
    fields = {k: v for k, v in REPORT_FIELDS.items()
              if selected_analysts is None or k in selected_analysts}
    ...
    # scale the skip threshold to the number of analysts actually run
    if fail_count < max(2, len(fields) // 2 + 1):
        ...
```

Thread `selected_analysts` through from `setup.py:102`.

**Fix, part 2 — make failure visible and optionally fatal:**

```python
return {
    "data_quality_summary": summary,
    "data_quality_failed": fail_count >= max(2, len(fields) // 2 + 1),
}
```

Add `data_quality_failed: bool` to `AgentState`, and a conditional edge:

```python
# setup.py — replace  workflow.add_edge("Quality Gate", "Bull Researcher")
workflow.add_conditional_edges(
    "Quality Gate",
    self.conditional_logic.should_continue_after_quality_gate,
    {"Bull Researcher": "Bull Researcher", END: END},
)
```

```python
# conditional_logic.py
def should_continue_after_quality_gate(self, state) -> str:
    if state.get("data_quality_failed") and self.quality_gate_policy == "block":
        return END
    return "Bull Researcher"
```

Default `quality_gate_policy` to `"warn"` so existing behaviour is preserved; document
`"block"` in the README config table. Either way, render the flag in the final report so a
degraded run is visibly degraded.

### F5.4 — Reflection measures outcomes with yfinance

**Severity: Medium** · `trading_graph.py:391-406`

```python
stock = yf.Ticker(yf_symbol).history(start=trade_date, end=end_str)
benchmark = yf.Ticker("000300.SS").history(start=trade_date, end=end_str)
```

The README states the project deliberately avoids Yahoo Finance because it does not support
A-shares, yet the learning loop depends on it. Adjustment and suspension handling differ from
the mootdx/Tencent data the decision was made on, so the alpha figures written into memory
are wrong — and those figures are what the Portfolio Manager learns from.

**Fix.** Re-implement `_fetch_returns` on `_load_ohlcv_astock` for the stock and CSI 300
(mootdx index code `999300`, or Sina `sh000300` — verify which the loader accepts). Two
secondary corrections while in here:

- Entry price: the decision is made *on* `trade_date`, so measuring from that day's close is
  not executable. Use the next session's open to model a realistic T+1 entry.
- BSE tickers currently fail yfinance resolution and stay `pending` forever (see F7.3);
  moving to the A-share loader fixes that as a side effect.

### F5.5 — Agent SDK subprocess has no timeout

**Severity: High** · `claude_agent_sdk_client.py:218-244`

```python
thread = threading.Thread(target=_worker)
thread.start()
thread.join()          # no timeout, no cancellation
```

A hung `claude` CLI wedges the whole graph with no recovery.

```python
timeout = self.kwargs.get("timeout", _DEFAULT_SDK_TIMEOUT)   # e.g. 600s
thread = threading.Thread(target=_worker, daemon=True)
thread.start()
thread.join(timeout)
if thread.is_alive():
    raise _SDKResultError(
        f"Agent SDK call exceeded {timeout}s. The `claude` CLI subprocess may be hung; "
        f"check for orphaned processes."
    )
```

`_SDKResultError` is in `_FALLBACK_ERRORS`, so a timeout correctly falls back to the paid
provider rather than aborting — that is the desired behaviour here, unlike auth failure.
Mark the thread `daemon=True` so a hung worker cannot block interpreter exit.

### F5.6 — Greedy JSON extraction

**Severity: Medium** · `claude_agent_sdk_client.py:207-215`

```python
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
```

Greedy from the first `{` to the last `}`. A response with prose plus an example schema plus
the real payload yields a span that is not valid JSON, which then routes into F1.2's
fallback.

**Fix.** Scan for balanced braces and return the first span that parses, preferring the last
such span (models tend to restate the final answer at the end):

```python
def _extract_json(text: str) -> str:
    candidates, depth, start = [], 0, None
    for i, ch in enumerate(text or ""):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                candidates.append(text[start:i + 1])
    for candidate in reversed(candidates):
        try:
            json.loads(candidate)
            return candidate
        except json.JSONDecodeError:
            continue
    raise ValueError("no parseable JSON object found in Agent SDK text response")
```

Does not handle braces inside string literals; acceptable given `json.loads` validates each
candidate before it is returned.

### F5.7 — Fallback LLM built without the primary's tuning kwargs

**Severity: Medium** · `trading_graph.py:217-224`

```python
fallback_spec = {
    "provider": _fb_provider or self.config["llm_provider"],
    "model": _fb_model or self.config[fallback_model_key],
    "base_url": None if cross_provider else self.config.get("backend_url"),
    **({"callbacks": self.callbacks} if self.callbacks else {}),
}
```

Primary clients get `_get_provider_kwargs()` — `reasoning_effort`, `thinking_level`,
`timeout`. The fallback gets none of them, so the degraded path runs untimed and untuned at
exactly the moment things are already failing. Dropping `backend_url` across providers is
correct and tested; merge the rest in:

```python
_fb_provider_resolved = _fb_provider or self.config["llm_provider"]
fallback_spec = {
    "provider": _fb_provider_resolved,
    "model": _fb_model or self.config[fallback_model_key],
    "base_url": None if cross_provider else self.config.get("backend_url"),
    **self._get_provider_kwargs(_fb_provider_resolved),
    **({"callbacks": self.callbacks} if self.callbacks else {}),
}
```

Note `_get_provider_kwargs` must be called with the *fallback's* provider, not the primary's,
so an Anthropic-effort setting is not forwarded to an OpenAI fallback.

### F5.8 — Dragon-tiger `UnboundLocalError` swallowed

**Severity: Medium** · `a_stock.py:1906, 1936, 1979`

`data` is bound inside the first `try`. If that call raises, `if data:` raises
`UnboundLocalError`, which `except Exception: pass` discards — institutional seat detail
vanishes with no error line.

```python
data: list[dict] = []          # bind before the try
try:
    data = _eastmoney_datacenter(...)
except Exception as e:
    lines.append(f"龙虎榜列表查询失败: {e}")
...
except Exception as e:
    lines.append(f"席位明细查询失败: {e}")     # replace the bare `pass`
```

While here, sweep the file for other `except Exception: pass` blocks —
`grep -n -A1 "except Exception" a_stock.py | grep -B1 "pass"` — and give each one at least a
line in the output. A tool that silently returns a partial report is worse than one that says
which part is missing.

---

## Phase 6 — Front-end parity and UX (P2)

**Effort: ~2 days.** The CLI and web UI have diverged into two products with different
capabilities. Most of this phase is making the CLI match the web.

### F6.1 — `--checkpoint` does nothing

**Severity: High** · `cli/main.py:995, 1096-1105`

```python
config["checkpoint_enabled"] = checkpoint
...
init_agent_state = graph.propagator.create_initial_state(
    selections["ticker"], selections["analysis_date"]
)
args = graph.propagator.get_graph_args(callbacks=[stats_handler])
for chunk in graph.graph.stream(init_agent_state, **args):
```

Setting the config key only matters if `prepare_graph_run()` runs — that is what recompiles
with `SqliteSaver`, injects `thread_id` and returns `None` as the initial state to trigger
resume. The CLI never calls it, so `--checkpoint` always restarts from scratch.

**Fix.** Mirror `web/runner.py:103`:

```python
init_agent_state, args, resume_step = graph.prepare_graph_run(
    selections["ticker"], selections["analysis_date"], callbacks=[stats_handler],
)
if resume_step is not None:
    console.print(f"[yellow]从断点续跑：已完成 {resume_step} 步[/yellow]")
for chunk in graph.graph.stream(init_agent_state, **args):
```

And at the end, replace the manual signal handling with `finalize_graph_run` so the CLI also
writes `full_states_log_*.json` and therefore shows up in the web history browser
(currently it does not):

```python
signal = graph.finalize_graph_run(selections["ticker"], selections["analysis_date"], final_state)
```

### F6.2 — CLI crashes on empty stream or missing key

**Severity: Medium** · `cli/main.py:1204-1206`

```python
final_state = trace[-1]
decision = graph.process_signal(final_state["final_trade_decision"])
```

`IndexError` on an empty stream, `KeyError` on a partial state. `web/runner.py:152` guards
both.

```python
if not trace:
    console.print("[red]分析未产生任何输出，请检查 LLM 配置与网络连接。[/red]")
    raise typer.Exit(code=1)
final_state = trace[-1]
if not final_state.get("final_trade_decision"):
    console.print("[red]分析未产生最终决策（pipeline 可能中途失败）。[/red]")
    raise typer.Exit(code=1)
```

### F6.3 — CLI exposes only 4 of 7 analysts

**Severity: High** · `cli/models.py:6-10`

```python
class AnalystType(str, Enum):
    MARKET = "market"
    SOCIAL = "social"
    NEWS = "news"
    FUNDAMENTALS = "fundamentals"
```

The three A-share specializations that are the stated reason this fork exists cannot be run
from the CLI at all.

```python
class AnalystType(str, Enum):
    MARKET = "market"
    SOCIAL = "social"
    NEWS = "news"
    FUNDAMENTALS = "fundamentals"
    POLICY = "policy"
    HOT_MONEY = "hot_money"
    LOCKUP = "lockup"
```

Note there are **two** `ANALYST_ORDER` definitions that must be kept in sync, which is its
own latent bug:

- `cli/main.py:846` — `["market", "social", "news", "fundamentals"]`, used at 875 and 1002 to
  order the selection
- `cli/utils.py:13` — a list of `(display, value)` pairs driving the `select_analysts()`
  checkbox at 89-94

Collapse these into one definition (keep the `(display, value)` form in `cli/utils.py` and
derive the key order from it in `main.py`) rather than adding three entries to each. Also
update the display-name map used by `message_buffer.init_for_analysis`.

Verify the `.capitalize()` node-name convention holds for `hot_money` — `setup.py:121` builds
`"Hot_money Analyst"` and the review confirmed the Msg Clear node matches, so no graph change
is needed, but the CLI's display names must not diverge from those node names.

### F6.4 — Web accepts future analysis dates

**Severity: High** · `web/components/sidebar.py:306-310`

`cli/main.py:652` validates this; the Streamlit input does not.

```python
trade_date = st.date_input(
    "分析日期",
    value=date.today(),
    max_value=date.today(),
    key="input_date",
)
```

Apply the same to the `start_date` input at 312 (`max_value=trade_date`), which should also
never exceed the analysis date.

### F6.5 — XSS via LLM-derived names in `unsafe_allow_html`

**Severity: Medium** · `web/components/report_viewer.py:65-86`

`ticker_label` comes from `stock_display_label()`, which can lift a name out of `final_state`
or an LLM report. `_clean_stock_name()` filters to printable characters, which does not
exclude HTML.

```python
import html
...
{html.escape(ticker_label)} · {html.escape(str(trade_date))}
```

Audit every other `unsafe_allow_html=True` in `web/` for interpolated non-constant values —
`grep -rn "unsafe_allow_html" web/`. Local single-user app, so exposure is limited, but the
sanitizer currently looks like it handles this and does not.

### F6.6 — Stop does not cancel in-flight work

**Severity: Medium** · `web/runner.py:121-128`

Stop is checked only at stream chunk boundaries, so a daemon thread keeps running inside a
blocking LLM call for minutes while the UI shows 停止中..., still spending API credit.

Full cancellation needs timeout support threaded through the LLM clients (see F5.5), which
is the real fix. Two things worth doing now regardless:

- Set the client `timeout` kwarg from config so a blocking call has a bounded worst case.
- Fix the stop/incomplete-task race: `sidebar.py:118` calls `clear_incomplete_task()` while
  the worker may still call `record_incomplete_task()` at `runner.py:138`. Have the worker
  check `tracker.stop_requested` before recording, and pass
  `completed_stages=list(tracker.completed_stages)` — line 142 currently passes the live
  mutable list, which `request_stop()` can clear mid-serialization.

### F6.7 — PDF regenerated on every rerun

**Severity: Medium** · `web/components/report_viewer.py:102-104`

`render_report` runs on every rerun in the completed state, and `app.py:260` reruns every two
seconds. Cache on report content:

```python
@st.cache_data(show_spinner=False, max_entries=8)
def _cached_pdf(state_digest: str, ticker: str, trade_date: str, signal: str) -> bytes:
    return generate_pdf(...)
```

Key on a stable digest of the final state, not the dict itself (unhashable). While here,
replace the `time.sleep(2); st.rerun()` polling loop at `app.py:260-263` with
`st.fragment(run_every=2)` on the progress panel so the whole script does not re-execute.

---

## Phase 7 — Cleanup (P3)

**Effort: ~half day.**

### F7.1 — README documents a different default provider than ships

`default_config.py:15-17` sets `openai` / `gpt-5.4`; `README.md:286` says the default is
`minimax` / `MiniMax-M2.7`. A user following the README's MiniMax section and omitting the
config key gets an OpenAI key error. Pick one and make both agree — given the README's
"推荐，国内直连" framing, changing the code default to `minimax` is probably the intent.

### F7.2 — Mutable list as a default argument

`trading_graph.py:135` and `setup.py:30`. Nothing mutates it today, so this is latent:

```python
def __init__(self, selected_analysts: list[str] | None = None, ...):
    selected_analysts = list(selected_analysts or DEFAULT_ANALYSTS)
```

Define `DEFAULT_ANALYSTS` once as a module-level tuple and reference it from both files —
they currently duplicate the same seven-element literal.

### F7.3 — Pending memory entries never pruned

`memory.py:221-256`. Documented behaviour, but entries for tickers the outcome fetcher cannot
resolve stay pending permanently and accumulate every run, so `memory_log_max_entries` cannot
bound the file. F5.4 removes the main cause (BSE codes failing yfinance); additionally, expire
pending entries older than a configurable horizon:

```python
"memory_pending_max_age_days": 90,   # unresolvable entries are dropped after this
```

### F7.4 — `log_states_dict` grows without bound

`trading_graph.py:268, 572`. Every `propagate()` adds a full state dict keyed by date and
nothing evicts. Only the per-date JSON is actually consumed, so the in-memory copy can be
dropped after `_log_state` writes it, or capped with a small `deque`.

### F7.5 — Root-level test scripts excluded from pytest

`pyproject.toml:84` sets `testpaths = ["tests"]`, so `test_astock.py`, `test_data_quality.py`
and `test.py` at the repo root are never collected. They need live APIs, so they should not
run in normal CI — but they should be runnable and maintained. Move them to
`tests/integration/`, mark them `@pytest.mark.integration` (the marker is already declared in
`pyproject.toml:87-90`), and add `-m "not integration"` to the default `addopts`. Then a
nightly job can run `-m integration` and actually catch data-source rot.

### F7.6 — Missing HTTP timeout

`alpha_vantage_common.py:66`: `requests.get(API_BASE_URL, params=api_params)` — add
`timeout=15` to match every other HTTP call in the codebase.

### F7.7 — `openai_compatible` silently reuses `OPENAI_API_KEY`

`openai_client.py:188-191`. This is deliberate and documented, and there is a test asserting
it — but the provider exists to point at third-party relays, so a user with `OPENAI_API_KEY`
already in `.env` ships their real OpenAI secret to a relay operator without any prompt. Do
not change the behaviour; warn when the fallback actually fires and the base URL is not an
OpenAI domain:

```python
if not os.environ.get("OPENAI_COMPATIBLE_API_KEY") and api_key:
    if "openai.com" not in (self.base_url or ""):
        logger.warning(
            "openai_compatible: OPENAI_COMPATIBLE_API_KEY 未设置，正在把 OPENAI_API_KEY "
            "发送到第三方网关 %s。如不是你的预期，请单独设置 OPENAI_COMPATIBLE_API_KEY。",
            self.base_url,
        )
```

### F7.8 — Gemini 2.5 thinking levels collapse to off

`google_client.py:64-74`: for non-Gemini-3 models, `"minimal"`, `"low"` and `"medium"` all map
to `thinking_budget=0`. Map to real budgets, or warn that the level is unsupported for the
selected model rather than silently disabling thinking.

---

## Test plan

New test files, in the order they should be written:

| File | Covers | Blocks |
|---|---|---|
| `tests/test_rating_parser.py` | F1.1 — negation, compound nouns, label precedence, conclusion-wins ordering | Phase 1 |
| `tests/test_structured_fallback.py` | F1.2 — schema error falls back, transient error propagates, marker present | Phase 1 |
| `tests/test_em_throttle.py` | F2.2 — concurrent serialization, thread-local sessions | Phase 2 |
| `tests/test_market_routing.py` | F3.1 — secid/sina symbol for SH, SZ, ChiNext, STAR, BSE 8xx and 92x | Phase 3 |
| `tests/test_lookahead.py` | F4.* — every point-in-time tool respects its cutoff; classification completeness | Phase 4 |
| `tests/test_quality_gate.py` | F5.3 — only selected analysts graded, threshold scales, block policy halts | Phase 5 |
| `tests/test_cli_analyze.py` | F6.1-F6.3 — checkpoint resume, empty stream, 7 analysts available | Phase 6 |
| `tests/test_graph_e2e.py` | Phase 0 — full pipeline with stub LLM | all |

Extend existing files:

- `tests/test_agent_sdk_provider.py` — the three auth-vs-fallback cases in F2.1.
- `tests/test_memory_log.py` — date filtering (F5.2) and the concurrency test.
- `tests/test_market_prefix_routing.py` — fold in the BSE call-site assertions.

**Regression discipline.** Each fix below Critical should land with a test that fails before
the change. For the lookahead work specifically, the test shape that matters is: freeze
"now", request a past date, and assert no returned value could only be known after that date.

---

## PR sequencing

Ten PRs. Each is independently reviewable and shippable; later phases assume the Phase 0
fixtures exist.

| # | Scope | Findings | Effort | Depends on |
|---|---|---|---|---|
| 1 | Test fixtures, stub-LLM E2E test, CI workflow | Phase 0 | 1d | — |
| 2 | Rating parser hardening + analyst prompt cleanup | F1.1, F1.3 | 0.5d | 1 |
| 3 | Structured-output fallback narrowed and marked | F1.2 | 0.5d | 1 |
| 4 | Agent SDK auth classification + subprocess timeout | F2.1, F5.5, F5.6 | 1d | 1 |
| 5 | Eastmoney throttle lock + thread-local sessions | F2.2 | 0.5d | 1 |
| 6 | BSE routing, unit normalization, mootdx thread-safety | F3.1-F3.4 | 2d | 1, 5 |
| 7 | Recursion limit, memory lock + date filter, quality gate | F5.1-F5.3 | 1.5d | 1 |
| 8 | Lookahead: contract, classification, per-function fixes | F4.1-F4.8 | 3d | 1, 5, 6 |
| 9 | CLI parity: checkpoint, guards, 7 analysts, history JSON | F6.1-F6.3 | 1d | 1, 7 |
| 10 | Web: date bounds, escaping, PDF cache, stop race; cleanup | F6.4-F6.7, Phase 7 | 1.5d | 1 |

**Total: ~13 working days.** PRs 2-5 are the highest value per hour and could ship in the
first week. PR 8 is the largest and benefits from 6 landing first, since both touch
`a_stock.py` heavily and would otherwise conflict.

**Sequencing note.** PRs 2 and 3 are listed separately but should ship together or
back-to-back: F1.2 reduces how often the free-text path fires, and F1.1 fixes what happens
when it does. Shipping only one leaves the composed failure mode partly open.

---

## Out of scope

Deliberately not addressed here, but worth tracking:

- **Prompt injection from scraped news** (Medium). Scraped Chinese headlines are interpolated
  verbatim into the quality gate, both researchers, all three risk debators and the Portfolio
  Manager, with no delimiting or instruction-hierarchy hardening. A real fix means wrapping
  untrusted content in explicit delimiters and adding a standing instruction that content
  inside them is data, not instructions — a prompt-engineering project affecting every agent,
  and worth its own design pass.
- **`cli/main.py` decomposition.** At 1,107 lines it duplicates substantial logic from
  `web/runner.py`. The parity fixes in Phase 6 will make the duplication worse before it gets
  better; extracting a shared run-orchestration module is the follow-up.
- **`a_stock.py` decomposition.** 1,816 lines in one module is the root cause of several
  findings here (five copies of the exchange split, inconsistent unit handling, inconsistent
  error handling). Splitting by data domain — quotes, financials, signals, news — would make
  the next review much cheaper. Do it after Phase 8, not before, to avoid conflicting with
  the lookahead work.
