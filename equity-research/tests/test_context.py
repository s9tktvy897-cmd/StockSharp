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


def test_coverage_counts_distinct_sites_by_kind():
    lines = [
        "### Nieuws",
        "- 2026-10-07: 8-K filed (https://www.sec.gov/Archives/x) and covered (https://www.reuters.com/a)",
        "- 2026-10-06: press release (https://www.businesswire.com/news/1)",
        "- 2026-10-05: same wire, other story (https://www.reuters.com/b)",
        "- 2026-10-04: FDA letter (https://www.fda.gov/news/c)",
        "- 2026-10-03: IR page (https://investor.example.com/q3)",
        "- 2026-10-02: trade press (https://www.fiercebiotech.com/d).",
    ]
    c = context.coverage(lines)
    assert c.bullets == 6
    assert c.pages == 7
    assert c.sites == {"sec.gov", "reuters.com", "businesswire.com", "fda.gov", "investor.example.com",
                       "fiercebiotech.com"}
    assert c.by_kind == {"officieel": 3, "persbericht": 1, "grote media": 1, "overig": 1}


def test_section_reports_coverage_and_warns_when_narrow(tmp_path):
    path = tmp_path / "c.md"
    path.write_text("- 2026-10-07: news (https://www.reuters.com/a)\n", encoding="utf-8")
    text = "\n".join(context.section(context.load(path)))
    assert "1 verschillende site(s)" in text
    assert "Smalle dekking" in text
