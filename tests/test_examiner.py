"""Examiner tests: presets -> expected k, and both parsers recover the expected fields."""
import json
import os
from pathlib import Path

import pytest

from doc_generator import DOC_FILES, PRESETS, generate_set
from examiner import CHECKABLE_RULES, FATAL_RULES, RULES, TemplateParser, examine, extract_text, get_parser

OUT = Path("docs/generated")


@pytest.fixture(scope="module", autouse=True)
def fixtures():
    for p in PRESETS:
        generate_set(p, OUT)


def _compare(parsed: dict, expected: dict, doc_type: str) -> list[str]:
    bad = []
    for k, v in expected.items():
        got = parsed.get(k)
        if k == "freight":
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if got is None or abs(float(got) - float(v)) > 1e-6:
                bad.append(f"{doc_type}.{k}: {got!r} != {v!r}")
        elif isinstance(v, str) and (got is None or str(got).strip().lower() != v.strip().lower()):
            bad.append(f"{doc_type}.{k}: {got!r} != {v!r}")
        elif isinstance(v, bool) and got is not v:
            bad.append(f"{doc_type}.{k}: {got!r} != {v!r}")
    return bad


def test_rule_table_has_19_rules_with_articles():
    assert len(RULES) == 19
    assert all(code and art.startswith("UCP600-") for code, art, _, _ in RULES.values())
    assert "R15" in CHECKABLE_RULES and "R19" in CHECKABLE_RULES and "R17" in FATAL_RULES


@pytest.mark.parametrize("preset,k,codes", [
    ("clean", 0, set()),
    ("discrepant", 2, {"QTY_INCONSISTENT", "LATE_SHIPMENT"}),
    ("fraudulent", 1, {"CONTAINER_MISMATCH"}),
])
def test_presets_with_template_parser(preset, k, codes):
    res = examine(OUT / preset, TemplateParser())
    assert res["k"] == k and {d["code"] for d in res["discrepancies"]} == codes
    assert res["fatal"] == []
    if preset == "fraudulent":
        d = res["discrepancies"][0]
        assert d["field"] == "container_number" and d["found"] == "MSKU8811207" and d["expected"] == "TCLU7702410"


@pytest.mark.parametrize("preset", PRESETS)
def test_template_parser_recovers_every_expected_field(preset):
    expected = json.loads((OUT / preset / "expected_fields.json").read_text())
    for doc_type, fname in DOC_FILES.items():
        parsed = TemplateParser().parse(doc_type, extract_text(OUT / preset / fname))
        assert _compare(parsed, expected[doc_type], doc_type) == []


@pytest.mark.live
@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="no GROQ_API_KEY")
def test_groq_parser_recovers_expected_fields_on_discrepant():
    expected = json.loads((OUT / "discrepant" / "expected_fields.json").read_text())
    parser = get_parser("groq")
    problems = []
    for doc_type, fname in DOC_FILES.items():
        parsed = parser.parse(doc_type, extract_text(OUT / "discrepant" / fname))
        assert "_parser_fallback" not in parsed, parsed.get("_parser_fallback")
        problems += _compare(parsed, expected[doc_type], doc_type)
    assert problems == [], problems
    res = examine(OUT / "discrepant", parser)
    assert res["k"] == 2
