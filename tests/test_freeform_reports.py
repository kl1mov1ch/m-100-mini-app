import asyncio

from backend import matcher


CATALOGUE = [
    {"id": "copper-6", "name": "Фреонопровод медный Д6,35", "unit": "м"},
    {"id": "copper-9", "name": "Фреонопровод медный Д9,52", "unit": "м"},
    {"id": "cable", "name": "Кабель силовой 3х2,5", "unit": "м"},
]


def test_misspelled_freon_and_six_mm_copper_keep_independent_quantities():
    result = matcher.local_parse(
        "Положили фрионопровод 120 метров и медную трубу 6ку 100 метров", CATALOGUE
    )
    assert len(result["lines"]) == 2
    first, second = result["lines"]
    assert first["quantity"] == 120 and set(first["candidates"]) == {"copper-6", "copper-9"}
    assert first["item_id"] is None
    assert second["quantity"] == 100 and second["item_id"] == "copper-6"


def test_local_stage_never_calls_ai_and_confident_report_does_not_need_it(monkeypatch):
    async def unexpected(*args, **kwargs):
        raise AssertionError("Однозначную работу не нужно отправлять в AI")

    monkeypatch.setattr(matcher, "complete", unexpected)
    settings = {"llm_api_key": "test-key"}
    uncertain = asyncio.run(
        matcher.parse("фрионопровод 120 метров", CATALOGUE, settings, local_only=True)
    )
    assert uncertain["needs_ai"] and uncertain["lines"][0]["candidates"]
    confident = asyncio.run(
        matcher.parse("Работали впятером, медную трубу 6ку 100 метров", CATALOGUE, settings)
    )
    assert (
        confident["crew_count"] == 5
        and confident["engine"] == "local"
        and len(confident["lines"]) == 1
    )


def test_ai_can_offer_real_candidates_and_cannot_invent_catalogue_ids(monkeypatch):
    calls = []

    async def complete(system, text, settings):
        calls.append(text)
        assert all(position["id"] in system for position in CATALOGUE)
        return {
            "lines": [
                {
                    "item_id": "invented",
                    "unit": "м",
                    "quantity": 120,
                    "raw": text,
                    "candidates": ["invented", "copper-6", "copper-9"],
                }
            ]
        }

    monkeypatch.setattr(matcher, "complete", complete)
    result = asyncio.run(
        matcher.parse("фрионопровод 120 метров", CATALOGUE, {"llm_api_key": "test-key"})
    )
    assert len(calls) == 1 and result["engine"] == "llm"
    assert result["lines"][0]["item_id"] is None
    assert result["lines"][0]["candidates"] == ["copper-6", "copper-9"]
