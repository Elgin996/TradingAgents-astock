"""Guard: the package must compile cleanly under SyntaxWarning-as-error."""

import compileall
import warnings


def test_package_compiles_without_syntax_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)
        assert compileall.compile_dir(
            "tradingagents", quiet=2, force=True
        ), "SyntaxWarning raised during compile"
