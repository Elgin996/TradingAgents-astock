<p align="center"><b>简体中文</b> | <a href="README_en.md">English</a></p>

<h1 align="center">TradingAgents-Astock</h1>

<p align="center">
  基于 <a href="https://github.com/TauricResearch/TradingAgents">TauricResearch/TradingAgents</a> 的 A 股特化 fork<br>
  Apache 2.0 · Python ≥ 3.10 · <code>pip install -e .</code> 即可运行
</p>

<p align="center">
  <b>研究与教学用途，不构成投资建议。</b>
</p>

<p align="center">
  <a href="https://github.com/simonlin1212/tradingagents-astock/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/simonlin1212/tradingagents-astock?style=social"/></a>
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/License-Apache_2.0-blue"/></a>
  <a href="https://arxiv.org/abs/2412.20138"><img alt="论文" src="https://img.shields.io/badge/论文-arXiv_2412.20138-B31B1B?logo=arxiv"/></a>
</p>

7 个 Analyst（市场 / 情绪 / 新闻 / 基本面 + 政策 / 游资 / 解禁）通过多空辩论和三方风控，生成 A 股投研报告。数据走 mootdx、东财、腾讯、新浪、同花顺等直连接口，不依赖 Tushare / Yahoo。

<p align="center">
  <img src="assets/web-ui-welcome.png" width="80%" alt="Web UI"/>
</p>

## 快速开始

```bash
git clone https://github.com/simonlin1212/tradingagents-astock.git
cd tradingagents-astock
python3 -m venv .venv && source .venv/bin/activate   # Windows: py -3 -m venv .venv && .venv\Scripts\activate
pip install -e .
cp .env.example .env   # 填入你用的供应商 API Key
```

| 供应商 | 环境变量 |
|--------|----------|
| MiniMax | `MINIMAX_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| 通义 | `DASHSCOPE_API_KEY` |
| 智谱 | `ZHIPU_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic / Kimi | `ANTHROPIC_API_KEY`（Kimi 还要设 `ANTHROPIC_BASE_URL`） |
| OpenRouter | `OPENROUTER_API_KEY` |
| OpenAI 兼容网关 | `OPENAI_COMPATIBLE_API_KEY` + `BACKEND_URL` |

每个供应商用**自己的**环境变量，不是一律 `OPENAI_API_KEY`。改完 `.env` 后重启进程。

```bash
tradingagents-web             # Web UI → http://localhost:8501
tradingagents                 # 交互式 CLI（裸跑即开始分析）
tradingagents quick 600519    # 仅 Market Analyst，输出 Markdown
tradingagents quick 517520.etf
tradingagents performance     # 已结算决策的方向正确率（零 LLM）
```

Python：

```python
from tradingagents.graph.trading_graph import TradingAgentsGraph

config = {
    "llm_provider": "deepseek",
    "deep_think_llm": "deepseek-chat",
    "quick_think_llm": "deepseek-chat",
    "output_language": "Chinese",
}
final_state, decision = TradingAgentsGraph(config=config).propagate("600519", "2026-08-14")
print(decision)
```

一次完整分析大约 30–50 次 LLM 调用。ETF 可加 `.etf` 后缀，默认只跑技术分析师。

## 配置要点

| 项 | 说明 |
|----|------|
| `llm_provider` / `deep_think_llm` / `quick_think_llm` | 供应商与模型。deep 用于 Research / Portfolio Manager，其余角色用 quick |
| `backend_url` | 自定义网关；也可用 `.env` 的 `BACKEND_URL` |
| `max_tokens` | 单次输出上限。报告写一半就断，调这个或 `TRADINGAGENTS_MAX_TOKENS` |
| `output_language` | 报告语言（内部辩论仍为英文） |
| `role_llms` | 可选，给单个角色换模型，合法键见 `graph/setup.py` 的 `ROLE_KEYS` |
| `EM_MIN_INTERVAL` | 东财请求间隔（默认 1s）。批量分析可设 `1.5`～`2` |

可选依赖：Gemini 需显式 `pip install --no-deps "langchain-google-genai>=4.0.0"` 和 `google-genai` / `httpx>=0.28.1`（与 mootdx 的 httpx 钉死冲突，故无 `[google]` extra）。个人 Claude 订阅走 `pip install -e ".[agentsdk]"`。

## 更多

- 与上游差异：[CHANGES_FROM_UPSTREAM.md](./CHANGES_FROM_UPSTREAM.md)
- 版本记录：[CHANGELOG.md](./CHANGELOG.md)
- 开发约定：[CLAUDE.md](./CLAUDE.md)
- 论文：[arXiv:2412.20138](https://arxiv.org/abs/2412.20138)

## License

[Apache 2.0](./LICENSE)。本项目是 [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 的 fork，详见 [NOTICE](./NOTICE)。
