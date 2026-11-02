import pytest
from app.utils.text_normalizer import normalize_text

def test_trim_whitespace():
    assert normalize_text("  John Doe  ") == "John Doe"

def test_collapse_spaces():
    assert normalize_text("John    Doe") == "John Doe"

def test_preserve_bangla():
    bangla_text = "রহিম আহমেদ"
    assert normalize_text(f"  {bangla_text}  ") == bangla_text

def test_empty_string():
    assert normalize_text("") == ""
    assert normalize_text(None) == ""
