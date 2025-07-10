import pytest
from utils.command_matcher import CommandMatcher

@pytest.mark.parametrize("input_text,expected", [
    ("menu", "menu"),
    ("menue", "menu"),
    ("help", "help"),
    ("halp", "help"),
    ("settings", "settings"),
    ("setings", "settings"),
    ("1", None),
    ("unknown command", None),
    ("menu 🍔", "menu"),
])
def test_command_matching(input_text, expected):
    matcher = CommandMatcher()
    result = matcher.match(input_text)
    assert (result["command"] == expected) or (expected is None and result["command"] is None)

@pytest.mark.parametrize("input_text,correction", [
    ("menue", "menu"),
    ("halp", "help"),
    ("setings", "settings"),
])
def test_command_corrections(input_text, correction):
    matcher = CommandMatcher()
    result = matcher.match(input_text)
    assert correction in (result.get("corrections") or [])
