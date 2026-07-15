"""Tests for record validation: schema-driven checks on extractor output."""

from app.agent.validation import build_validator, validate_records

SCHEMA = {
    "fields": [
        {"name": "title", "type": "string", "required": True},
        {"name": "points", "type": "integer", "required": False},
        {"name": "url", "type": "string", "required": True},
    ]
}


class TestValidation:
    def test_accepts_well_formed_records(self):
        records = [
            {"title": "A", "points": 10, "url": "/a"},
            {"title": "B", "points": 5, "url": "/b"},
        ]
        report = validate_records(records, SCHEMA)
        assert report.ok is True
        assert report.record_count == 2

    def test_rejects_empty_result(self):
        report = validate_records([], SCHEMA)
        assert report.ok is False
        assert "empty" in report.reason.lower()

    def test_rejects_missing_required_field(self):
        report = validate_records([{"title": "A"}], SCHEMA)  # no url
        assert report.ok is False
        assert "url" in report.reason

    def test_optional_field_may_be_absent(self):
        report = validate_records([{"title": "A", "url": "/a"}], SCHEMA)
        assert report.ok is True

    def test_rejects_wrong_type(self):
        report = validate_records([{"title": "A", "points": "lots", "url": "/a"}], SCHEMA)
        assert report.ok is False

    def test_flags_low_field_coverage(self):
        # 'points' present in only 1 of 10 records -> suspicious extraction
        records = [{"title": f"t{i}", "url": f"/{i}"} for i in range(9)]
        records.append({"title": "t9", "points": 1, "url": "/9"})
        report = validate_records(records, SCHEMA, min_coverage=0.5)
        assert report.ok is True  # points is optional, so coverage is informational
        assert report.coverage["points"] < 0.5

    def test_build_validator_produces_pydantic_model(self):
        Model = build_validator(SCHEMA)
        obj = Model(title="A", url="/a")
        assert obj.title == "A"
