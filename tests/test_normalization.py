from parser_app import runtime


def test_url_normalization_removes_tracking_and_fragment() -> None:
    assert (
        runtime.normalize_url("/catalog/item/?utm_source=test&page=2#details", "https://example.com/base/")
        == "https://example.com/catalog/item/?page=2"
    )


def test_model_normalization_keeps_real_model_codes() -> None:
    assert runtime.normalize_model("DAB-65.178TSS.TO") == "DAB-65.178TSS.TO"
    assert runtime.normalize_model("WFbli 5041") == "WFbli 5041"


def test_model_normalization_keeps_visual_latin_letters_in_darina_codes() -> None:
    assert runtime.normalize_model("Darina 6Р ЕI 3302 B, черный") == "6P EI 3302 B"
    assert runtime.normalize_model("Darina 6Р9 ЕI 528 B, черный") == "6P9 EI 528 B"
    assert runtime.normalize_model("Винный холодильник") == "Винный холодильник"


def test_replacement_rules_and_markers() -> None:
    assert runtime.prepare_rule_model(
        "ABC-123 Black", {"model_replace_rules": "Black|\nABC|XYZ"}
    ) == "XYZ-123"
    assert runtime.extract_between_markers("prefix [ABC-123] suffix", "[", "]") == "ABC-123"


def test_blocked_page_detection() -> None:
    assert runtime.looks_blocked_or_empty("<html><body>empty</body></html>") is True
    assert runtime.looks_blocked_or_empty(
        '<a href="/catalog/a-123">A</a><a href="/catalog/b-456">B</a>'
    ) is False


def test_schedule_normalization() -> None:
    assert runtime.normalize_schedule_type("weekly") == "weekly"
    assert runtime.normalize_schedule_type("unknown") == "daily"
    assert runtime.normalize_weekday("8") == 6
