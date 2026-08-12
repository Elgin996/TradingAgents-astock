# 指数行情数据源验证

> 文档状态：阶段 0 已完成；阶段 1–4 仅开放价格指数关系能力
> 验证基线：2026-08-12
> 依赖记录：`ETF_DATA_SOURCE_VALIDATION.md`

## 范围结论

当前工程已验证的指数输入是境内指数的日线 OHLC；它用于指数趋势、动量、波动和关键位置分析，以及 ETF 的价格路径比较。指数不是可直接交易证券，指数子报告不产生 Buy/Sell 等可执行评级。

## 字段级结论

| 字段 | 当前结论 | 运行时处理 |
|---|---|---|
| provider + code | 常见指数通过版本化 `config/index_catalog_v2.yaml` 精确冻结；目录外代码必须有用户或主数据来源 | provider-qualified，不使用名称包含匹配 |
| 序列 variant | 当前目录只收录 `price` | 价格指数不得描述为全收益指数 |
| 日线 OHLC | 沿用结构化 `MarketDataService`，指数主源为新浪，备用源按策略显式配置 | 记录独立 source attempts、质量和快照 |
| 成交量 | 供应方返回字段的统计口径未统一验证 | 默认禁用 volume/VWMA/MFI |
| 全收益/净收益序列 | 当前没有稳定、许可清晰且口径一致的公共来源 | 关闭正式 tracking error/difference |
| 指数成分与权重 | 当前没有覆盖完整且许可清晰的来源 | 关闭 constituent exposure/归因 |
| 历史覆盖 | 由每次行情质量报告按请求区间核验 | 缺失日期不前向/后向填充 |
| 除数调整和历史回写 | 未形成统一供应方契约 | 质量报告保留 single-source/unverified 标记 |

## 硬门

1. provider、code、variant 未同时确认时，不开放双序列关系指标。
2. 名称只用于精确规范化名称或精确别名匹配；相似名称只返回候选，不自动冻结。
3. 找不到语义相同的备用源时允许单源，但必须记录 `single_source_unverified`。
4. ETF 市场价与价格指数之间的差异只能称为“市场价格收益差”“价格路径一致性”或“相对强弱”。
5. NAV/IOPV 与全收益指数未取得前，不输出折溢价、正式跟踪误差、正式跟踪差异或套利机会。

## 第一版目录

第一版目录覆盖当前旧目录中的沪深 300、中证 500、中证 1000、中证 800、中证 A500、上证 50、上证 180、科创 50、创业板、深证成指、中小板、中证银行、中证白酒、中证医药、中证红利和上证红利。每条记录拥有独立 `instrument_id`，其中 `price` 是序列变体的一部分；后续加入全收益序列时不得复用价格序列 ID。

## 关闭能力

以下能力在本验证基线关闭：`nav_iopv`、`premium_discount`、`formal_tracking_error`、`formal_tracking_difference`、`index_constituent_exposure`、`pcf`、`realtime_holdings`。
