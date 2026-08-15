<p align="center"><a href="README.md">简体中文</a> | <b>English</b></p>

<h1 align="center">TradingAgents-Astock</h1>

<p align="center">
  A-share specialization of <a href="https://github.com/TauricResearch/TradingAgents">TauricResearch/TradingAgents</a><br>
  Apache 2.0 · Python ≥ 3.10 · <code>pip install -e .</code> and run
</p>

<p align="center">
  <b>For research and education. Not investment advice.</b>
</p>

<p align="center">
  <a href="https://github.com/simonlin1212/tradingagents-astock/stargazers"><img alt="Stars" src="https://img.shields.io/github/stars/simonlin1212/tradingagents-astock?style=social"/></a>
  <a href="./LICENSE"><img alt="License" src="https://img.shields.io/badge/License-Apache_2.0-blue"/></a>
  <a href="https://arxiv.org/abs/2412.20138"><img alt="Paper" src="https://img.shields.io/badge/paper-arXiv_2412.20138-B31B1B?logo=arxiv"/></a>
</p>

Seven analysts (market / sentiment / news / fundamentals + policy / hot money / lock-up) produce A-share research via bull/bear debate and three-way risk review. Data comes from mootdx, Eastmoney, Tencent, Sina, and 10jqka — not Tushare or Yahoo.

<p align="center">
  <img src="assets/web-ui-welcome.png" width="80%" alt="Web UI"/>
</p>

## Quick start

```bash
git clone https://github.com/simonlin1212/tradingagents-astock.git
cd tradingagents-astock
python3 -m venv .venv && source .venv/bin/activate   # Windows: py -3 -m venv .venv && .venv\Scripts\activate
pip install -e .
cp .env.example .env   # fill in the API key for your provider
```

| Provider | Env var |
|----------|---------|
| MiniMax | `MINIMAX_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Qwen | `DASHSCOPE_API_KEY` |
| GLM | `ZHIPU_API_KEY` |
| OpenAI | `OPENAI_API_KEY` |
| Anthropic / Kimi | `ANTHROPIC_API_KEY` (Kimi also needs `ANTHROPIC_BASE_URL`) |
| OpenRouter | `OPENROUTER_API_KEY` |
| OpenAI-compatible gateway | `OPENAI_COMPATIBLE_API_KEY` + `BACKEND_URL` |

Each provider uses **its own** env var, not a shared `OPENAI_API_KEY`. Restart after editing `.env`.

```bash
tradingagents-web             # Web UI → http://localhost:8501
tradingagents                 # interactive CLI (bare invoke starts analysis)
tradingagents quick 600519    # Market Analyst only → Markdown
tradingagents quick 517520.etf
tradingagents performance     # direction accuracy on settled decisions (no LLM)
```

Python:

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

A full run is about 30–50 LLM calls. ETFs accept a `.etf` suffix and default to the market analyst only.

## Config that matters

| Key | Role |
|-----|------|
| `llm_provider` / `deep_think_llm` / `quick_think_llm` | Provider and models. Deep is for Research / Portfolio Manager; everyone else uses quick |
| `backend_url` | Custom gateway; or `BACKEND_URL` in `.env` |
| `max_tokens` | Output cap. Truncated reports → raise this or `TRADINGAGENTS_MAX_TOKENS` |
| `output_language` | Report language (internal debate stays English) |
| `role_llms` | Optional per-role models; valid keys in `ROLE_KEYS` (`graph/setup.py`) |
| `EM_MIN_INTERVAL` | Eastmoney throttle (default 1s). Use `1.5`–`2` for batch runs |

Optional extras: Gemini needs an explicit `pip install --no-deps "langchain-google-genai>=4.0.0"` plus `google-genai` / `httpx>=0.28.1` (no `[google]` extra — it conflicts with mootdx's httpx pin). Personal Claude Pro/Max: `pip install -e ".[agentsdk]"`.

## More

- Upstream delta: [CHANGES_FROM_UPSTREAM.md](./CHANGES_FROM_UPSTREAM.md)
- Releases: [CHANGELOG.md](./CHANGELOG.md)
- Dev notes: [CLAUDE.md](./CLAUDE.md)
- Paper: [arXiv:2412.20138](https://arxiv.org/abs/2412.20138)

## License

[Apache 2.0](./LICENSE). Fork of [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents); see [NOTICE](./NOTICE).
