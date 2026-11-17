import asyncio

from backend import matcher

CATALOGUE = [
    {"id": "copper-6", "name": "Фреонопровод медный Д6,35", "unit": "м"},
    {"id": "copper-9", "name": "Фреонопровод медный Д9,52", "unit": "м"},
    {"id": "cable", "name": "Кабель силовой 3х2,5", "unit": "м"},
]


def test_pipeline_volume_and_crew_stay_separate():
    catalogue = [{"id": "pipe", "name": "Трубопровод", "unit": "м"}]
    for text, expected in [
        ("трубопровод 20 5 чел", 20),
        ("трубопровод 20м 5 чел", 20),
        ("трубопровод двадцать метров пять человек", 20),
        ("трубопровод 20 метрво 5 чел", 20),
        ("трубопровод 10км, 5чел.", 10000),
        ("Трубопровод 1,25 километра. Работали впятером", 1250),
        ("трубопровод 250 сантиметров, 5 человек", 2.5),
    ]:
        result = matcher.local_parse(text, catalogue)
        assert result["crew_count"] == 5
        [work] = result["lines"]
        assert (work["item_id"], work["quantity"], work["unit"]) == ("pipe", expected, "м")


def test_compact_piece_unit_and_alternative_quantities():
    catalogue = [{"id": "grille", "name": "Решётка", "unit": "шт."}]
    [work] = matcher.local_parse("поставили решётки 30шт", catalogue)["lines"]
    assert (work["item_id"], work["quantity"]) == ("grille", 30)
    [uncertain] = matcher.local_parse("поставили решётки 20 или 30шт", catalogue)["lines"]
    assert uncertain["quantity"] is None
    spoken = matcher.local_parse(
        "поставили решётки тридцать штук, двадцать пять человек", catalogue
    )
    assert spoken["crew_count"] == 25
    assert spoken["lines"][0]["quantity"] == 30


def test_length_conversion_respects_catalogue_unit_and_dimensions():
    catalogue = [{"id": "pipe", "name": "Трубопровод", "unit": "км"}]
    [work] = matcher.local_parse("трубопровод 2500 м", catalogue)["lines"]
    assert (work["item_id"], work["quantity"], work["unit"]) == ("pipe", 2.5, "км")
    [work] = matcher.local_parse("трубопровод 2500 м²", catalogue)["lines"]
    assert work["item_id"] is None
    assert matcher.extract_crew("монтаж 5 чел.-ч")[1] is None


def test_ai_cannot_replace_a_verifiable_converted_volume(monkeypatch):
    async def complete(_, text, __):
        line = {"item_id": "copper-6", "quantity": 10, "raw": text}
        return {"lines": [line.copy(), line.copy()]}

    monkeypatch.setattr(matcher, "complete", complete)
    result = asyncio.run(
        matcher.parse("фреонопровод 10км 5 чел", CATALOGUE, {"llm_api_key": "test-key"})
    )
    assert result["crew_count"] == 5
    [work] = result["lines"]
    assert work["item_id"] is None
    assert (work["quantity"], work["unit"]) == (10000, "м")


def test_colloquial_report_matches_operation_and_item():
    catalogue = [
        {"id": "remove", "name": "Демонтаж вентиляционной решётки", "unit": "шт."},
        {"id": "install", "name": "Монтаж решётки", "unit": "шт."},
        {"id": "duct", "name": "Монтаж воздуховодов", "unit": "м"},
    ]
    result = matcher.local_parse("сняли 2 вентрешётки потом проложили 12 м вентканала", catalogue)
    assert [(row["item_id"], row["quantity"]) for row in result["lines"]] == [
        ("remove", 2),
        ("duct", 12),
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


def test_report_dimensions_and_units_are_verified_before_offering_a_row(monkeypatch):
    catalogue = [
        {"id": "small", "name": "Монтаж решётки Ø160", "unit": "шт."},
        {"id": "large", "name": "Монтаж решётки Ø1600", "unit": "шт."},
    ]
    [matched] = matcher.local_parse("Монтаж решётки Д 160 2 шт.", catalogue)["lines"]
    assert (matched["item_id"], matched["quantity"]) == ("small", 2)
    [incomplete] = matcher.local_parse("Монтаж решётки Ø160", catalogue)["lines"]
    assert incomplete["quantity"] is None
    [wrong_unit] = matcher.local_parse("Монтаж решётки Ø160 2 м²", catalogue)["lines"]
    assert wrong_unit["item_id"] is None

    async def answer(_, text, __):
        return {
            "crew_count": 6,
            "lines": [{"item_id": "large", "quantity": 5, "unit": "шт.", "raw": text}],
        }

    monkeypatch.setattr(matcher, "complete", answer)
    result = asyncio.run(
        matcher.parse("Монтаж решётки Ø160", catalogue, {"llm_api_key": "test-key"})
    )
    assert result["crew_count"] is None
    assert result["lines"][0]["item_id"] is None and result["lines"][0]["quantity"] is None
