import pytest

from equity_research.report import context


def test_context_needs_url_and_date_per_bullet(tmp_path):
    good = tmp_path / "good.md"
    good.write_text("### Nieuws\n- 2026-10-07: earnings date set (https://example.com/a)\n", encoding="utf-8")
    assert context.section(context.load(good))[0].startswith("## 10.")
    bad = tmp_path / "bad.md"
    bad.write_text("- earnings date set, no source\n- 2026-10-07 https://example.com/b\n", encoding="utf-8")
    with pytest.raises(context.ContextError) as error:
        context.load(bad)
    assert "no source" in str(error.value) and "example.com/b" not in str(error.value)


def test_empty_context_is_refused(tmp_path):
    empty = tmp_path / "empty.md"
    empty.write_text("just text\n", encoding="utf-8")
    with pytest.raises(context.ContextError):
        context.load(empty)
