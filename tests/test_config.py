"""Attraction map covers the four Orlando parks and the TouringPlans headliner set."""

from wdw.config import attractions, park_entity_ids, parks


def test_four_theme_parks() -> None:
    ids = park_entity_ids()
    assert set(ids) == {"magic_kingdom", "epcot", "hollywood_studios", "animal_kingdom"}
    assert parks()["magic_kingdom"]["entity_id"].startswith("75ea578a")


def test_fourteen_headliners_mapped() -> None:
    specs = attractions()
    assert len(specs) == 14
    live = [s for s in specs if s.get("live_entity_id")]
    assert len(live) == 13  # DINOSAUR has closed
    assert {s["key"] for s in specs} >= {"seven_dwarfs_train", "flight_of_passage", "soarin"}
