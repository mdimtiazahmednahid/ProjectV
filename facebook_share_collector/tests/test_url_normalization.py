import pytest
from app.utils.url_normalizer import normalize_url

def test_add_https():
    assert normalize_url("facebook.com/john") == "https://www.facebook.com/john"

def test_normalize_mobile_subdomains():
    assert normalize_url("https://m.facebook.com/john") == "https://www.facebook.com/john"
    assert normalize_url("https://mbasic.facebook.com/john") == "https://www.facebook.com/john"

def test_remove_trailing_slash():
    assert normalize_url("https://www.facebook.com/john/") == "https://www.facebook.com/john"

def test_preserve_valid_url():
    valid = "https://www.facebook.com/john.doe.123"
    assert normalize_url(valid) == valid
