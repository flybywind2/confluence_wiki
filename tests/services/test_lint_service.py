from app.core.config import Settings
from app.demo_seed import seed_demo_content


def test_demo_seed_creates_lint_report_with_health_sections(tmp_path, sample_settings_dict):
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    seed_demo_content(settings)

    lint_path = tmp_path / "wiki" / "global" / "knowledge" / "lint" / "report.md"
    lint_text = lint_path.read_text(encoding="utf-8")

    assert "# Lint Report" in lint_text
    assert "## Missing Summaries" in lint_text
    assert "## Unmapped Raw Pages" in lint_text
    assert "## Orphans" in lint_text
    assert "## History Coverage" in lint_text
