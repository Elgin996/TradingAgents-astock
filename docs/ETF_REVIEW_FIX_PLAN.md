# ETF 改造 Code Review 修复方案

> 状态：已实施
> 评审范围：`b631bec` / `2dfbbf0` / `4e23ceb`（60 个文件，约 +4300 行）
> 评审日期：2026-08-09
> 实施日期：2026-08-09
> 基线：`python -m pytest tests/ -v` 当前 344 passed / 1 skipped，全绿

本文件只记录**需要改动**的问题、根因、修复方式与验收方式。评审确认没有问题的部分（能力清单驱动的分析师/阶段/报告裁剪、`route_to_vendor` 前置能力断言、提示词单正文+注入块、阶段 0 数据源表）不在本文范围内。

已验证的前提：LangGraph 同步执行使用 `copy_context()` + `ctx.run`（`langgraph/pregel/_executor.py:64`），因此 `capability_guard` 的 `ContextVar` 能正确传递到图节点，工具硬禁用机制本身成立，不需要改造为线程安全容器。

---

## 0. 修复批次与顺序

| 批次 | 内容 | 理由 |
|---|---|---|
| 批次 1 | §1 证券分类、§2 交易所路由 | 当前会产出**错误的分析对象与错误的行情**，优先级最高 |
| 批次 2 | §3 历史记录形状、§4 个股提示词语义回归 | 功能缺失与既有能力退化，用户可感知 |
| 批次 3 | §5 东财限流与缓存、§6 前视偏差 | 稳定性与数据纪律，不改变对外行为 |
| 批次 4 | §7 质量门控、§8 新闻缓存、§9 文档同步、§10 杂项 | 收尾 |

每批次结束后跑 `python -m pytest tests/ -q`，批次 1、2 结束后另需按 §11 做一次真实标的冒烟。

---

## 1. 【阻断】货币 ETF 与场内 LOF 被静默降级为个股分析

### 现象（已用实盘数据复现）

| 代码 | 基金全称 | 基金类型 | 当前分类 | 后果 |
|---|---|---|---|---|
| `511990` 华宝添益 | 华宝现金添益**交易型货币市场基金** | 货币型-普通货币 | `not_etf` | 进入个股流程，跑基本面/龙虎榜/解禁 |
| `511880` 银华日利 | 银华**交易型货币市场基金** | 货币型-普通货币 | `not_etf` | 同上 |
| `159001` | 易方达保证金收益货币市场基金 | 货币型-普通货币 | `not_etf` | 同上 |
| `161725` 招商中证白酒 | 招商中证白酒指数证券投资基金**(LOF)** | 指数型-股票 | `not_etf` | 同上 |
| `110020` 沪深300ETF**联接** | 易方达沪深300交易型开放式指数发起式证券投资基金联接基金 | 指数型-股票 | `domestic_equity_etf` | 误判为可分析 ETF（当前仅靠不在交易所名册而侥幸拦下） |

违反 `ETF_ANALYSIS_PLAN.md` §2.2、§7.1「识别到排除类型时…**不得自动降级为个股分析**」。

### 根因

`tradingagents/dataflows/security_master.py:115-127` 用基金全称的子串判断「是不是 ETF」：

```python
is_etf = "交易型开放式" in full_name
if not is_etf:
    return "not_etf", "基金全称不包含“交易型开放式”"
```

`not_etf` 在 `web/components/sidebar.py:176` 被直接映射为 `"stock"`。于是「这是一只基金，但不是我们支持的 ETF」和「这根本不是基金，是股票」被合并成了同一个分支。

### 修复方式

**1.1 拆分分类枚举**，把「非基金」和「基金但不支持」分开：

```python
FundClassification = Literal[
    "domestic_equity_etf",   # 支持
    "unsupported_fund",      # 是基金，但不在支持范围 → 拒绝，不降级
    "not_a_fund",            # 档案页为占位符，真正的非基金 → 走个股
]
```

**1.2 用占位符识别真正的非基金。** 实测 `600519` 的档案页返回 `基金全称 = "---"`、`基金类型 = "---"`（表格结构存在，只是无内容）。判定顺序改为：

1. `基金全称` 或 `基金类型` 属于占位符集合 `{"---", "--", "-", ""}` → `not_a_fund`；
2. 全称含 `联接` → `unsupported_fund`（联接基金，§2.2 排除；不能依赖「不在交易所名册」当拦截手段）；
3. 全称不含 `交易型开放式` → `unsupported_fund`（覆盖货币 ETF「交易型货币市场基金」与 LOF）；
4. `基金类型 != "指数型-股票"` → `unsupported_fund`（现有逻辑，已验证可正确拒绝债券/黄金/商品/QDII/主动型）；
5. 无跟踪标的或为「该基金无跟踪标的」→ `unsupported_fund`；
6. 其余 → `domestic_equity_etf`。

**1.3 同步改 sidebar 映射**（`web/components/sidebar.py:119-176`）：

- `not_a_fund` → `("stock", None, None)`
- `unsupported_fund` → `("unsupported", None, f"当前版本不支持该类型：{reason}")`
- 删除现有靠异常字符串匹配 `"no parseable Eastmoney fund profile"` 判定个股的分支——占位符判定生效后，正常股票会走 `not_a_fund`，不再依赖解析失败。

**1.4 解析失败的语义。** 改动后，`_fetch_profile_fields` 抛错只意味着「档案页结构变化或网络异常」，按 §7.2 第 6 条应归为 `unknown`（提示重试、禁用开始），不得按代码前缀推断。

> ⚠️ 可用性权衡：若东财档案页改版，所有标的（含个股）都会被判为 `unknown` 而无法开始分析。缓解手段：`resolve_fund_master` 按交易日缓存（见 §5.2），并在解析失败时打 `logger.error` 便于发现。**如果不接受这个风险，需要显式决策是否允许「解析失败 + 代码不在 `5xxxxx`/`159xxx` 区间 → 按个股放行」的兜底，但这属于对 §7.2 的破例，应写进方案而不是悄悄实现。**

### 验收

新增 `tests/test_security_master.py` 用例（用固定 HTML fixture，不打网络）：

- `511990`、`511880`、`159001` → `unsupported_fund`，且 sidebar 返回 `"unsupported"`
- `161725`（LOF）、`110020`（联接）→ `unsupported_fund`
- `600519` 占位符档案 → `not_a_fund` → sidebar 返回 `"stock"`
- `510300`、`159915`、`588000` → `domestic_equity_etf`（回归）
- `511260`（债券）、`518880`（黄金）、`513050`（QDII）→ `unsupported_fund`（回归）

---

## 2. 【阻断】`_get_prefix` 把深市股票 `000016` 路由到上交所

### 现象（已复现）

```
_get_prefix("000016") == "sh"      # 深康佳A（深市股票）
_em_secid("000016")   == "1.000016"
_sina_symbol("000016") == "sh000016"   # 实际取到的是上证50指数
```

改动前该代码返回 `sz`（正确）。这是阶段 -1 引入的**新回归**：分析 000016 深康佳A 会拿到上证50指数的 K 线。

### 根因

`tradingagents/dataflows/a_stock.py:40` 新增的 `_SH_INDEX_CODES` 被塞进了服务于**全部证券**的 `_get_prefix`（`a_stock.py:54-72`）。`000016` 在深市是股票、在沪市是指数，代码空间重叠，单一函数无法同时承担两种语义。

同样的混淆出现在证券主数据：`security_master.py:66-78` 按 `(0, SZSE) → (1, SSE)` 顺序写入同一个 dict，后写覆盖先写，因此 `_lookup_exchange("000016")` 返回 `SSE`（对股票而言错误）。

### 附带问题

`_SH_INDEX_CODES` 只有 5 个代码，未覆盖 `index_catalog` 的其余条目。实测这些全部落到 `sz` 并取不到数据：

`000906`（中证800）、`000510`（中证A500）、`000922`（中证红利）、`000015`（上证红利）、`000010`（上证180）

因此市场分析师被提示词要求做的「比较 ETF 与跟踪指数区间走势」，对这些指数一律失败。`_load_tracking_index_ohlcv`（`trading_graph.py:351`）因为自带 sh/sz 双前缀重试而不受影响，这正是问题被掩盖的原因。

### 修复方式

**2.1 `_get_prefix` 回退为纯证券路由**：删除 `if code in _SH_INDEX_CODES: return "sh"`，恢复为 `92→bj`、`8→bj`、`5/6/9→sh`、其余 `sz`。ETF 的 `5xxxxx`/`159xxx` 修复保留（那部分没有代码空间冲突）。

**2.2 新增独立的指数路由**，与证券路由分离：

```python
# 指数代码 → 交易所，来源与 index_catalog 一致，二者必须同步
_INDEX_EXCHANGE: dict[str, str] = {...}   # 覆盖 index_catalog 全部条目

def _index_symbol(code: str) -> str: ...   # 供指数行情路径专用
```

`_INDEX_EXCHANGE` 与 `index_catalog._INDEX_CATALOG` 的键必须一致，加一个测试断言二者不漂移。

**2.3 指数行情走独立入口。** 不要让市场分析师用 `get_stock_data` 取指数。两种方案，推荐 A：

- **A（推荐）**：新增 `get_index_data` 工具（能力 `price_history`），内部用 `_index_symbol` + 现有 `_load_tracking_index_ohlcv` 的双前缀重试；ETF 模式下注册到 `market` ToolNode，提示词改为引导调用该工具。语义清晰，且 `_get_prefix` 永远不必知道指数。
- **B**：保持复用 `get_stock_data`，在函数入口按 `_INDEX_EXCHANGE` 命中时切换路由。改动小，但把两种代码空间继续压在一个工具里。

**2.4 修 `_exchange_memberships` 覆盖问题**（`security_master.py:66-78`）：改为 `setdefault` 语义（先写深市、后写沪市即先到先得），使 `000016 → SZSE`；对重复代码打 `logger.debug` 记录冲突，便于后续发现新的重叠。ETF 代码段（`5xxxxx`/`159xxx`）不存在跨市重复，不受影响。

### 验收

扩充 `tests/test_market_prefix_routing.py`：

- `_get_prefix("000016") == "sz"`、`_sina_symbol("000016") == "sz000016"`（回归本次问题）
- 现有沪深/北交所/ETF 用例全部保持
- `_INDEX_EXCHANGE` 覆盖 `index_catalog` 全部键（防漂移）
- `_index_symbol("000906") == "sh000906"`、`_index_symbol("399006") == "sz399006"`
- `_exchange_memberships` 在同代码跨市时返回深市（用 fake client 构造 `000016` 同时出现在 market 0 与 1）

---

## 3. 【阻断】历史列表里 ETF 徽标永远显示为 `[个股]`

### 根因

落盘写的是**扁平** state：

```python
# tradingagents/graph/trading_graph.py:824-826
json.dump(self.log_states_dict[str(trade_date)], f, indent=4)
```

读取按**日期为键**：

```python
# web/history.py:49-53
state = payload.get(date) if isinstance(payload, dict) else None
if isinstance(state, dict):
    entry["analysis_mode"] = state.get("analysis_mode", "stock")
```

`payload.get(date)` 恒为 `None`，`analysis_mode` / `instrument_profile` 从未写入 entry，`_history_mode_badge` 落到默认值 `"stock"`。`web/app.py:277` 按扁平结构读取同一文件并且工作正常，可确认扁平是实际格式。

`tests/test_web_history.py:42` 写的是嵌套结构，所以测试通过而生产失效——这是该问题逃过评审的直接原因。

### 修复方式

**3.1** 在 `web/history.py` 新增单一读取函数，兼容两种形状（旧日志可能确实存在嵌套版本）：

```python
def _load_state(path) -> dict:
    payload = json.load(...)
    if not isinstance(payload, dict):
        return {}
    inner = payload.get(date)          # 兼容历史嵌套格式
    return inner if isinstance(inner, dict) else payload
```

`get_history` 与 `app.py`（`load_analysis`）共用它，避免二次漂移。

**3.2** 修正 `tests/test_web_history.py:38-66`，用**扁平**结构作为主用例；嵌套结构另立一条「旧格式兼容」用例。

**3.3** 补一条端到端形状测试：调用 `TradingAgentsGraph._log_state` 写盘，再用 `get_history` 读回并断言 `analysis_mode == "etf"` 且 `instrument_profile.tracking_index_name` 可用。这条测试是本问题真正的护栏——只测 helper 无法发现读写不一致。

---

## 4. 【阻断】个股模式提示词语义退化

### 现象

`ETF_ANALYSIS_PLAN.md` §16.3 要求「提示词注入块改造后，**个股模式下渲染出的完整提示词与改造前语义等价**」。实际改造把个股侧的 A 股专属框架整段删除，替换为一行摘要：

```python
# tradingagents/agents/utils/agent_utils.py:182-186
return {
    "aggressive": "Consider A-share policy support, momentum, Northbound flow, and valuation upside.",
    "conservative": "Consider T+1, price-limit traps, policy reversals, lockups, hot-money exits, and valuation risk.",
    "neutral": "Balance T+1, policy sensitivity, sector rotation, valuation, and position sizing.",
}[posture]
```

丢失清单（均可从 `git show 336fd6f:<file>` 取回原文）：

| 节点 | 丢失内容 |
|---|---|
| `bull_researcher.py` | A-Share Bull Framework（政策顺风、北向资金、游资接力、估值成长、解禁出清）5 条 |
| `bear_researcher.py` | A-Share Bear Framework（政策逆风、解禁减持、游资撤退、估值泡沫、T+1 陷阱、北向撤离）6 条 |
| `aggressive_debator.py` | A-Share Aggressive Framework 6 条 |
| `conservative_debator.py` | A-Share Conservative Framework 7 条（含涨跌停板买盘真空、ST/退市、T+1 结算锁定的完整论述） |
| `neutral_debator.py` | A-Share Neutral Framework 7 条 |
| `portfolio_manager.py` | 交易约束中的 ST/退市风险、融资融券资格两条 |

注意：`build_general_debate_points` 里的「General bull/bear points」通用块**已正确保留**，`build_trading_constraints`（trader/PM）的个股完整规则也**已正确保留**——后者正是应该照抄的模式。

### 修复方式

不改架构，只补内容：

**4.1** `build_debate_framework(analysis_mode, side)`：`analysis_mode != "etf"` 分支返回改造前 bull/bear 的完整 A-Share Framework 原文（逐字）。
**4.2** `build_risk_framework(analysis_mode, posture)`：同理返回三个 debator 各自的完整 A-Share Framework 原文。
**4.3** `build_trading_constraints` 个股分支补回 ST/退市风险与融资融券资格两条。
**4.4** ETF 分支保持现状不动。

### 验收

新增 `tests/test_prompt_parity.py`：对 stock 模式断言若干关键短语存在（`涨跌停板` 相关英文原句、`Lockup Expiry Overhang`、`Northbound`、`PE digestion`、`ST/delisting` 等），并断言 ETF 模式下这些短语**不**出现。用短语断言而非全文比对，避免后续正常改文案时测试脆断。

---

## 5. 【重要】东财限流被绕过 + 主数据无缓存导致请求放大

### 问题

**5.1 裸 `requests.get` 打东财。** `security_master.py:88-97` 的 `_fetch_profile_fields` 直接 `requests.get("https://fundf10.eastmoney.com/jbgk_{code}.html")`，违反 `CLAUDE.md` 明确规则：「新增东财端点时务必走 `_em_get` 而非裸 `requests.get`」。该路径不参与全局节流与 Session 复用。

**5.2 `resolve_fund_master` 完全无缓存。** 被 sidebar 识别、`get_etf_profile` 工具、`get_etf_peer_comparison`、`_peer_row` 多处调用。Streamlit 每次 rerun 只要 `resolved_instrument_profiles` 未命中就重新打一次网络；个股输入也会白白打一次。

**5.3 Stage 3 请求扇出。** `get_etf_peer_comparison` 在 `etf_data.py:299` 调 `resolve_fund_master(symbol)`，随后 `_peer_row(symbol, ...)` 对同一个 symbol **再调一次**；每个 peer 各一次档案页 + 一次 `gmbd` + 一次腾讯行情。单次工具调用约 8 次档案页（不受节流）+ 8 次 gmbd + 行情。LLM 可能多次调用该工具。

### 修复方式

- `_fetch_profile_fields` 改走 `_em_get(url, headers=...)`（`_em_get` 已支持 `headers` 覆盖，见 `a_stock.py:363`）。
- `resolve_fund_master` 加按交易日的缓存：`@lru_cache` + 以 `(code, date.today().isoformat())` 为键的薄包装，符合 §7.5「产品类型…在每次新分析前进行轻量校验」且不会跨日僵化。
- `get_etf_peer_comparison` 复用已取得的 `record`，不要让 `_peer_row` 对 subject 重复解析；`_peer_row` 增加 `record` 可选入参。
- `web/components/sidebar.py:521` 的 `resolved_instrument_profiles` session 缓存加交易日维度（§7.5 要求按交易日缓存）。
- `_exchange_memberships` 的 `lru_cache(maxsize=1)` 同样加交易日键。

### 验收

- 单元测试：mock `_em_get`，断言 `_fetch_profile_fields` 调用它而非 `requests.get`
- 单元测试：连续两次 `resolve_fund_master("510300")` 只触发一次网络调用
- 单元测试：`get_etf_peer_comparison` 对 subject 的档案解析次数 == 1

---

## 6. 【重要】ETF 快照类工具存在前视偏差

### 问题

`get_etf_quote`（`etf_data.py:74`）、`get_etf_structure_alerts`（`etf_data.py:369`）以及 `get_etf_peer_comparison` 中的 `turnover_pct` / `float_mcap_yi`，都直接读 `_tencent_quote` 实时快照，且**函数签名里根本没有 `trade_date`**。对回溯日期分析，今天的换手率会混进历史那一天的结论，违反 §6.2「历史分析只能使用分析日当时已经公开的数据」。

个股侧已有现成机制：`LIVE_ONLY_TOOLS` + `_reject_if_not_point_in_time`（`a_stock.py:710-747`），ETF 工具只是没接进去。

### 修复方式

- `get_etf_quote` / `get_etf_structure_alerts` / `get_etf_peer_comparison` 增加 `end_date`（分析日）参数，并在 `etf_data_tools.py` 的 `@tool` 签名与 `interface.VENDOR_METHODS` 中一并透传。
- 把这三个方法加入 `LIVE_ONLY_TOOLS`。
- **ETF 模式下不受 `strict_point_in_time` 开关影响**：`trade_date < today` 时一律返回 `status="unsupported"` + 明确 notes，而不是返回今天的数字。理由：§6.2 对 ETF 是硬约束，而 `strict_point_in_time` 默认是关的，沿用开关等于默认不生效。
- `probe_etf_capabilities`（`etf_data.py:488`）据此在回溯日期移除 `liquidity_metrics`，让流动性分析师、进度阶段、报告栏目一并消失——这正是能力清单机制该处理的场景。

### 验收

- `tests/test_lookahead.py` 增加：`trade_date` 为过去某日时，三个 ETF 快照工具返回 `unsupported`，且 payload 内不含任何数值
- `probe_etf_capabilities("510300", "<过去日期>")` 的返回中包含 `liquidity_metrics`
- 当日/未来日期行为不变（回归）

---

## 7. 质量门控：F 不阻断，且禁用词存在误判

### 问题

**7.1 F 不阻断。** §12.4 规定 F 表示流程本身出错、「应阻断输出并记录」。实际单个 F 只让 `fail_count` +1，阻断条件是 `fail_count >= max(2, n//2+1)`，ETF 5 个栏目需要 3 个才拦（`quality_gate.py:199`）。一份报告真的混入个股逻辑不会被拦住。

**7.2 禁用词误判。** `ETF_FORBIDDEN_TERMS = ("公司营收", "净利润", "董监高", "解禁", "限售", "龙虎榜")`（`quality_gate.py:33`）是裸子串匹配，而注入的证据词表恰恰会告诉模型「禁止引用解禁、龙虎榜」。报告写「不适用：龙虎榜、解禁（个股专属）」就会被判 F。

### 修复方式

- 禁用词检测改为区分「使用」与「声明未使用」：在命中词前后一定窗口内出现否定/排除标记（`不适用`、`不涉及`、`未使用`、`无相关`、`已排除`、`N/A`）时不计为违规。实现放在独立函数并单独测试。
- 违规命中改为独立的阻断信号：`data_quality_failed = (fail_count >= threshold) or forbidden_term_hit`，并在 summary 中单独列出命中的词与所在报告，便于事后定位。
- `_hard_check_report` 未使用的 `analyst_type` 参数一并清理或用于错误信息。

### 验收

- ETF 报告含「本节不涉及解禁与龙虎榜数据」→ 不判 F、不阻断
- ETF 报告含「该 ETF 的解禁压力将在下月释放」→ 判 F 且 `data_quality_failed=True`
- 个股模式不受禁用词逻辑影响（回归）

---

## 8. 指数新闻缓存无界且键判定过宽

### 问题

`_INDEX_NEWS_CACHE`（`a_stock.py:43`）是模块级 dict，无容量上限、无失效；`_is_index_code` 对任何 `000` 开头的代码返回 `True`，即包含 `000001` 平安银行等全部深市主板股票。长驻的 Streamlit 进程里，个股新闻会被永久冻结在首次结果上，且内存只增不减。

### 修复方式

- 缓存键的准入条件收紧为「命中 `index_catalog` 的指数代码」，而不是 `startswith("000")`；`_is_index_code` 若还有别处使用，需一并复核语义。
- 改用有界容器（`functools.lru_cache` 或 `OrderedDict` + maxsize），并把交易日纳入键，避免跨日复用。

### 验收

- `get_news("000001", ...)` 不进缓存
- `get_news("000300", ...)` 命中缓存且第二次不发请求
- 超过容量上限后最早条目被淘汰

---

## 9. 阶段 0 文档与实现漂移

`ETF_DATA_SOURCE_VALIDATION.md` 第 16-17 行结论为：ETF 日 K 主源是新浪、**无成交额字段**，因此「不启用依赖成交额的流动性指标」。但实现新增了未经阶段 0 验证的东财 `push2his` K 线作为 ETF 主源，专门为了拿 `Amount`（`_em_kline_with_amount`，`a_stock.py:491`），且 `liquidity_metrics` 无条件进入 `ETF_PHASE_ONE_CAPABILITIES`。

阶段 0 是方案里的硬门，实现绕过它就失去了这道门的意义。修复方式二选一（推荐前者）：

- **补验证**：在 `ETF_DATA_SOURCE_VALIDATION.md` 增加一行 `push2his kline`（含字段映射 `f51..f57`、样本覆盖、限流结论、授权风险、不可得时降级行为），并把 `liquidity_metrics` 的启用条件写清楚；
- **或**回退到已验证的新浪源，并按原结论关闭依赖成交额的指标。

---

## 10. 杂项

| 位置 | 问题 | 处理 |
|---|---|---|
| `instrument.py:11` vs `:142` | `DataStatus` Literal 缺 `"derived"`，但 `derive_price_limit_pct` 就返回该值 | 把 `"derived"` 补进 Literal |
| `instrument.py:101` | `profile_as_of` 用裸 `datetime.now()`（本地时区），同结构其余字段用 UTC | 统一为 UTC 或显式记录时区 |
| `etf_liquidity_analyst.py:16` | `lookback` 计算后从未使用 | 删除，或按其他分析师的做法注入提示词 |
| `aggressive/conservative/neutral_debator.py` | `market_research_report` 等逐份报告变量在改用 `report_context` 后成为死变量 | 删除 |
| `a_stock.py:663` | `elif not is_etf_run` 应为 `else`（当前形式让 `df` 在静态分析下可能未绑定） | 改为 `else` |
| `web/pdf_export.py:670` | 个股报告标题渲染为「A股个股与ETF多Agent投研分析报告」 | 个股用「A股个股…」，ETF 用「A股ETF…」 |

---

## 11. 非本次改造引入，但会让 ETF 功能不可用（需决策）

`_build_name_code_map`（`a_stock.py:137`）遍历 `for market in (0, 1, 2)`，当前 mootdx 版本对 `market=2` 抛 `MootdxValidationException('市场代码错误, 目前只支持沪深市场')`，整个函数因此进入 except 分支抛错。实测：

```
resolve_ticker('沪深300ETF')
→ ValueError: 无法通过 mootdx 解析股票名称（通达信服务暂时不可达）…
```

结论：**所有中文名称输入当前都不可用**。这意味着阶段 -1 为纳入 ETF 而放宽的正则（`a_stock.py:148`）是不可达代码，方案 §16.2「代码输入与中文名称输入」这条必测场景在真实环境下从未成立。

该缺陷早于本次 ETF 改造，建议作为独立缺陷单独修（把 `market=2` 改为容错跳过，或按 mootdx 版本能力探测），但因为它直接决定 ETF 名称输入能否使用，需在本轮一并决策是否顺带修复。

---

## 12. 冒烟验收（批次 1、2 后执行）

真实标的最小集，逐个确认识别结果与开始按钮状态：

| 输入 | 期望模式 | 期望回显 |
|---|---|---|
| `510300` | etf | 识别为 ETF · 华泰柏瑞沪深300ETF · 上交所；跟踪沪深300指数；指数代码 CSI · 000300（目录映射） |
| `159915` | etf | 深交所；创业板指数(价格)；涨跌幅 20%（推导） |
| `588000` | etf | 上交所；上证科创板50成份指数；涨跌幅 20%（推导） |
| `600519` | stock | 识别为 股票；开始按钮可用 |
| `000016` | stock | 行情落到 `sz000016`（深康佳A），不是上证50 |
| `511990` | unsupported | 明确拒绝，开始按钮禁用 |
| `161725` | unsupported | 明确拒绝，开始按钮禁用 |
| `518880` / `513050` / `511260` | unsupported | 明确拒绝（回归） |

另需确认：完成一次 `510300` 的 ETF 分析后，侧边栏历史记录显示 `[ETF] · 沪深300指数`。
