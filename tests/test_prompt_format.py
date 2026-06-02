"""tests.test_prompt_format -- verify every {placeholder} in a prompt template
is satisfied by the corresponding caller's .format() call.

Catches the silent class of bug where a new prompt block is added but the
caller forgets to pass the variable, causing a KeyError at runtime when the
push fires. Uses Python's ast module to walk format() calls reliably (regex
trips on nested parens inside f-strings + str() calls).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _extract_placeholders(text: str) -> set[str]:
    """Return the set of {placeholder} names in a template string."""
    return set(_PLACEHOLDER_RE.findall(text))


def _kwargs_passed_to_format_calls(py_source: str) -> set[str]:
    """Walk the AST and collect every kw= name passed to a `.format(...)` call.

    Aggregates across ALL format() invocations in the file so a module with
    multiple .format() calls (e.g. thesis.py with extract + verify both using
    user_template.format()) gets full coverage.
    """
    tree = ast.parse(py_source)
    kwargs: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match `<anything>.format(...)`
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "format":
            for kw in node.keywords:
                if kw.arg:
                    kwargs.add(kw.arg)
    return kwargs


def _check_prompt(
    prompt_path: str, py_source_path: str, *, placeholders_section: str = "[USER]",
) -> None:
    """Shared assertion helper: every prompt placeholder has a matching kwarg."""
    prompt = Path(prompt_path).read_text(encoding="utf-8")
    py_source = Path(py_source_path).read_text(encoding="utf-8")

    user_part = prompt.split(placeholders_section, 1)[-1]
    placeholders = _extract_placeholders(user_part)
    kw_names = _kwargs_passed_to_format_calls(py_source)
    missing = placeholders - kw_names
    assert not missing, (
        f"\n  Prompt:  {prompt_path}"
        f"\n  Caller:  {py_source_path}"
        f"\n  Missing kwargs in any .format() call: {sorted(missing)}"
        f"\n  Either pass them or drop the placeholder from the prompt."
    )


def test_research_prompt() -> None:
    """Every {var} in prompts/research.txt is passed to research.py format() calls."""
    _check_prompt("prompts/research.txt", "src/stock/research.py")


def test_grading_prompt() -> None:
    """Every {var} in prompts/grading.txt is passed to grading.py format() calls."""
    _check_prompt("prompts/grading.txt", "src/stock/grading.py")


def test_event_verify_prompt() -> None:
    """Every {var} in prompts/event_verify.txt is passed to events.py format() calls."""
    _check_prompt("prompts/event_verify.txt", "src/stock/events.py")


def test_thesis_extract_prompt() -> None:
    """Every {var} in prompts/thesis_extract.txt is passed to thesis.py format() calls."""
    _check_prompt("prompts/thesis_extract.txt", "src/stock/thesis.py")


def test_thesis_verify_prompt() -> None:
    """Every {var} in prompts/thesis_verify.txt is passed to thesis.py format() calls."""
    _check_prompt("prompts/thesis_verify.txt", "src/stock/thesis.py")


def test_deep_dive_prompt() -> None:
    """Every {var} in prompts/deep_dive.txt is passed to research.py format() calls."""
    _check_prompt("prompts/deep_dive.txt", "src/stock/research.py")


def test_reply_prompt() -> None:
    """Every {var} in prompts/reply.txt is passed to research.py format() calls."""
    _check_prompt("prompts/reply.txt", "src/stock/research.py")
