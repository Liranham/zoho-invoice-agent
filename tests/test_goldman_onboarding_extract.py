"""Tests for the onboarding extraction prompt + schema."""

from __future__ import annotations

from unittest.mock import MagicMock

from goldman.onboarding.extract import (
    EXTRACTION_SCHEMA,
    build_prompt,
    extract_from_dump,
)


def test_extraction_schema_has_expected_top_level_keys():
    props = EXTRACTION_SCHEMA["properties"]
    assert "tax_registrations" in props
    assert "bank_accounts" in props
    assert "vendors" in props
    assert "clients" in props
    assert "facts" in props
    assert "entity_metadata" in props


def test_build_prompt_includes_entity_context():
    system, user = build_prompt(
        entity_slug="amzg",
        entity_legal_name="AMZ Expert Global Limited",
        entity_jurisdiction="HK",
        dump="UK VAT registered as GB123456789 since 2024-03-01.",
    )

    assert "AMZ Expert Global Limited" in system
    assert "HK" in system
    assert "GB123456789" in user


def test_extract_from_dump_calls_llm_and_returns_validated_struct():
    fake_llm = MagicMock()
    fake_llm.extract_with_tool.return_value = {
        "tax_registrations": [
            {"tax_type": "vat", "jurisdiction": "GB",
             "registration_number": "GB123456789",
             "effective_from": "2024-03-01",
             "filing_cadence": "quarterly"}
        ],
        "bank_accounts": [],
        "vendors": [],
        "clients": [],
        "facts": [],
        "entity_metadata": {},
    }

    result = extract_from_dump(
        llm=fake_llm,
        entity_slug="amzg",
        entity_legal_name="AMZ Expert Global Limited",
        entity_jurisdiction="HK",
        dump="UK VAT GB123456789 since 2024-03-01, files quarterly.",
    )

    assert len(result["tax_registrations"]) == 1
    assert result["tax_registrations"][0]["jurisdiction"] == "GB"
    # The LLM call used the right tool name
    call_kwargs = fake_llm.extract_with_tool.call_args.kwargs
    assert call_kwargs["tool_name"] == "submit_extraction"
