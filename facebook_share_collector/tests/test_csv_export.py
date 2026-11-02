import pytest
import os
import csv
from app.models.share_profile import ShareProfile
from app.exporters.csv_exporter import CSVExporter

def test_csv_export(tmp_path):
    p1 = ShareProfile(name="John Doe", profile_url="https://facebook.com/john", source="ui", confidence=0.9, session_id="1")
    p2 = ShareProfile(name="Jane Smith", profile_url=None, source="ui", confidence=0.8, session_id="1")
    
    output_file = tmp_path / "test_export.csv"
    
    success = CSVExporter.export([p1, p2], str(output_file))
    assert success
    assert os.path.exists(output_file)
    
    # Verify contents
    with open(output_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        
        assert len(rows) == 2
        assert rows[0]["Name"] == "John Doe"
        assert rows[0]["Profile URL"] == "https://facebook.com/john"
        assert rows[1]["Name"] == "Jane Smith"
        assert rows[1]["Profile URL"] == ""
