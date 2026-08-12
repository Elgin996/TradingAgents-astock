# A 股普通股票、股票 ETF 与跟踪指数技术分析下一步方案

> 文档状态：待评审、待实施  
> 依赖方案：`ASTOCK_TECHNICAL_ANALYSIS_IMPROVEMENT_PLAN.md`  
> 目标版本：`technical-analysis-v2`  
> 核心定位：在统一、可降级、可复现的数据底座上，为普通 A 股和境内股票 ETF 建立产品语义正确的确定性技术分析；ETF 分析同时纳入其跟踪指数或合适基准  
> 明确排除：不建设包含 T+1、涨跌停、停牌、费用、滑点、成交失败或仓位管理的交易回测

## 1. 需求解释与范围

“中国 A 股普通股票 ETF 和指数 ETF”存在概念重叠。为避免实现阶段产生不同理解，本文将范围冻结为三类对象：

1. **普通 A 股股票**：上交所、深交所和北交所上市的普通人民币股票；
2. **境内股票 ETF**：在沪深交易所上市、主要投资境内股票的 ETF，包括：
   - 被动指数型股票 ETF；
   - 主动管理型股票 ETF；
3. **ETF 的参考指数**：
   - 被动指数型 ETF 的正式跟踪指数；
   - 主动股票 ETF 在基金资料中披露的业绩比较基准，若无法结构化取得则不强行补齐。

本文中的“指数分析”主要服务于 ETF 技术分析。指数不是可直接交易证券，因此：

- 可以输出指数趋势、动量、波动和关键位置；
- 可以作为 ETF 的驱动因素和比较序列；
- 不单独输出 Buy / Sell 等可执行投资评级；
- 指数成交量不可靠或语义不明时，不计算量价信号；
- 价格指数不能被描述为全收益指数，也不能替代 NAV、IOPV 或基金实际净值。

### 1.1 第一版纳入

- 主板、创业板、科创板、北交所普通 A 股；
- 境内宽基、规模、行业、主题、风格、红利、策略类股票指数 ETF；
- 可确认身份和参考指数的主动股票 ETF；
- 中证、上证、深证、国证等具有可验证代码的境内股票指数；
- 日线级技术分析；
- 标的自身技术信号；
- ETF 与跟踪指数/比较基准的同步趋势、相对强弱和偏离观察；
- 非交易型、点时信号有效性评估。

### 1.2 第一版排除

- 港股、美股和其他跨境 ETF；
- 债券、货币、商品、黄金、REIT、期货和多资产 ETF；
- 杠杆、反向和增强杠杆产品；
- LOF、场外联接基金和非上市基金；
- 分钟线、盘口和高频信号；
- 指数成分权重实时归因；
- 实时基金持仓推断；
- NAV/IOPV 折溢价分析，除非后续数据源验证单独开放该能力；
- 正式跟踪误差和跟踪差异结论，除非取得口径一致、许可清晰的 ETF 净值与全收益指数序列；
- 交易回测和成交模拟。

## 2. 与上一阶段的关系

上一份方案解决“底层数据和信号是否可信、可复现”的问题；本方案解决“不同证券类型应该如何正确分析”的问题。

当前工作区已经出现以下可靠性基础组件：

- `MarketDataRequest / NormalizedBar / DataQualityReport`；
- `MarketDataService`、供应商适配器和显式 fallback；
- 内容寻址快照；
- 确定性指标与信号引擎；
- 技术证据包和报告事实核验；
- 点时信号评估器；
- `InstrumentProfile`、ETF 能力清单和指数目录。

本方案不重建这些组件，而是在其上增加：

1. 面向多证券类型的标的关系模型；
2. subject / tracking index / benchmark 多序列数据包；
3. ETF 与指数的日期、口径和质量对齐；
4. 跨序列确定性指标和相对信号；
5. 股票、被动 ETF、主动 ETF 三套评估组合规则；
6. 产品类型感知的报告、下游辩论和质量门控；
7. 分产品、分数据质量的非交易型有效性评估。

若上一阶段组件尚未完成验收，本方案对应功能不得绕过其质量门控直接上线。

## 3. 产品语义原则

### 3.1 普通股票

普通股票的技术分析对象是公司股票本身。主要证据包括：

- 自身价格趋势；
- 动量、波动、量价关系；
- 相对宽基或行业基准的强弱；
- 技术位置和信号冲突。

公司基本面、新闻、游资、解禁等仍可由其他分析师提供，但不能混入“确定性技术信号”计算。

### 3.2 被动指数型股票 ETF

ETF 价格和跟踪指数承担不同角色：

- **跟踪指数**代表底层市场暴露的技术趋势；
- **ETF 市场价格**代表交易载体自身的价格表现；
- **ETF 成交量/成交额**代表交易载体的流动性与参与度；
- 二者的短期收益差只能称为“市场价格相对偏离”或“价格路径差异”；
- 没有 NAV 和全收益指数时，不得称为跟踪误差、跟踪差异或真实折溢价。

ETF 的方向判断应优先回答：

1. 跟踪指数的技术趋势是什么？
2. ETF 市场价格是否确认该趋势？
3. ETF 自身流动性和量价是否支持结论？
4. ETF 与指数出现分歧时，分歧来自数据、时间点还是交易载体自身？

### 3.3 主动股票 ETF

主动 ETF 没有机械跟踪关系，因此：

- ETF 自身价格是主分析序列；
- 正式业绩比较基准仅用于相对强弱背景；
- 不使用“跟踪一致性”“跟踪偏离”等措辞；
- 若比较基准无法确认，仍可做 ETF 自身技术分析，但质量报告必须注明“无可靠参考基准”；
- 不从基金名称猜测基准。

### 3.4 指数

指数只计算可由指数 OHLC 可靠支持的信号：

- 趋势：SMA、EMA、滚动高低点；
- 动量：MACD、RSI；
- 波动：布林带、ATR 或收益波动；
- 关键位置：突破、跌破、区间位置。

以下信号默认禁用：

- 指数成交量放大/缩量，除非数据契约明确其统计口径；
- VWMA、MFI 等依赖可靠成交量的指标；
- ETF 份额、成交额和流动性信号；
- 直接交易评级。

## 4. 目标分析模型

### 4.1 双层模型

技术分析分为“单序列”和“关系”两层：

```text
单序列层
├── 股票自身技术分析
├── ETF 自身技术分析
└── 指数自身技术分析

关系层
├── 股票 vs 宽基/行业基准（可选）
├── 被动 ETF vs 正式跟踪指数（优先）
└── 主动 ETF vs 正式比较基准（可选）
```

单序列层失败时，关系层不得继续。关系层失败时，可以按产品规则降级为单序列分析，但必须显式降低质量等级。

### 4.2 角色定义

建议新增：

```python
SeriesRole = Literal[
    "subject",          # 用户输入的股票或 ETF
    "tracking_index",   # 被动 ETF 的正式跟踪指数
    "benchmark",        # 股票或主动 ETF 的比较基准
]
```

同一个代码在不同请求中的角色可以不同，但一个分析请求内角色必须唯一。

### 4.3 分析类型

```python
AnalysisProduct = Literal[
    "a_share_stock",
    "passive_equity_etf",
    "active_equity_etf",
]
```

不要继续只用 `analysis_mode = stock/etf` 承担全部语义。为兼容现有流程，可以保留 `analysis_mode`，同时新增更细粒度的 `analysis_product`。

## 5. 标的信息与关系模型

### 5.1 扩展 `InstrumentProfile`

现有 `InstrumentProfile.security_type` 只有 `stock/etf`。建议保留并增加：

```python
class InstrumentProfile:
    instrument_id: str
    symbol: str
    exchange: str
    security_type: Literal["stock", "etf", "index"]
    analysis_product: str
    name: str | None
    currency: str
    timezone: str
    listed_date: DataPoint | None
    adjustment_policy: str

    # ETF fields
    etf_management_style: Literal["passive", "active"] | None
    etf_asset_type: str | None
    fund_manager: DataPoint | None

    # Reference relationship
    reference_instrument: ReferenceInstrument | None
```

### 5.2 `ReferenceInstrument`

```python
class ReferenceInstrument:
    role: Literal["tracking_index", "benchmark"]
    code: str
    name: str
    provider: str
    series_variant: Literal["price", "total_return", "net_total_return", "unknown"]
    source: str
    status: Literal["verified", "user_supplied", "ambiguous", "missing"]
    verified_at: str
```

硬规则：

- 被动 ETF 必须有 `tracking_index` 关系；
- 主动 ETF 可以有 `benchmark`，但不得标为 `tracking_index`；
- 用户补充代码时保留 `user_supplied`，不能冒充主数据；
- 指数代码相同但供应商或序列类型不同，不能视为同一个 instrument ID；
- 指数名称模糊匹配只能生成候选，不能自动冻结低置信结果。

### 5.3 身份解析顺序

```text
证券代码
→ 交易所证券主数据确认股票/基金
→ ETF 基金资料确认资产类型和管理方式
→ 解析正式跟踪指数或比较基准名称
→ provider-qualified 指数目录精确匹配
→ 低置信匹配时要求用户确认
→ 冻结 InstrumentProfile
```

身份不明时 fail closed。不得根据代码前缀或名称包含“ETF”直接决定产品类型。

## 6. 指数主数据改造

现有 `index_catalog.py` 是小型名称到六位代码映射，足以支持少量常见指数，但不适合作为完整关系主数据。

### 6.1 新目录结构

建议将目录外置为版本化数据文件：

```text
config/index_catalog_v2.yaml
```

每条记录至少包括：

```yaml
- instrument_id: CSI:000300:price
  code: "000300"
  name: 沪深300指数
  aliases: [沪深300, 沪深300价格指数]
  provider: CSI
  exchange_route: sh
  series_variant: price
  currency: CNY
  timezone: Asia/Shanghai
  source: curated
  source_as_of: 2026-08-12
```

### 6.2 匹配策略

匹配优先级：

1. ETF 主数据直接给出 provider + code；
2. provider + 精确规范化名称；
3. 精确别名；
4. 用户选择候选；
5. 无法确认则 `missing`。

禁止仅使用“名称中包含某个目录 key”自动冻结，因为主题指数名称很容易产生包含关系误匹配。

### 6.3 目录验证

每次更新目录应运行：

- instrument ID 唯一；
- provider + code + variant 唯一；
- alias 无跨指数冲突；
- 交易所路由可取样本行情；
- 数据源返回的指数名称与目录相容；
- price / total return variant 不混淆；
- 旧快照引用的目录版本仍可读取。

## 7. 多序列行情数据包

### 7.1 `AnalysisMarketDataBundle`

```python
class AnalysisMarketDataBundle(BaseModel):
    subject: MarketDataResult
    reference: MarketDataResult | None
    alignment: SeriesAlignmentReport | None
    bundle_snapshot_id: str
    overall_decision: Literal["allow", "observe_only", "block"]
    flags: list[str]
```

subject 和 reference 分别拥有：

- 独立请求；
- 独立实际来源和降级路径；
- 独立质量报告；
- 独立 snapshot ID；
- 独立复权/序列口径。

不得用 ETF 行情源的成功掩盖指数源失败，反之亦然。

### 7.2 组合快照

`bundle_snapshot_id` 的哈希输入包括：

- 冻结 InstrumentProfile；
- subject snapshot ID；
- reference snapshot ID；
- 对齐规则版本；
- 指数目录版本；
- 产品分析规则版本。

因此同一 ETF 后续更正跟踪指数映射时，不会悄悄改变旧报告语义。

### 7.3 数据窗口

每条序列使用相同的目标展示区间，但计算预热可以不同：

- subject：按其启用指标所需最长预热获取；
- reference：按指数启用指标所需最长预热获取；
- 关系指标：至少需要配置的共同有效观察数；
- 对齐只使用两边共同交易日；
- 不采用前向填充或后向填充制造共同日期；
- ETF 停牌或缺失时保留缺口，不拿指数收益替代 ETF 收益。

## 8. 序列对齐与关系质量

### 8.1 `SeriesAlignmentReport`

```python
class SeriesAlignmentReport(BaseModel):
    start_date: date | None
    end_date: date | None
    subject_observations: int
    reference_observations: int
    common_observations: int
    common_coverage: float
    subject_only_dates: list[date]
    reference_only_dates: list[date]
    subject_series_variant: str
    reference_series_variant: str
    decision: Literal["allow", "observe_only", "block"]
    flags: list[str]
```

### 8.2 对齐硬检查

- 两条序列日期均不晚于分析日；
- 共同观察数满足对应关系指标的最小窗口；
- 两者都是人民币日线且使用相同收盘时点语义；
- ETF 价格复权方式明确；
- 指数 `series_variant` 明确；
- 日期交集覆盖率达到配置阈值；
- 不存在大段单边缺失；
- 不把非交易日补值当真实观察。

### 8.3 质量决策矩阵

| subject | reference | 对齐 | 被动 ETF 行为 |
|---|---|---|---|
| A/B | A/B | allow | 完整双序列分析 |
| A/B | C | observe_only | ETF 自身信号正常；指数与关系信号仅观察 |
| A/B | D/F/缺失 | block | 降级为 ETF 自身技术报告，整体最多 C，不输出跟踪一致性结论 |
| C | A/B | observe_only | 整体仅观察；不能用指数方向替代 ETF 数据 |
| D/F | 任意 | block | 终止 ETF 技术方向判断 |

主动 ETF 的参考基准缺失不自动把 subject 降为 C；只关闭相对基准能力，并明确缺失。

普通股票的可选基准缺失也不阻断自身技术分析。

## 9. 单序列指标配置

### 9.1 股票配置

沿用确定性指标 v1：

- SMA20/50/200；
- EMA10；
- MACD(12,26,9)；
- RSI14；
- BOLL(20,2)；
- ATR14；
- VWMA20、MFI14；
- 5/20 日均量；
- 20/60 日滚动高低点。

量价指标只有在 volume 单位和连续性检查通过时启用。

### 9.2 ETF 配置

价格类指标与股票一致，但量价部分增加 ETF 语义：

- 5/20 日平均成交量；
- 5/20 日平均成交额，Amount 可用时优先；
- 成交额自身历史分位；
- 零成交和成交连续性；
- 量价确认仅描述二级市场活跃度，不解释为基金申购赎回；
- 份额变化属于结构/资金流证据，不混入技术指标引擎。

### 9.3 指数配置

启用：

- SMA20/50/200；
- EMA10；
- MACD；
- RSI；
- BOLL；
- ATR 或收益波动；
- 20/60 日滚动高低点。

默认禁用：

- VWMA；
- MFI；
- 成交量均值；
- 依赖可靠真实成交量的所有信号。

### 9.4 产品配置版本

新增：

```text
config/technical_products_v2.yaml
```

将不同产品的启用指标、最小预热、关系能力和降级规则集中配置，不在 prompt 或业务函数中散落判断。

## 10. 跨序列指标

建议新增 `tradingagents/technical/relative.py`。

### 10.1 可实现指标

以下指标只依赖日期对齐后的价格收益：

1. **共同区间累计收益差**
   - `ETF_return - index_return`；
   - 只能称为市场价格收益差；
2. **滚动收益相关系数**
   - 20/60 个共同交易日；
   - 观察价格路径是否同步；
3. **滚动 beta**
   - 仅在样本充分、参考收益方差不接近零时计算；
   - 作为敏感度描述，不作为跟踪质量结论；
4. **归一化相对强弱线**
   - `subject_norm / reference_norm`；
   - 分析相对强弱趋势，不跨窗口比较绝对水平；
5. **日收益差波动**
   - 可称“市场价格收益差波动”；
   - 不称正式 tracking error；
6. **方向一致率**
   - 共同交易日中日收益同号比例；
7. **技术状态一致性**
   - subject 和 reference 的趋势/动量 stance 是否一致。

### 10.2 禁止输出

仅凭 ETF 市场价与价格指数，禁止输出：

- 真实折溢价；
- NAV 偏离；
- 正式跟踪误差；
- 年化跟踪差异；
- 基金复制能力评级；
- 申购赎回资金流结论；
- 指数成分归因。

### 10.3 `RelativeMetric`

```python
class RelativeMetric(BaseModel):
    metric_id: str
    value: float | None
    window: int | None
    as_of: date
    subject_snapshot_id: str
    reference_snapshot_id: str
    common_observations: int
    status: Literal["ok", "insufficient", "blocked"]
    semantics: str
    rule_version: str
```

`semantics` 必须写清“市场价格 vs 价格指数”或“市场价格 vs 全收益指数”。

## 11. 产品级技术信号

### 11.1 普通股票 `StockTechnicalAssessment`

由以下类别组成：

- 自身趋势；
- 自身动量；
- 自身波动；
- 自身量价；
- 关键位置；
- 可选的相对基准强弱。

基准只调整上下文置信度，不应覆盖自身价格信号。例如股票自身破位、基准上涨时，应输出相对弱势，而不是因为基准上涨改成看多。

### 11.2 被动 ETF `PassiveEtfTechnicalAssessment`

建议形成四个独立维度：

1. `underlying_stance`：跟踪指数趋势；
2. `vehicle_stance`：ETF 市场价格趋势；
3. `liquidity_state`：ETF 成交量/额质量与活跃度；
4. `alignment_state`：ETF 与指数关系的一致、轻微分歧或显著分歧。

最终状态不使用一个不透明总分强制覆盖冲突，而采用决策表：

| 指数 | ETF | 对齐 | 产品技术状态 |
|---|---|---|---|
| bullish | bullish | consistent | bullish_confirmed |
| bearish | bearish | consistent | bearish_confirmed |
| bullish | neutral/mixed | weak_divergence | underlying_bullish_vehicle_unconfirmed |
| bearish | neutral/mixed | weak_divergence | underlying_bearish_vehicle_unconfirmed |
| bullish | bearish | divergent | conflicted |
| bearish | bullish | divergent | conflicted |
| unavailable | 可用 | unavailable | standalone_vehicle_only |
| 任意 | unavailable | 任意 | unavailable |

“ETF 强、指数弱”不能直接解释为折价修复、资金流入或套利机会；只能报告交易载体与底层指数的价格状态分歧。

### 11.3 主动 ETF `ActiveEtfTechnicalAssessment`

由以下维度组成：

- ETF 自身趋势、动量、波动和流动性；
- 与正式比较基准的相对强弱；
- 不生成 tracking alignment；
- 基准缺失时输出 standalone assessment；
- 报告明确“主动管理产品，基准不是机械跟踪目标”。

### 11.4 置信度

置信度由可审计因素组合：

- subject 数据质量；
- reference 数据质量；
- 日期对齐覆盖；
- 指标预热完整性；
- 单项信号覆盖率；
- 类别冲突程度；
- 是否发生 fallback/merge；
- ETF 流动性数据是否完整。

置信度只表示证据完整和一致程度，不表示上涨概率。

## 12. 能力清单 v2

现有 ETF 能力 `price_history / technical_indicators` 太粗。建议新增细粒度能力：

```text
subject_price_history
subject_price_indicators
subject_volume_indicators
subject_amount_indicators
tracking_index_identity
tracking_index_price_history
tracking_index_price_indicators
series_alignment
relative_price_strength
market_price_path_consistency
benchmark_price_history
benchmark_relative_strength
etf_liquidity_metrics
fund_profile
shares_and_aum
index_news_policy
peer_comparison
```

继续关闭且不得用近似值冒充的能力：

```text
nav_iopv
premium_discount
formal_tracking_error
formal_tracking_difference
index_constituent_exposure
pcf
realtime_holdings
```

### 12.1 能力依赖

```text
series_alignment
  requires subject_price_history + reference_price_history

relative_price_strength
  requires series_alignment + sufficient_common_observations

market_price_path_consistency
  requires passive ETF + verified tracking index + series_alignment

formal_tracking_error
  requires NAV series + total-return index + matching frequency/period
```

最后一项在第一版保持关闭。

## 13. 数据获取与降级策略

### 13.1 普通股票

```text
subject stock bars
→ primary source
→ fallback source
→ cross-source sample validation
→ subject quality
→ optional benchmark bars
```

基准失败不阻断股票自身分析。

### 13.2 被动 ETF

```text
ETF identity
├── ETF market bars
├── ETF liquidity fields
└── verified tracking-index identity
      └── tracking-index bars

ETF bars + index bars
→ independent quality reports
→ common-date alignment
→ cross-series metrics
→ product assessment
```

ETF 主行情失败必须阻断；指数失败按 §8.3 降级。

### 13.3 主动 ETF

```text
ETF identity
├── ETF market bars
├── ETF liquidity fields
└── optional disclosed benchmark
```

不将名称相似指数自动当成比较基准。

### 13.4 指数行情源验证硬门

在扩大指数目录前必须完成字段级验证：

- 可支持的 provider 和代码格式；
- 返回的是价格指数、全收益指数还是未知序列；
- 历史长度；
- 最新交易日覆盖；
- 是否存在成交量以及其语义；
- 除数调整或指数修订是否回写历史；
- 请求频率、稳定性和许可；
- 主源失败时是否有语义相同的备用源。

找不到同口径备用源时允许单源，但质量标记为 `single_source_unverified`。

## 14. 技术证据包 v2

建议扩展 `TechnicalEvidenceBundle`：

```python
class ProductTechnicalEvidenceBundle(BaseModel):
    analysis_product: str
    instrument_profile: dict
    subject_quality: DataQualityReport
    reference_quality: DataQualityReport | None
    alignment: SeriesAlignmentReport | None
    subject_indicators: list[IndicatorValue]
    reference_indicators: list[IndicatorValue]
    subject_signals: list[TechnicalSignal]
    reference_signals: list[TechnicalSignal]
    relative_metrics: list[RelativeMetric]
    product_assessment: dict
    unavailable_capabilities: dict[str, str]
    bundle_snapshot_id: str
    versions: dict[str, str]
```

所有报告数值都必须来自该证据包。LLM 不再自行调用 `get_index_data` 后手工比较两段 CSV。

## 15. 报告设计

### 15.1 普通股票报告

```text
1. 数据质量与来源
2. 当前价格和区间表现
3. 趋势结构
4. 动量与波动
5. 量价状态
6. 支撑阻力候选
7. 相对基准表现（可选）
8. 信号一致性、冲突与置信度
9. 数据限制
```

### 15.2 被动指数 ETF 报告

```text
1. ETF 身份、跟踪指数和数据质量
2. 跟踪指数技术状态
3. ETF 市场价格技术状态
4. ETF 成交量、成交额和流动性状态
5. ETF 与指数的价格路径一致性
6. 相对强弱和分歧说明
7. 关键位置
8. 产品技术状态和置信度
9. 明确不可得能力
```

强制术语：

- 有 NAV/IOPV 才可使用“折溢价”；
- 有全收益指数和合适基金净值才可使用正式“跟踪误差/跟踪差异”；
- 否则统一使用“市场价格收益差”“价格路径一致性”“相对强弱”。

### 15.3 主动股票 ETF 报告

```text
1. ETF 身份和主动管理属性
2. ETF 自身技术状态
3. 成交量、成交额和流动性
4. 相对正式比较基准表现（可选）
5. 技术信号冲突与置信度
6. 数据限制
```

不得使用跟踪指数模板。

### 15.4 指数子报告

指数子报告只作为 ETF 报告的一部分或附件，不输出交易评级，并标明：

- 指数 provider、code、variant；
- 实际行情来源；
- 是否为价格指数；
- 禁用的量价指标；
- 数据质量和快照 ID。

## 16. LLM 和下游决策改造

### 16.1 技术分析师

技术分析师接收产品证据包，职责是：

- 解释结构化结果；
- 区分 ETF、指数和普通股票；
- 解释一致与冲突；
- 明确降级和不可得能力；
- 不修改程序生成的 stance、confidence 和 quality decision。

### 16.2 多空研究员

普通股票允许使用：

- 股票自身技术状态；
- 相对市场强弱；
- 其他个股分析师证据。

被动 ETF 允许使用：

- 指数趋势；
- ETF 价格确认；
- 流动性；
- 价格路径一致性；
- ETF 结构、指数新闻和同类比较。

主动 ETF 允许使用：

- ETF 自身技术与流动性；
- 正式比较基准相对表现；
- 不得使用机械跟踪逻辑。

### 16.3 最终评级

- 指数不单独评级；
- ETF subject 可进入最终评级；
- reference 缺失时，最终理由必须标明 ETF 分析已降级；
- `product_assessment=conflicted` 时不能仅凭技术面形成强方向评级；
- `subject decision=block` 时技术证据不得进入方向评级；
- 数据不足不是 Hold，应输出 unavailable/data insufficient 状态供前端展示。

## 17. UI 与 CLI

### 17.1 输入

用户只输入证券代码和分析日期。系统自动：

- 识别普通股票或 ETF；
- 识别主动/被动股票 ETF；
- 解析跟踪指数或比较基准；
- 必要时要求用户确认指数候选；
- 冻结关系后开始分析。

### 17.2 ETF 页面

报告顶部显示：

```text
分析对象：510300 沪深300ETF
产品类型：被动股票指数ETF
跟踪指数：CSI:000300:price
ETF 数据：B / FALLBACK_OK / source=...
指数数据：A / PRIMARY_OK / source=...
共同观察：220 / coverage=...
组合快照：sha256:...
产品规则：passive-equity-etf-v2
```

### 17.3 分栏展示

ETF 技术页建议使用三个逻辑分栏：

- 跟踪指数；
- ETF 市场价格；
- 二者关系。

若指数不可用，保留分栏但显示不可得原因，不能让“关系”区块无提示消失。

### 17.4 历史记录

历史记录保存：

- analysis product；
- instrument profile hash；
- reference instrument ID；
- subject/reference/bundle snapshot IDs；
- product assessment；
- 数据质量和规则版本。

旧记录没有这些字段时按 legacy 展示，不重新猜测跟踪指数。

## 18. 非交易型有效性评估

### 18.1 普通股票

继续评估：

- 5/20/60 日未来收益；
- 相对适当基准 alpha；
- bullish/bearish 方向区分度；
- 按质量、板块、年份和市场状态分层。

### 18.2 被动 ETF

分别评估三个问题：

1. 指数技术状态与指数未来价格收益是否有区分度；
2. ETF 技术状态与 ETF 未来市场价格收益是否有区分度；
3. `bullish_confirmed / bearish_confirmed / conflicted` 是否比单看 ETF 或指数更有区分度。

另外评估：

- 数据降级是否导致产品状态翻转；
- 高低对齐覆盖下结果是否稳定；
- 价格路径分歧后是否倾向收敛，仅作为统计观察，不解释为可套利收益。

### 18.3 主动 ETF

评估 ETF 自身技术状态及相对正式基准的未来表现，不评估 tracking consistency。

### 18.4 明确排除

评估报告不输出：

- 组合净值；
- 年化策略收益；
- 夏普和最大回撤；
- 扣费收益；
- 可成交收益；
- T+1、涨跌停、停牌、滑点或订单模拟。

报告必须标注“信号统计评估，不是交易回测”。

## 19. 测试策略

### 19.1 身份与关系测试

- 普通股票不会被识别成指数或 ETF；
- 被动 ETF 必须冻结 tracking index；
- 主动 ETF 不产生 tracking index 能力；
- 相似指数名称不发生包含匹配误路由；
- 用户确认的指数代码保留 provenance；
- 历史任务不因目录升级改变引用。

### 19.2 多序列数据测试

- subject/reference 独立 fallback；
- ETF 成功、指数失败；
- 指数成功、ETF 失败；
- 两边日期不完全一致；
- 序列 variant 不明；
- 共同观察不足；
- bundle snapshot 可离线重建；
- 无任何前向或后向填充。

### 19.3 指标与信号测试

- 指数不生成 volume/VWMA/MFI 信号；
- ETF Amount 缺失时关闭成交额指标但保留可用指标；
- 股票与 ETF 使用各自产品配置；
- subject/reference 趋势一致时产生 confirmed 状态；
- 趋势相反时产生 conflicted，而不是强制多空；
- reference 不可用时产生 standalone 状态；
- 相同 bundle snapshot 和规则版本完全确定。

### 19.4 术语安全测试

在缺少 NAV、IOPV、全收益指数时，报告不得出现未经限定的：

- 折价、溢价；
- 跟踪误差；
- 跟踪差异；
- 套利机会；
- 资金净流入；
- 实际持仓变化。

使用否定或“数据不可得”语境时不能误报违规，复用现有排除窗口思想。

### 19.5 黄金样本

至少建立：

| 类型 | 示例场景 |
|---|---|
| 普通股票 | 沪市、深市、创业板、科创板、北交所各一只 |
| 宽基 ETF | ETF 与指数数据均完整 |
| 行业 ETF | 相似指数名称防误匹配 |
| 主题 ETF | 指数单源降级 |
| 主动 ETF | 无 tracking index，仅可选 benchmark |
| ETF 降级 | ETF fallback，指数 primary |
| 指数降级 | ETF primary，指数缺失 |
| 关系冲突 | ETF 与指数技术方向相反 |
| 口径风险 | 指数 variant unknown |

黄金样本冻结 profile、两条行情快照、对齐报告、指标、单项信号、产品状态和证据包。

## 20. 分阶段实施计划

### 阶段 0：范围和数据源验证

目标：确认产品边界以及指数行情能支持什么语义。

工作项：

1. 冻结第一版纳入/排除的 ETF 分类；
2. 抽样验证现有 ETF 主数据能否区分主动与被动；
3. 验证常见指数 provider、代码、variant 和历史覆盖；
4. 验证指数 volume 是否可用，默认按不可用处理；
5. 形成 `INDEX_DATA_SOURCE_VALIDATION.md`；
6. 选定黄金样本。

硬门：

- 无法确认指数代码或序列口径的产品不开放双序列能力；
- 没有可靠指数来源不阻止 ETF 自身分析，但不能实现关系信号；
- 不允许为了填满报告使用名称搜索结果代替验证。

验收：

- 每个纳入的 ETF 子类有明确身份判据；
- 每个指数数据能力有字段级来源结论；
- price / total return / unknown 可以区分；
- 第一版指数目录范围明确。

### 阶段 1：标的关系和能力 v2

目标：让系统明确知道分析对象和参考对象的关系。

工作项：

1. 扩展 `InstrumentProfile` 和 `ReferenceInstrument`；
2. 增加 `analysis_product`；
3. 外置 provider-qualified 指数目录；
4. 重写指数匹配为精确匹配 + 用户确认；
5. 实现能力清单 v2 及依赖；
6. 兼容旧 stock/etf mode 和历史快照。

验收：

- 普通股票、被动 ETF、主动 ETF 路由正确；
- 被动 ETF 的 tracking index 来源可审计；
- 主动 ETF 不误用跟踪逻辑；
- 模糊匹配不自动冻结。

### 阶段 2：多序列数据包和组合快照

目标：一次分析得到彼此独立、可对齐、可复现的 subject/reference 数据。

工作项：

1. 实现 `AnalysisMarketDataBundle`；
2. 为 index 完成结构化 adapter 和质量校验；
3. 实现对齐报告；
4. 实现组合质量决策；
5. 实现 bundle snapshot；
6. 禁止填充制造共同日期。

验收：

- 两条序列分别记录实际来源和质量；
- 任一序列失败时按矩阵正确降级；
- 组合快照离线可重建；
- 对齐结果逐日期可核验。

### 阶段 3：产品化指标配置

目标：股票、ETF、指数使用正确的指标集合。

工作项：

1. 增加 `technical_products_v2.yaml`；
2. 将现有统一 IndicatorConfig 拆成产品配置；
3. 为 ETF 增加 Amount/流动性技术统计；
4. 默认关闭指数 volume 类指标；
5. 对所有产品实现独立预热判断；
6. 建立产品黄金回归。

验收：

- 指数没有伪量价信号；
- Amount 缺失只关闭依赖项；
- 产品配置和指标版本进入证据包；
- 同输入同版本输出一致。

### 阶段 4：跨序列指标和产品状态

目标：建立语义受控的 ETF—指数关系分析。

工作项：

1. 实现 `relative.py`；
2. 实现共同收益差、相关、beta、相对强弱和方向一致率；
3. 实现 `SeriesAlignmentReport` 门控；
4. 实现普通股票、被动 ETF、主动 ETF 三类 assessment；
5. 将 conflict/standalone/unavailable 设为一等状态；
6. 增加禁用术语程序检查。

验收：

- 未取得 NAV/TR 时不产生正式跟踪质量字段；
- ETF 与指数冲突不被压成单一方向；
- reference 失败时不影响 subject 原始信号；
- 所有关系指标包含共同观察数和语义标签。

### 阶段 5：报告与下游流程

目标：把产品状态安全地呈现并传递给决策链。

工作项：

1. 扩展 ProductTechnicalEvidenceBundle；
2. 重写三类报告模板；
3. 更新技术分析师 prompt 和事实核验；
4. 更新质量门控、研究员、交易员和组合经理规则；
5. 更新 Web/CLI 分栏、警告和历史记录；
6. 增加 legacy 兼容展示。

验收：

- 报告明确区分 ETF、指数和股票证据；
- 禁止术语检查通过；
- 数据不足不显示成 Hold；
- 所有数值可追溯到 bundle snapshot；
- 下游不能把指数 stance 当作 ETF 已确认 stance。

### 阶段 6：非交易型信号评估

目标：验证产品化信号是否比单序列信号更有统计区分度。

工作项：

1. 扩展 evaluator 支持 analysis product；
2. 分别标签 ETF 和指数未来价格收益；
3. 比较 subject-only、reference-only、confirmed/conflicted 状态；
4. 按来源、质量、对齐覆盖和产品类型分层；
5. 输出置信区间、样本量和版本；
6. 与 `performance.py` 分开展示。

验收：

- 评估严格点时；
- 不模拟交易限制或成交；
- 不输出策略收益指标；
- 可以回答双序列分析是否增加信息，而不是只增加报告长度。

### 阶段 7：灰度发布

目标：先验证可解释性和稳定性，再替代现有 market analyst 路径。

步骤：

1. shadow 模式并行生成 v1/v2，不影响现有最终评级；
2. 比较数据覆盖、降级率、信号翻转率和报告事实错误率；
3. 先对普通股票启用 v2；
4. 再对有 verified tracking index 的 ETF 启用双序列；
5. 主动 ETF 最后启用；
6. 保留配置开关快速回退到 v1 报告，但不回退数据质量阻断。

退出 shadow 的条件：

- 黄金样本全绿；
- 离线结果确定；
- 禁用术语零违规；
- 主源失败时降级行为符合矩阵；
- v2 的新增信号能够解释其输入和规则；
- 未发现指数错配。

## 21. 推荐文件变更

新增：

```text
config/index_catalog_v2.yaml
config/technical_products_v2.yaml
config/relative_signal_rules_v1.yaml
tradingagents/dataflows/analysis_bundle.py
tradingagents/dataflows/index_master.py
tradingagents/technical/relative.py
tradingagents/technical/products.py
tradingagents/technical/product_evidence.py
tests/test_instrument_relationships.py
tests/test_analysis_bundle.py
tests/test_relative_indicators.py
tests/test_product_technical_assessment.py
tests/test_etf_index_terminology.py
tests/fixtures/index_data/...
```

重点修改：

```text
tradingagents/dataflows/instrument.py
tradingagents/dataflows/index_catalog.py
tradingagents/dataflows/analysis_capabilities.py
tradingagents/dataflows/market_data_service.py
tradingagents/dataflows/models.py
tradingagents/technical/indicators.py
tradingagents/technical/signals.py
tradingagents/technical/evidence.py
tradingagents/technical/report_validation.py
tradingagents/agents/analysts/market_analyst.py
tradingagents/agents/quality_gate.py
tradingagents/agents/utils/agent_states.py
tradingagents/agents/utils/agent_utils.py
tradingagents/graph/trading_graph.py
tradingagents/evaluation/technical_signal_evaluator.py
web/components/report_viewer.py
cli/main.py
```

## 22. 实施优先级

### P0：语义正确性

- 准确区分普通股票、被动股票 ETF 和主动股票 ETF；
- provider-qualified 跟踪指数身份；
- 禁止 price index 冒充 total-return index；
- 禁止使用正式跟踪误差、折溢价等无数据支持的术语；
- subject 数据失败时 fail closed。

### P1：双序列技术能力

- 独立 subject/reference 质量；
- 日期对齐；
- 组合快照；
- ETF—指数相对指标；
- confirmed/conflicted/standalone 产品状态。

### P2：产品体验和验证

- 三类报告；
- UI 分栏；
- 下游提示词；
- shadow 模式；
- 非交易型有效性评估。

## 23. 最终验收标准

项目完成后必须满足：

1. 系统可以稳定识别普通 A 股、被动股票 ETF 和主动股票 ETF。
2. 被动 ETF 的跟踪指数具有 provider、code、variant 和来源，不靠名称猜测。
3. ETF 和指数行情分别拥有质量等级、来源尝试和快照。
4. 多序列只按共同真实交易日对齐，不前向或后向填充。
5. 股票、ETF、指数使用不同的产品指标配置。
6. 指数成交量语义不明时不生成量价指标。
7. 被动 ETF 报告同时展示指数、ETF 和二者关系，并保留冲突状态。
8. 主动 ETF 不使用机械跟踪语义。
9. 缺少 NAV、IOPV 或全收益指数时不输出折溢价或正式跟踪质量结论。
10. reference 缺失时能够显式降级，subject 缺失时阻断。
11. 同一 bundle snapshot 和规则版本重复运行得到完全一致的指标与产品状态。
12. LLM 只能解释证据包，不能修改质量、方向或具体数值。
13. 历史记录保存 subject/reference/bundle 快照和产品规则版本。
14. 有效性评估按产品、质量、来源和对齐覆盖分层。
15. 评估明确是信号统计，不是含 A 股交易限制的回测或策略业绩。

## 24. 推荐的第一批交付

为控制风险，第一批只交付以下最小闭环：

1. 普通 A 股自身技术分析 v2；
2. 被动股票指数 ETF + verified 跟踪指数双序列；
3. 指数禁用 volume 类指标；
4. ETF—指数共同收益差、相关、相对强弱和技术状态一致性；
5. `bullish_confirmed / bearish_confirmed / conflicted / standalone_vehicle_only / unavailable`；
6. 组合快照和三栏 ETF 报告；
7. 禁止术语检查；
8. shadow 模式。

第一批暂缓：

- 主动 ETF 比较基准自动解析；
- beta 以外的复杂统计关系模型；
- 背离后收敛概率模型；
- 指数成分和行业贡献归因；
- NAV/IOPV 与正式跟踪质量；
- 自动参数优化。

这一顺序能先解决最重要的问题：让普通股票保持确定性，让被动 ETF 的结论同时尊重底层指数和交易载体，并在任何一条数据链降级时给出可审计、不过度推断的结果。
