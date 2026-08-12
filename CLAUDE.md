# TradingAgents-Astock

## 项目定位

A 股多 Agent 投研框架，要求 Python 3.10+。

- 核心代码：`tradingagents/`
- CLI：`cli/`
- Web UI：`web/`
- 测试：`tests/`
- 文档：`docs/`

## 开发规则

- 先检查 `git status`，保留已有改动，只修改任务范围内的文件。
- 数据层遵循既有接口与 vendor 路由；ticker 输入必须经过标准化和安全校验。
- 历史日期分析不得引入未来数据；东财请求统一使用数据层的节流入口。
- Agent 节点使用统一的角色模型配置接口，不绕过配置直接选模型。
- 文档放在 `docs/`，Issue 记录放在 `docs/issues/`。
- 更新版本时同步 `pyproject.toml`、`docs/CHANGELOG.md`，并运行版本一致性测试。

## 验证

优先运行相关测试；跨模块改动运行：

```bash
python -m pytest tests/ -v
```
