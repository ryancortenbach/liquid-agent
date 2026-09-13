from app.intake.item_guard import extract_separate_item_requests


def test_extracts_repeated_sell_intents_as_separate_items() -> None:
    assert extract_separate_item_requests(
        "I want to sell my AirPods and then I want to sell my water bottle"
    ) == ["AirPods", "water bottle"]
    assert extract_separate_item_requests("Sell my camera, then list the tripod by Sunday") == [
        "camera",
        "tripod",
    ]
    assert extract_separate_item_requests("Sell my AirPods and my water bottle") == [
        "AirPods",
        "water bottle",
    ]


def test_does_not_split_accessories_from_one_item() -> None:
    assert extract_separate_item_requests("Sell my AirPods with the case and charger") == []
    assert extract_separate_item_requests("Sell my AirPods, then list it for $50") == []
