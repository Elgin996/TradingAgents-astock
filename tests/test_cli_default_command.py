"""裸跑 `tradingagents` 必须仍然直接开始分析（codex 第四轮）。

Typer 在只注册一个命令时用"单命令模式"，裸跑就等于跑那个命令；一旦注册第二个
子命令（v0.5.2 加的 `performance`），它切换成"命令组模式"，裸跑直接报
`Missing command` 退出——而 README 和所有文档写的都是裸跑。这是升级即破坏。
"""
import inspect

from typer.testing import CliRunner

from cli.main import app


def test_bare_invocation_does_not_error_with_missing_command(monkeypatch):
    called = {}

    import cli.main as m
    monkeypatch.setattr(m, "run_analysis", lambda **kw: called.update(kw))

    result = CliRunner().invoke(app, [])

    assert "Missing command" not in (result.output or "")
    assert result.exit_code == 0
    assert called == {"checkpoint": False}, "裸跑应当直接进入分析流程"


def test_bare_invocation_still_accepts_original_flags(monkeypatch):
    called = {}

    import cli.main as m
    monkeypatch.setattr(m, "run_analysis", lambda **kw: called.update(kw))

    result = CliRunner().invoke(app, ["--checkpoint"])

    assert result.exit_code == 0
    assert called == {"checkpoint": True}


def test_subcommands_are_still_registered():
    names = {c.name or c.callback.__name__ for c in app.registered_commands}
    assert "analyze" in names
    assert "performance" in names
    assert "quick" in names


def test_performance_prints_markdown_report(monkeypatch):
    """非 --json 路径必须把 format_report 打出来，不能静默 return。"""
    import tradingagents.agents.utils.memory as memory_mod

    class _FakeLog:
        def __init__(self, _config):
            pass

        def load_entries(self):
            return []

    monkeypatch.setattr(memory_mod, "TradingMemoryLog", _FakeLog)

    result = CliRunner().invoke(app, ["performance"])

    assert result.exit_code == 0
    assert "暂无可统计的决策结果" in (result.output or "")


def test_quick_analyze_is_declared_as_installable_module():
    """console script ``tradingagents-quick`` 需要根模块被 setuptools 安装。"""
    from pathlib import Path

    text = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert 'tradingagents-quick = "quick_analyze:main"' in text
    assert 'py-modules = ["quick_analyze"]' in text


def test_callback_explains_why_it_exists():
    """这个 callback 很容易在重构时被当成多余删掉——注释必须说清后果。"""
    src = inspect.getsource(app.registered_callback.callback)
    assert "Missing command" in src
