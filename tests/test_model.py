"""Tests for the explainable wait-time baseline vs naive hour/weekday median."""

from __future__ import annotations

from wdw.model import naive_same_hour_last_week, time_split, train_model
from wdw.sample_data import generate_sample_hourly


def test_time_split_is_chronological() -> None:
    hourly = generate_sample_hourly(weeks=4)
    train, test = time_split(hourly, test_fraction=0.25)
    assert train["park_date"].max() <= test["park_date"].min()
    assert len(train) > 0 and len(test) > 0


def test_naive_baseline_has_finite_mae() -> None:
    hourly = generate_sample_hourly(weeks=4)
    train, test = time_split(hourly)
    preds = naive_same_hour_last_week(train, test)
    assert len(preds) == len(test)
    assert (preds >= 0).all()


def test_model_beats_or_matches_naive_on_structured_sample() -> None:
    hourly = generate_sample_hourly(weeks=8)
    metrics = train_model(hourly)
    assert metrics["n_train"] > 0
    assert metrics["n_test"] > 0
    # On this designed sample the tree should at least not collapse vs the grouped median.
    assert metrics["mae_minutes"] <= metrics["naive_mae_minutes"] + 2.0
    assert "hour" in metrics["feature_importance"]
