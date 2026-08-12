# A 股技术分析可靠性改进方案

> 文档状态：待评审、待实施  
> 适用范围：本项目 A 股个股技术分析链路  
> 核心目标：数据好时生成可复现信号；数据降级时降低置信度；数据不可信时拒绝判断  
> 明确排除：不建设包含 T+1、涨跌停、停牌、手续费、印花税、滑点、冲击成本、成交失败或仓位管理的 A 股交易回测引擎

## 1. 背景与结论

当前技术分析链路已经具备以下基础能力：

- 通过 `get_stock_data` 获取 OHLCV，通过 `get_indicators` 计算技术指标；
- A 股行情以 mootdx 为主，并在部分路径中使用新浪数据补充或降级；
- 指标计算前按照分析日期截断数据，避免技术指标直接读取未来行情；
- 技术分析师能够综合均线、MACD、RSI、布林带、ATR、VWMA 和量价信息生成报告；
- 下游已有报告质量门控、结构化评级和简单的事后表现统计。

但当前链路无法回答三个关键问题：

1. 本次分析实际用了哪个数据源，是否发生过降级、拼接、缺失或口径变化？
2. 相同的冻结数据和相同配置，是否必然得到相同的技术信号？
3. 数据不足或不同来源冲突时，系统是否会停止输出方向性结论？

本方案把数据获取、指标计算、信号生成和语言解释分层。供应商不稳定是预期状态，不再假设任何免费或非官方接口具有持续 SLA。系统可靠性的定义不是“接口永不失败”，而是：

- 失败和降级可观测；
- 数据口径可追踪；
- 原始输入可冻结；
- 数值校验由程序完成；
- 方向信号由确定性规则产生；
- LLM 只解释证据，不自行创造事实；
- 关键数据不可信时 fail closed，拒绝评级。

## 2. 建设目标与非目标

### 2.1 建设目标

1. 建立统一、带来源元数据的 OHLCV 数据契约。
2. 建立通用供应商适配层，统一处理异常、空结果、错误字符串、超时和限流。
3. 建立显式降级状态机和字段级数据血缘，不允许静默 fallback。
4. 建立跨来源一致性校验、时效检查、连续性检查、单位检查和复权口径检查。
5. 将原始响应、标准化数据和质量报告按请求冻结，支持离线复现。
6. 将技术指标与技术信号确定化；同一输入和配置必须产生相同结果。
7. 让 LLM 只消费结构化证据包，输出解释性报告，不负责计算指标和决定底层信号。
8. 将数据质量与信号置信度贯穿到技术报告、质量门控和最终评级。
9. 建立点时、样本外的信号有效性评估，检验方向准确率、未来收益和相对基准收益。
10. 通过单元测试、契约测试、固定样本回归测试和故障注入测试保证降级行为。

### 2.2 非目标

- 不保证任何数据供应商永久可用。
- 不承诺技术信号产生正收益或稳定超额收益。
- 不建设交易执行系统。
- 不建设组合级回测、资金曲线、仓位管理或订单撮合。
- 不模拟 T+1、涨跌停、停牌、手续费、印花税、滑点、冲击成本或成交失败。
- 不用 LLM 猜测缺失行情、成交量、复权因子或指标数值。
- 第一阶段不覆盖分钟线、高频行情和盘口数据。

## 3. 现状缺口

### 3.1 路由层不能可靠识别供应商失败

`tradingagents/dataflows/interface.py::route_to_vendor` 当前只在 `AlphaVantageRateLimitError` 时继续 fallback。其他实现可能：

- 抛出普通异常；
- 返回 `Error ...`、`No data ...` 或“获取失败”等字符串；
- 返回格式合法但为空的数据；
- 返回最后交易日明显滞后的数据。

这些情况可能被当成成功，导致 fallback 没有发生，或者错误文本被直接交给 LLM。

### 3.2 降级发生在函数内部，缺乏统一记录

`a_stock.py` 中存在 mootdx → 新浪、东方财富 → 新浪等局部降级，但调用者通常只能拿到拼接后的文本。当前缺少：

- 尝试过的供应商列表；
- 每次失败的分类和原因；
- 主源与备用源返回区间；
- 数据是否被拼接；
- 哪些日期或字段来自哪个来源；
- 降级对数据质量等级的影响。

### 3.3 行情语义不完整

当前 OHLCV 输出没有稳定、机器可读地表达：

- 价格是否为原始价、前复权或后复权；
- 成交量和成交额单位；
- 交易所与证券类型；
- 数据时区和交易日历；
- 停牌日、缺失日和非交易日的区别；
- 数据源返回时间与数据最后日期；
- 企业行动造成的跳变是否已经处理。

这会直接影响长周期均线、MACD、ATR、布林带和区间收益。

### 3.4 技术信号依赖 LLM 自由解释

当前模型从最多 8 个指标中自行选择，并自行判断多空、背离、支撑和阻力。即使底层数值相同，不同模型或重复运行也可能给出不同结论。系统目前没有：

- 统一信号规则；
- 指标冲突处理；
- 信号强度和置信度算法；
- 明确的 abstain/拒绝判断状态；
- 对支撑阻力候选的确定性计算。

### 3.5 质量门控主要检查报告形态

现有质量门控能够发现报告过短、失败文本、数据缺失和缺少表格，但不能充分验证：

- OHLC 关系是否合法；
- 数据是否新鲜；
- 不同来源是否冲突；
- 指标是否使用足够的预热数据；
- 报告中的数值是否与底层证据一致；
- 降级后是否仍允许输出方向评级。

### 3.6 历史结果不能完全复现

缓存更偏向减少网络请求，不等同于不可变快照。供应商可能修订历史数据或改变接口结果；同一分析日期以后重新运行，可能拿到不同内容。完整历史流程中还存在只能提供实时快照的工具，而 `strict_point_in_time` 默认关闭。

### 3.7 现有绩效统计不是策略验证

当前 `performance.py` 统计的是离散决策在固定持有期后的结果，不是组合回测。该机制可以保留作为观测入口，但需要补齐数据质量分层、版本分层、点时冻结和样本外评估，才能判断技术信号是否具有区分度。

## 4. 目标架构

```text
AnalysisRequest
      |
      v
MarketDataService
  |-- VendorAdapter[mootdx]
  |-- VendorAdapter[sina]
  |-- VendorAdapter[...]
      |
      v
NormalizedBars + Provenance
      |
      v
DataValidator ------> QualityReport
      |                    |
      | pass/degrade       | block
      v                    v
SnapshotStore          UnavailableResult
      |
      v
IndicatorEngine
      |
      v
DeterministicSignalEngine
      |
      v
TechnicalEvidenceBundle
      |
      +--> LLM Report Renderer
      +--> Quality Gate
      +--> Point-in-time Evaluator
```

关键约束：

- 供应商适配层不得直接返回给 LLM 的自由文本；
- 数据服务层只返回结构化结果；
- 指标引擎不得访问网络；
- 信号引擎不得调用 LLM；
- LLM 不得接收未经验证的原始供应商文本；
- 快照是评估和复现的唯一数据入口。

## 5. 统一数据契约

建议新增 `tradingagents/dataflows/models.py`，使用 dataclass 或 Pydantic 定义以下模型。

### 5.1 请求对象 `MarketDataRequest`

```python
class MarketDataRequest(BaseModel):
    symbol: str
    exchange: Literal["SSE", "SZSE", "BSE"]
    instrument_type: Literal["stock", "etf", "index"]
    start_date: date
    end_date: date
    frequency: Literal["1d"] = "1d"
    adjustment: Literal["raw", "forward", "backward"]
    as_of: datetime
```

约束：

- `end_date <= as_of`；
- 证券识别结果必须在请求前冻结；
- `adjustment` 必填，不允许隐式默认；
- 第一阶段只支持日线。

### 5.2 标准行情 `NormalizedBar`

```python
class NormalizedBar(BaseModel):
    symbol: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    amount: Decimal | None
    adjustment: Literal["raw", "forward", "backward", "unknown"]
    source: str
    source_symbol: str
    retrieved_at: datetime
    flags: set[str]
```

建议使用 `Decimal` 保存归一化后的价格和数量，在指标计算边界统一转换为 `float64`，减少文本解析和单位换算造成的不一致。

### 5.3 来源尝试 `SourceAttempt`

```python
class SourceAttempt(BaseModel):
    source: str
    started_at: datetime
    elapsed_ms: int
    status: Literal[
        "success", "timeout", "rate_limited", "network_error",
        "schema_error", "empty", "stale", "conflict", "unsupported"
    ]
    row_count: int = 0
    first_date: date | None = None
    last_date: date | None = None
    error_code: str | None = None
    error_summary: str | None = None
```

`error_summary` 必须脱敏，不保存 API Key、完整请求头或可能包含凭据的 URL。

### 5.4 数据集结果 `MarketDataResult`

```python
class MarketDataResult(BaseModel):
    request: MarketDataRequest
    bars: list[NormalizedBar]
    attempts: list[SourceAttempt]
    quality: DataQualityReport
    snapshot_id: str | None
```

所有上层调用统一判断 `quality.decision`，不再通过搜索错误字符串判断成功或失败。

## 6. 供应商适配与显式降级

### 6.1 适配器协议

建议新增：

```text
tradingagents/dataflows/vendors/
  base.py
  mootdx_adapter.py
  sina_adapter.py
  eastmoney_adapter.py
  yfinance_adapter.py
  alpha_vantage_adapter.py
```

统一接口：

```python
class MarketDataVendor(Protocol):
    name: str
    capabilities: VendorCapabilities

    def fetch_bars(self, request: MarketDataRequest) -> VendorBarsResult:
        ...
```

适配器职责仅包括：请求、解析、字段映射和供应商特定错误分类。它不负责跨源 fallback、质量评分、拼接或生成报告。

### 6.2 失败分类

统一异常层次：

```text
VendorError
├── VendorTimeout
├── VendorRateLimited
├── VendorNetworkError
├── VendorSchemaError
├── VendorEmptyResult
├── VendorStaleResult
└── VendorUnsupportedRequest
```

兼容迁移期间，对旧函数返回文本增加 `classify_legacy_result()`：

- 空字符串、空 DataFrame、零行 CSV → `empty`；
- `Error`、`No data`、`获取失败`、`无法获取` 等已知前缀 → 转成异常；
- 无法解析为约定 schema → `schema_error`；
- 最后日期早于预期交易日 → `stale`。

迁移完成后删除错误字符串协议。

### 6.3 降级策略

降级顺序放入配置，不写死在业务函数：

```python
"market_data_policy": {
    "stock_daily": ["mootdx", "sina"],
    "etf_daily": ["eastmoney", "sina"],
    "index_daily": ["sina"],
    "max_attempts": 2,
    "per_attempt_timeout_seconds": 15,
}
```

状态定义：

| 状态 | 含义 | 默认行为 |
|---|---|---|
| `PRIMARY_OK` | 主源完整，通过校验 | 正常分析 |
| `FALLBACK_OK` | 主源失败，备用源完整 | 分析并降低来源置信度 |
| `MERGED` | 多源按日期拼接 | 分析，但必须展示拼接区间和来源 |
| `STALE` | 最新有效交易日缺失 | 仅观察或阻断，取决于滞后程度 |
| `PARTIAL` | 关键字段或日期少量缺失 | 仅允许兼容指标，降低置信度 |
| `CONFLICT` | 多源数据超出容差 | 阻断方向信号 |
| `UNAVAILABLE` | 无可用数据 | 终止技术分析 |

### 6.4 拼接规则

允许拼接，但必须满足：

1. 同一日期不能静默覆盖；
2. 重叠日期先做交叉验证；
3. 价格口径、单位和复权方式一致；
4. 每根 bar 保留来源；
5. 拼接边界写入质量报告；
6. 若重叠区间冲突超过阈值，状态变为 `CONFLICT`，不得选择“看起来更合理”的来源。

### 6.5 熔断与冷却

对连续超时、限流或 schema 错误的供应商建立进程内健康状态：

- 最近 N 次失败达到阈值后进入冷却；
- 冷却期间跳过该源并记录 `circuit_open`；
- 半开状态只允许一次探测；
- 健康状态只影响调用顺序，不改变质量规则；
- 不把永久状态只存在内存，关键事件写入结构化日志。

## 7. 数据质量验证与分级

建议新增 `tradingagents/dataflows/validation.py`。

### 7.1 单条行情硬校验

每根 bar 至少检查：

- `low <= min(open, close) <= max(open, close) <= high`；
- OHLC 均为正数且为有限值；
- `volume >= 0`、`amount >= 0`；
- 日期唯一且严格递增；
- 日期不得晚于请求 `end_date/as_of`；
- 证券代码和交易所与请求一致；
- 单位必须已知；
- 复权口径必须已知，未知时不得计算跨企业行动的长周期指标。

硬校验失败不得自动修复价格值。只能丢弃明确无效行并记录，超过阈值后阻断。

### 7.2 数据集连续性

使用 A 股交易日历而非自然日检查：

- 预期交易日覆盖率；
- 首尾日期覆盖；
- 连续缺失交易日数量；
- 重复日期；
- 零成交量连续段；
- 预热区间是否足够。

不应把停牌日直接当成供应商缺失。若没有可靠停牌日历，标记为 `calendar_ambiguous`，并降低质量，不擅自填充 OHLCV。

### 7.3 新鲜度

根据请求结束日期和最近有效交易日判断：

- 当日收盘后：应覆盖到当日；
- 盘中分析：可接受覆盖到上一交易日，并明确 `intraday_not_final`；
- 周末/节假日：以最近交易日为期望终点；
- 超过一个预期交易日未更新：`STALE`；
- 超过配置阈值：阻断方向信号。

### 7.4 跨来源一致性

备用源不仅用于失败后接管，也可按采样策略做交叉验证：

- 最新 5 个重叠交易日比较 OHLC；
- 价格采用相对误差和最小报价单位组合容差；
- 成交量/成交额先归一化单位再比较；
- 如果只有单一来源，标记 `single_source_unverified`，不等同失败；
- 超出容差时保存冲突日期和字段，状态设为 `CONFLICT`。

阈值必须进入版本化配置，禁止散落在代码中。第一版阈值通过固定样本验证后确定，不在本方案中臆定具体百分比。

### 7.5 企业行动与复权

优先目标是获得明确复权口径的数据，而不是自行猜测复权因子：

1. 数据源明确提供前复权序列时，记录供应商及参数；
2. 同时保存原始价和复权价时，将二者分为不同数据集；
3. 数据源不能说明口径时标记 `adjustment=unknown`；
4. `unknown` 数据只允许短窗口、且未检测到疑似企业行动时生成观察报告；
5. 发现单日机械跳变、成交量同步倍增等疑似企业行动时，阻断长周期趋势结论；
6. 快照中保存复权元数据和版本，避免供应商日后调整历史因子导致不可复现。

### 7.6 质量报告与评分

质量决策优先采用规则，不只使用一个总分：

```python
class DataQualityReport(BaseModel):
    grade: Literal["A", "B", "C", "D", "F"]
    decision: Literal["allow", "observe_only", "block"]
    source_status: str
    completeness_score: float
    freshness_score: float
    consistency_score: float
    semantics_score: float
    flags: list[str]
    missing_dates: list[date]
    conflicts: list[DataConflict]
    lineage_summary: str
```

建议规则：

| 等级 | 典型条件 | 技术分析行为 |
|---|---|---|
| A | 主源完整，口径明确，交叉验证通过 | 正常信号 |
| B | 备用源完整，或单源未交叉验证但其他检查通过 | 正常信号，降低置信度 |
| C | 少量缺失、轻微滞后或发生可解释拼接 | 只输出观察性信号，不进入强方向评级 |
| D | 复权未知且影响窗口、预热不足、重要字段冲突 | 阻断方向信号 |
| F | 无数据、schema 破坏或严重冲突 | 终止分析 |

硬阻断条件优先于平均分，不能让多个高分维度抵消一个严重冲突。

## 8. 不可变数据快照与可复现性

建议新增 `tradingagents/dataflows/snapshots.py`，目录默认放在现有 `data_cache_dir` 下：

```text
snapshots/
  sha256-prefix/
    manifest.json
    request.json
    attempts.json
    raw/
      mootdx.bin-or-json
      sina.json
    normalized.parquet
    quality.json
```

### 8.1 快照标识

`snapshot_id` 由以下内容的规范化序列计算 SHA-256：

- 请求对象；
- 标准化数据；
- 来源尝试记录；
- 数据契约版本；
- 归一化代码版本；
- 质量规则版本。

### 8.2 写入原则

- 原始响应只追加，不原地改写；
- 标准化数据与质量报告原子写入；
- 不完整快照使用临时目录，完成后再原子重命名；
- 快照清单包含内容哈希和文件大小；
- API Key、Cookie、认证头和带签名 URL 不得落盘；
- 无法合法保存的供应商原始响应，只保存脱敏摘要、哈希和解析后的标准化数据。

### 8.3 在线与离线模式

增加三种运行模式：

```text
online       优先网络，可写新快照
prefer_cache 命中完全一致请求时复用快照，否则访问网络
offline      只读指定 snapshot_id，缺失即失败
```

固定样本测试、历史复现和信号评估必须使用 `offline`。

### 8.4 保留策略

- 被分析报告、评估记录或缺陷工单引用的快照永久保留，除非用户明确删除；
- 未引用的临时快照按容量或期限清理；
- 清理只删除索引确认未被引用的快照；
- 快照索引损坏时 fail closed，不批量删除未知文件。

## 9. 确定性指标引擎

建议新增 `tradingagents/technical/indicators.py`。

### 9.1 输入输出

输入只能是通过质量门控的 `NormalizedBars` 和版本化 `IndicatorConfig`。输出为结构化时间序列及元数据：

```python
class IndicatorValue(BaseModel):
    name: str
    value: float | None
    trade_date: date
    parameters: dict[str, int | float | str]
    warmup_complete: bool
    engine_version: str
```

### 9.2 第一版指标集

保留现有指标，但固定参数并显式记录：

- `SMA(20/50/200)`；
- `EMA(10)`；
- `MACD(12, 26, 9)`；
- `RSI(14)`；
- `BOLL(20, 2)`；
- `ATR(14)`；
- `VWMA(20)`；
- `MFI(14)`，仅在成交量可靠时启用；
- 5 日与 20 日平均成交量；
- 20 日和 60 日滚动高低点。

现有 `stockstats` 可以继续作为第一版计算后端，但要封装在引擎后面，并用固定输入输出回归样本锁定结果。后续更换库时，新旧引擎必须做数值差异报告。

### 9.3 预热数据

“展示窗口”和“计算窗口”必须分开：

- 用户选择 30 日分析窗口，不代表只下载 30 日数据；
- 计算 200 日 SMA 至少需要 200 个有效交易日，并增加配置化缓冲；
- 预热不足的指标输出 `warmup_complete=false`，不得作为方向证据；
- 报告展示仍只截取用户选择的分析窗口。

### 9.4 数值验证

- 使用人工构造的小序列验证均线、ATR 和量能计算；
- 使用冻结真实样本与第二实现交叉验证；
- 明确 NaN、无穷值和首期初始化规则；
- 对 MACD、RSI、布林带记录所用库版本和默认参数，避免依赖升级静默改变结果。

## 10. 确定性技术信号引擎

建议新增 `tradingagents/technical/signals.py`。第一版不追求复杂策略，而是把当前报告中的常见判断变成可测试证据。

### 10.1 单项信号

每个信号统一输出：

```python
class TechnicalSignal(BaseModel):
    signal_id: str
    category: Literal["trend", "momentum", "volatility", "volume", "level"]
    direction: Literal["bullish", "bearish", "neutral", "unavailable"]
    strength: float       # 0..1
    confidence: float     # 0..1，受数据质量和预热影响
    observed_at: date
    inputs: dict[str, float | str]
    rule_version: str
    explanation_key: str
```

第一版规则建议包括：

- 收盘价相对 SMA20/SMA50/SMA200 的位置；
- SMA20 与 SMA50 的排列和交叉；
- EMA10 的斜率与价格位置；
- MACD 主线/信号线交叉、零轴位置、柱体连续扩大或收缩；
- RSI 所处区间与最近变化方向；
- 收盘价在布林带中的标准化位置；
- ATR/收盘价和自身历史分位；
- 5 日均量相对 20 日均量；
- 价格突破 20/60 日高点或跌破低点；
- 可重复计算的支撑阻力候选：滚动高低点、近期摆动点和均线，不允许 LLM凭空给价位。

背离识别容易受峰谷算法影响，第一阶段可以暂不自动评级；若实现，必须固定峰谷参数、最小间隔和显著性阈值，并单独版本化。

### 10.2 综合信号

综合信号不是简单多数投票。建议：

1. 先按类别聚合，避免 MACD 三条线被当成三个独立票；
2. 趋势、动量、量价、波动和关键位各形成一个类别结果；
3. 类别冲突时输出 `mixed`，不得强制归一到多或空；
4. 数据质量等级调整置信度，不修改原始方向；
5. C 级数据最多输出 `observe_only`；D/F 级输出 `unavailable`；
6. 所有权重和阈值进入 `signal_rules_v1.yaml`，并保留版本号。

建议输出：

```python
class TechnicalAssessment(BaseModel):
    stance: Literal["bullish", "bearish", "neutral", "mixed", "unavailable"]
    score: float          # -1..1，仅表示规则汇总方向
    confidence: float     # 0..1
    decision: Literal["allow", "observe_only", "block"]
    supporting_signal_ids: list[str]
    conflicting_signal_ids: list[str]
    data_quality_grade: str
    snapshot_id: str
    indicator_config_version: str
    signal_rule_version: str
```

`score` 不是预期收益，也不能直接映射成仓位。

## 11. LLM 角色收缩与报告改造

### 11.1 新职责

技术分析师不再自行调用多个指标工具、手工计算涨跌幅或自由选择最终底层信号。其输入改为 `TechnicalEvidenceBundle`：

- 标的信息和分析区间；
- 数据质量等级、来源和降级路径；
- 最新行情及程序计算的区间统计；
- 已验证指标当前值；
- 确定性单项信号；
- 综合信号和冲突项；
- 支撑阻力候选及计算依据；
- 明确的缺失项和禁止使用项。

LLM 只负责：

- 用自然语言解释证据；
- 指出信号一致与冲突之处；
- 说明数据降级的影响；
- 按固定模板生成研究报告。

### 11.2 防幻觉约束

- 报告中出现的每个价格、指标值、日期必须可追溯到 evidence ID；
- 不允许新增证据包以外的具体数值；
- `decision=block` 时只能说明不可判断，不得输出多空结论；
- `observe_only` 时不得使用“买入、卖出、强烈看多、强烈看空”等执行性措辞；
- 报告尾部机器可读地列出 `snapshot_id`、质量等级和规则版本。

### 11.3 程序化事实核验

报告生成后增加轻量核验器：

- 提取报告中的日期、价格和百分比；
- 与 evidence bundle 中允许引用的数值比对；
- 检查多空描述是否与结构化信号相反；
- 检查是否遗漏降级和阻断提示；
- 核验失败时允许一次受约束重写，第二次仍失败则返回结构化模板报告，不继续自由生成。

## 12. 质量门控与下游评级联动

### 12.1 数据门控前移

质量门控分为两层：

1. **数据门控**：在指标和 LLM 之前执行，决定 `allow / observe_only / block`；
2. **报告门控**：检查报告完整性、证据一致性和禁用措辞。

现有 `quality_gate.py` 保留为报告层入口，但新增结构化字段：

```text
market_data_quality
market_data_decision
market_snapshot_id
technical_assessment
technical_evidence_bundle
```

### 12.2 下游使用规则

- `allow`：技术报告可进入多空辩论；
- `observe_only`：报告可以进入上下文，但研究员必须将其标为低置信证据，不能单独驱动强评级；
- `block`：技术报告替换为“不可用原因”，不把技术方向传给下游；
- 最终组合经理若关键分析全部被阻断，应输出数据不足，而不是默认 Hold；
- 数据不足和中性判断必须区分：前者是 `unavailable`，后者是有证据的 `neutral`。

### 12.3 UI/CLI 展示

报告头部至少显示：

```text
数据质量：B / FALLBACK_OK
实际来源：sina
主源状态：mootdx timeout
复权口径：forward
数据区间：2025-01-02 → 2026-08-12
快照：sha256:...
信号规则：technical-v1
```

C/D/F 或发生冲突时使用明显警告，不把信息藏在报告末尾。

## 13. 点时信号有效性评估（非交易回测）

本阶段只回答“技术信号与未来价格变化是否有统计关联”，不回答“按 A 股实际交易规则能赚多少钱”。

### 13.1 评估样本

每条样本保存：

```text
symbol
signal_date
snapshot_id
data_quality_grade
technical_stance
technical_score
confidence
rule_version
forward_return_5d / 20d / 60d
benchmark_return_5d / 20d / 60d
forward_alpha_5d / 20d / 60d
```

未来收益只用于事后打标签，不得进入当时的快照、指标和信号生成过程。

### 13.2 Walk-forward 纪律

- 每个信号只读取 `signal_date` 当时可用的冻结快照；
- 参数调整只使用训练期；
- 时间顺序划分训练、验证、测试区间；
- 测试区间一次性评估，不根据结果反复调参；
- 不允许随机打散时间序列；
- 规则版本改变后新建评估批次，不能覆盖旧结果；
- 同一股票高频重复信号要单独报告样本重叠，避免把相关样本当独立观测。

### 13.3 评价指标

至少报告：

- 有方向信号覆盖率；
- bullish/bearish/neutral/mixed 分布；
- 方向准确率；
- 各方向的平均、中位未来收益；
- 相对沪深 300 或适当基准的未来 alpha；
- 不同持有观察窗口的结果；
- 按 A/B/C 数据质量分层结果；
- 主源与备用源分层结果；
- 按规则版本、年份、市场状态和板块分层结果；
- 置信度分桶后的单调性；
- bootstrap 置信区间和样本量提示。

不计算或不宣称：

- 组合净值；
- 年化收益；
- 夏普比率；
- 最大回撤；
- 可成交收益；
- 扣费后收益；
- 策略容量。

这些指标需要组合构建和执行假设，超出本方案范围。

### 13.4 防止结论污染

- A、B、C 级数据分别报告，不只给合并数字；
- 降级前后同日期数据同时可用时，比较信号是否翻转；
- 供应商变更和规则版本升级前后分段展示；
- 样本不足时明确标为探索性结果；
- 不以一次样本外成功作为未来有效性的保证。

## 14. 配置与版本管理

建议新增：

```text
config/
  market_data_policy.yaml
  data_quality_rules_v1.yaml
  indicator_config_v1.yaml
  signal_rules_v1.yaml
```

每份分析报告保存以下版本：

- `data_contract_version`；
- `normalizer_version`；
- `quality_rule_version`；
- `indicator_engine_version`；
- `indicator_config_version`；
- `signal_rule_version`；
- `prompt_version`；
- `model_provider/model_name`。

配置变更必须产生新版本，不允许只修改同名文件后覆盖历史语义。

## 15. 可观测性与运维

### 15.1 结构化日志

每次数据请求记录：

- request ID、symbol、日期范围；
- 供应商尝试顺序；
- 耗时、结果分类、行数和最后日期；
- 是否降级、拼接或冲突；
- 质量等级和阻断原因；
- snapshot ID。

不得记录 API Key、认证头或完整敏感响应。

### 15.2 指标

建议聚合：

- 各供应商成功率、超时率、空结果率和 schema 错误率；
- fallback 比例；
- stale/partial/conflict 比例；
- 每种质量等级占比；
- 平均和 P95 请求耗时；
- 因数据问题阻断的分析比例；
- LLM 报告事实核验失败率。

### 15.3 告警

- 某主源连续失败超过阈值；
- fallback 比例显著上升；
- schema 错误首次出现；
- 同一标的跨来源价格冲突；
- 最新交易日覆盖率异常下降；
- A/B 级数据比例快速下降。

第一阶段可以只输出本地 JSONL 日志和 CLI 汇总，不要求部署外部监控平台。

## 16. 测试方案

### 16.1 单元测试

- 所有适配器的正常、空数据、超时、限流、schema 变化和错误文本分类；
- OHLC、日期、单位、时效、重复和缺口校验；
- 降级状态机及熔断状态迁移；
- 拼接边界和冲突处理；
- 复权未知时的阻断规则；
- 指标预热和固定参数；
- 单项信号、类别聚合、冲突和 abstain；
- 质量等级对信号决策的影响；
- 报告数值与证据包的一致性核验。

### 16.2 契约测试

为每个供应商保存脱敏响应 fixture，验证：

- 当前解析器仍能解析已知 schema；
- 字段单位和日期语义不漂移；
- 上游新增字段不影响结果；
- 上游删改关键字段时明确失败，而不是返回部分错误数据。

在线 smoke test 与默认 CI 分离，避免网络不稳定导致单元测试随机失败。

### 16.3 黄金样本回归

选择覆盖以下情况的固定标的和日期：

- 沪市、深市、创业板、科创板、北交所；
- 正常交易、长期停牌附近、除权除息附近；
- 主源完整、备用源完整、拼接、缺失、冲突；
- 200 日指标预热充分与不足。

每个样本冻结：标准化数据、质量报告、指标输出、技术信号和结构化证据包。LLM 文案不做全文快照，只校验结构、引用事实和禁止项。

### 16.4 故障注入

必须覆盖：

- 主源超时，备用源成功；
- 主源返回 HTTP 200 但正文为空；
- 主源返回错误字符串；
- 备用源字段改名；
- 两源同日收盘价冲突；
- 缓存损坏；
- 快照写到一半进程中断；
- 数据只到前两个交易日；
- 复权口径未知；
- 指标库升级产生数值漂移。

### 16.5 当前已知测试债务

实施前先修复或明确：

- `get_index_data` 尚未加入 `POINT_IN_TIME_TOOLS`/`LIVE_ONLY_TOOLS` 分类，当前相关测试失败；
- pytest 临时目录和缓存目录在部分 Windows 环境存在权限问题，应由测试配置指定工作区内可写路径；
- 在线数据测试必须标记为 integration，不纳入离线可靠性结论。

## 17. 分阶段实施计划

### 阶段 0：基线冻结与安全网

目标：改架构前先固定现有行为和真实样本。

工作项：

1. 修复 `get_index_data` 点时分类测试；
2. 处理 Windows pytest 临时目录配置；
3. 为 mootdx、新浪、东方财富保存脱敏 fixtures；
4. 记录当前主源、备用源、字段和已知错误形式；
5. 选择黄金样本并保存当前指标结果；
6. 为 `route_to_vendor` 的普通异常、错误字符串和空结果补回归测试。

验收：

- 离线相关测试全绿；
- 在线测试与默认 CI 隔离；
- 至少覆盖主源成功、主源失败备用源成功、全部失败三条路径；
- 当前行为和已知缺陷有书面基线。

### 阶段 1：结构化数据契约与适配器

目标：消除“字符串既是数据又是错误”的接口。

工作项：

1. 实现请求、bar、attempt、result、quality 模型；
2. 封装 mootdx 和新浪适配器；
3. 引入统一异常分类；
4. 建立 `MarketDataService` 和配置化供应商顺序；
5. 保留旧工具函数作为兼容 facade，将结构化结果渲染成旧文本；
6. 在报告中显示实际来源和降级路径。

验收：

- 上层不再依赖错误字符串判断状态；
- 每次请求都有完整 attempts；
- 主源普通异常、空结果、错误正文均能触发备用源；
- 旧 CLI/Web 主流程仍可运行。

### 阶段 2：质量验证与显式降级

目标：决定哪些数据可用、哪些只能观察、哪些必须阻断。

工作项：

1. 实现硬校验、连续性、新鲜度和单位检查；
2. 引入交易日历；
3. 实现跨源抽样验证和冲突报告；
4. 明确复权口径和企业行动风险；
5. 实现 A-F 等级及 `allow/observe_only/block`；
6. 将质量决策接入技术分析入口。

验收：

- 构造的非法 OHLC、未来日期、严重滞后和冲突数据全部被阻断；
- fallback 不再静默；
- B/C 级输出含清晰降级原因；
- D/F 级无法产生方向信号。

### 阶段 3：不可变快照

目标：相同快照可离线复现标准化数据和质量结论。

工作项：

1. 实现 manifest、哈希、原子写入和索引；
2. 支持 online/prefer_cache/offline；
3. 把数据契约和规则版本写入快照；
4. 建立引用关系和安全保留策略；
5. 为缓存损坏和中断写入增加恢复测试。

验收：

- 指定 snapshot ID 可在断网状态读取；
- 相同快照重复加载内容哈希一致；
- 供应商后来变更不会改变旧快照结果；
- 不完整写入不会被识别为有效快照。

### 阶段 4：确定性指标与信号

目标：相同数据、相同规则版本得到相同技术判断。

工作项：

1. 封装指标引擎并固定参数；
2. 分离计算窗口和展示窗口；
3. 实现预热检查；
4. 实现第一版单项信号与类别聚合；
5. 实现 `neutral/mixed/unavailable`；
6. 建立黄金样本数值回归。

验收：

- 重复运行结果逐字段一致；
- 不同 LLM 不影响底层技术信号；
- 指标预热不足不会产生伪信号；
- 类别冲突时不会强制输出多或空；
- 每个结论均能追溯到输入值和规则版本。

### 阶段 5：LLM 与质量门控改造

目标：模型只解释经验证的结构化证据。

工作项：

1. 生成 `TechnicalEvidenceBundle`；
2. 重写 market analyst 提示词和工具权限；
3. 实现报告事实核验器；
4. 将数据决策传入现有 quality gate、研究员和组合经理；
5. 更新 Web/CLI 报告头部和历史记录元数据。

验收：

- 报告中的数字均可追溯；
- block 时模型不能输出方向结论；
- observe_only 时报告不使用执行性措辞；
- 模型失败时能用结构化模板提供可读报告；
- 最终评级能区分“中性”和“数据不足”。

### 阶段 6：点时信号评估

目标：评估技术信号的统计区分度，不模拟交易执行。

工作项：

1. 建立冻结快照驱动的 walk-forward 样本生成；
2. 计算 5/20/60 日未来收益和相对基准 alpha；
3. 按质量、来源、规则版本和置信度分层；
4. 输出置信区间、样本量和重叠样本提示；
5. 将结果与现有 `performance.py` 分开展示，避免被误解为策略业绩。

验收：

- 未来收益标签与信号生成严格隔离；
- 测试区间不参与调参；
- 报告明确声明“非交易回测、非策略收益”；
- 不输出夏普、最大回撤、组合净值或扣费收益；
- 能回答不同质量等级下信号是否保持方向区分度。

## 18. 推荐文件改动清单

新增：

```text
tradingagents/dataflows/models.py
tradingagents/dataflows/validation.py
tradingagents/dataflows/snapshots.py
tradingagents/dataflows/market_data_service.py
tradingagents/dataflows/vendors/base.py
tradingagents/dataflows/vendors/mootdx_adapter.py
tradingagents/dataflows/vendors/sina_adapter.py
tradingagents/dataflows/vendors/eastmoney_adapter.py
tradingagents/technical/__init__.py
tradingagents/technical/indicators.py
tradingagents/technical/signals.py
tradingagents/technical/evidence.py
tradingagents/technical/report_validation.py
tradingagents/evaluation/technical_signal_evaluator.py
config/market_data_policy.yaml
config/data_quality_rules_v1.yaml
config/indicator_config_v1.yaml
config/signal_rules_v1.yaml
tests/fixtures/market_data/...
```

重点修改：

```text
tradingagents/dataflows/interface.py
tradingagents/dataflows/a_stock.py
tradingagents/dataflows/config.py
tradingagents/default_config.py
tradingagents/agents/analysts/market_analyst.py
tradingagents/agents/quality_gate.py
tradingagents/agents/utils/agent_states.py
tradingagents/agents/utils/agent_utils.py
tradingagents/graph/trading_graph.py
tradingagents/performance.py
web/components/report_viewer.py
cli/stats_handler.py
```

迁移时不建议一次删除旧接口。先增加结构化服务，再让旧 LangChain tool 充当 facade；等所有调用方切换并通过回归后再移除文本协议。

## 19. 风险与决策点

### 19.1 数据许可和原始响应保存

不同供应商对缓存、再分发和长期保存可能有不同约束。实施快照前需要确认使用许可；不允许保存原文时，只保存脱敏摘要、哈希和允许保存的标准化数据。

### 19.2 复权数据的稳定来源

这是长周期技术分析的关键前置项。如果现有来源无法稳定提供并说明复权口径，应降低范围：

- 暂停 200 日均线等长周期结论；或
- 引入一个明确提供复权数据及企业行动信息的新来源。

不得用模型猜测或从单次跳变反推后直接覆盖历史价格。

### 19.3 交易日历和停牌语义

交易日历只能判断市场是否开市，不能单独判断某只股票是否停牌。若没有可靠停牌数据，缺失日只能标为歧义，不能填充为零成交或沿用前收盘价。

### 19.4 多数据源不等于真值

两个免费源一致只能提高信心，不能证明绝对正确。质量等级必须表达“已完成哪些校验”，不能包装成交易所级准确性承诺。

### 19.5 规则过拟合

确定性并不自动意味着有效。规则保持简单、版本化，并通过时间顺序的样本外评估检验。任何根据测试区间修改规则的行为都必须产生新的评估批次。

## 20. 最终验收标准

全部阶段完成后，系统至少满足以下标准：

1. 任一次技术分析都能回答实际来源、降级路径、数据日期、复权口径和快照 ID。
2. 普通异常、错误字符串、空结果、滞后数据和 schema 漂移均不会被当成成功。
3. 同一快照和同一规则版本重复运行，指标和技术信号完全一致。
4. 供应商降级或多源拼接在 UI、CLI、报告和日志中均明确可见。
5. 跨源冲突、关键字段缺失、复权风险或预热不足时，系统能拒绝方向判断。
6. LLM 无权修改程序生成的指标、信号方向、质量等级和来源事实。
7. 报告中的具体数值可以追溯到 evidence ID 和 snapshot ID。
8. 历史评估只使用当时冻结的点时数据，未来收益只作为事后标签。
9. 评估结果按数据质量和实际来源分层，明确样本量及不确定性。
10. 文档和界面明确说明评估不是含 A 股交易限制的回测，也不是可成交策略业绩。

## 21. 建议优先级

如果资源有限，优先顺序为：

1. **P0：结构化失败与显式降级**——先阻止错误文本和空数据被当成成功。
2. **P0：数据硬校验与阻断**——先保证“不可信时不判断”。
3. **P1：不可变快照**——保证问题可复现、评估输入不漂移。
4. **P1：确定性指标与信号**——减少模型随机性，形成可验证对象。
5. **P1：LLM 解释层与事实核验**——让报告忠于结构化证据。
6. **P2：点时信号评估**——最后检验信号是否具有统计区分度。
7. **P2：熔断、监控和运维体验**——在主链稳定后完善长期运行能力。

不建议跳过前四项直接做有效性评估，否则评估结果会混入供应商漂移、静默降级、复权不明和模型随机性，得到形式精确但无法解释的数字。
