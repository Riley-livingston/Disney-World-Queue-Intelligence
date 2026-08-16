"""Explainable wait-time baseline vs a naive same-hour last-week predictor."""

from __future__ import annotations

import argparse
import json

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

from wdw.config import METRICS_JSON, MODEL_PATH, MODELS_DIR, ensure_data_dirs
from wdw.typical import typical_day_curve  # noqa: F401
from wdw.warehouse import load_hourly

FEATURE_COLS = [
    "attraction_key",
    "park_key",
    "hour",
    "weekday",
    "month",
    "is_weekend",
    "is_holiday",
    "early_entry",
]
CATEGORICAL = ["attraction_key", "park_key"]
NUMERIC = ["hour", "weekday", "month", "is_weekend", "is_holiday", "early_entry"]
TARGET = "posted_wait_median"


def _prepare(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["observed_at"] = pd.to_datetime(work["observed_at"], errors="coerce")
    work = work.dropna(subset=[TARGET, "observed_at"])
    work = work.loc[work[TARGET] >= 0]
    for col in ("is_holiday", "early_entry", "is_weekend", "hour", "weekday", "month"):
        if col not in work.columns:
            work[col] = 0
        work[col] = pd.to_numeric(work[col], errors="coerce").fillna(0).astype(int)
    work["attraction_key"] = work["attraction_key"].astype(str)
    work["park_key"] = work["park_key"].astype(str)
    return work.sort_values("observed_at").reset_index(drop=True)


def time_split(frame: pd.DataFrame, test_fraction: float = 0.2) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = np.sort(frame["park_date"].dropna().unique())
    if len(dates) < 10:
        cut = max(1, int(len(frame) * (1 - test_fraction)))
        return frame.iloc[:cut], frame.iloc[cut:]
    cut_date = dates[int(len(dates) * (1 - test_fraction))]
    train = frame.loc[frame["park_date"] < cut_date]
    test = frame.loc[frame["park_date"] >= cut_date]
    if train.empty or test.empty:
        cut = int(len(frame) * (1 - test_fraction))
        return frame.iloc[:cut], frame.iloc[cut:]
    return train, test


def naive_same_hour_last_week(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    """Predict the median posted wait for the same attraction/hour/weekday from history.

    This is the honest baseline a park ops analyst would try first: 'what does
    this ride usually do at 2pm on Saturdays?'
    """
    lookup = (
        train.groupby(["attraction_key", "hour", "weekday"], observed=True)[TARGET]
        .median()
        .rename("naive")
    )
    merged = test.merge(lookup, on=["attraction_key", "hour", "weekday"], how="left")
    global_median = train[TARGET].median()
    hour_median = train.groupby("hour")[TARGET].median()
    merged["naive"] = merged["naive"].fillna(merged["hour"].map(hour_median)).fillna(global_median)
    return merged["naive"].to_numpy()


def build_pipeline() -> Pipeline:
    transformer = ColumnTransformer(
        transformers=[
            (
                "cat",
                OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
                CATEGORICAL,
            ),
            ("num", "passthrough", NUMERIC),
        ]
    )
    model = HistGradientBoostingRegressor(
        max_depth=4,
        learning_rate=0.08,
        max_iter=200,
        l2_regularization=0.1,
        random_state=42,
    )
    return Pipeline([("prep", transformer), ("model", model)])


def train_model(frame: pd.DataFrame | None = None) -> dict:
    ensure_data_dirs()
    data = _prepare(frame if frame is not None else load_hourly())
    train, test = time_split(data)
    pipeline = build_pipeline()
    pipeline.fit(train[FEATURE_COLS], train[TARGET])
    pred = pipeline.predict(test[FEATURE_COLS])
    naive = naive_same_hour_last_week(train, test)
    y = test[TARGET].to_numpy()

    mae = float(mean_absolute_error(y, pred))
    naive_mae = float(mean_absolute_error(y, naive))
    rmse = float(np.sqrt(mean_squared_error(y, pred)))

    # Permutation importance on a sample so training stays fast.
    sample = test.sample(min(len(test), 4000), random_state=42)
    importance = permutation_importance(
        pipeline,
        sample[FEATURE_COLS],
        sample[TARGET],
        n_repeats=5,
        random_state=42,
        scoring="neg_mean_absolute_error",
    )
    importances = {
        col: float(val)
        for col, val in zip(FEATURE_COLS, importance.importances_mean, strict=True)
    }

    residuals = test.assign(predicted=pred, naive=naive, residual=y - pred)
    by_attraction = (
        pd.DataFrame(
            [
                {
                    "attraction_name": name,
                    "mae": float(mean_absolute_error(group[TARGET], group["predicted"])),
                    "naive_mae": float(mean_absolute_error(group[TARGET], group["naive"])),
                    "bias": float(group["residual"].mean()),
                    "n": int(len(group)),
                }
                for name, group in residuals.groupby("attraction_name", observed=True)
            ]
        )
    )

    metrics = {
        "n_train": int(len(train)),
        "n_test": int(len(test)),
        "train_start": str(train["park_date"].min()),
        "train_end": str(train["park_date"].max()),
        "test_start": str(test["park_date"].min()),
        "test_end": str(test["park_date"].max()),
        "mae_minutes": round(mae, 2),
        "naive_mae_minutes": round(naive_mae, 2),
        "rmse_minutes": round(rmse, 2),
        "mae_lift_vs_naive": round(naive_mae - mae, 2),
        "feature_importance": importances,
        "by_attraction": by_attraction.to_dict(orient="records"),
        "notes": (
            "This is an explainable baseline, not a claim to beat Disney's own wait system. "
            "Features are hour, weekday, month, holiday, early entry, attraction, and park."
        ),
    }
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": pipeline, "features": FEATURE_COLS}, MODEL_PATH)
    METRICS_JSON.write_text(json.dumps(metrics, indent=2, default=str), encoding="utf-8")
    return metrics


def load_trained() -> dict | None:
    if not MODEL_PATH.exists():
        return None
    return joblib.load(MODEL_PATH)


def expected_wait(live_rows: pd.DataFrame, hourly: pd.DataFrame | None = None) -> pd.DataFrame:
    """Score mapped live attractions with the trained model, else historical hour medians."""
    history = _prepare(hourly if hourly is not None else load_hourly())
    now = pd.Timestamp.now(tz="America/New_York")
    mapped = live_rows.dropna(subset=["entity_id"]).copy()
    key_by_entity = (
        history.dropna(subset=["live_entity_id"])
        .drop_duplicates("live_entity_id")
        .set_index("live_entity_id")["attraction_key"]
        .to_dict()
    )
    name_by_entity = (
        history.dropna(subset=["live_entity_id"])
        .drop_duplicates("live_entity_id")
        .set_index("live_entity_id")["attraction_name"]
        .to_dict()
    )
    mapped["attraction_key"] = mapped["entity_id"].map(key_by_entity)
    mapped = mapped.dropna(subset=["attraction_key"])
    if mapped.empty:
        return mapped
    mapped["attraction_name"] = mapped["entity_id"].map(name_by_entity)
    mapped["hour"] = now.hour
    mapped["weekday"] = now.dayofweek
    mapped["month"] = now.month
    mapped["is_weekend"] = int(now.dayofweek >= 5)
    mapped["is_holiday"] = 0
    mapped["early_entry"] = 0

    trained = load_trained()
    if trained is not None:
        mapped["expected_wait"] = trained["pipeline"].predict(mapped[FEATURE_COLS])
    else:
        lookup = (
            history.groupby(["attraction_key", "hour", "weekday"])[TARGET]
            .median()
            .rename("expected_wait")
        )
        mapped = mapped.merge(lookup, on=["attraction_key", "hour", "weekday"], how="left")
        mapped["expected_wait"] = mapped["expected_wait"].fillna(
            history.groupby("attraction_key")[TARGET].median().reindex(mapped["attraction_key"]).to_numpy()
        )
    mapped["delta_vs_expected"] = mapped["standby_wait"] - mapped["expected_wait"]
    return mapped


def posted_vs_actual(hourly: pd.DataFrame) -> pd.DataFrame:
    work = hourly.dropna(subset=["posted_wait_median", "actual_wait_median"]).copy()
    work = work.loc[(work["posted_n"] > 0) & (work["actual_n"] > 0)]
    summary = (
        work.groupby(["attraction_key", "attraction_name", "park_name"], observed=True)
        .agg(
            posted_median=("posted_wait_median", "median"),
            actual_median=("actual_wait_median", "median"),
            bias_median=("posted_minus_actual", "median"),
            bias_mean=("posted_minus_actual", "mean"),
            n=("posted_minus_actual", "size"),
        )
        .reset_index()
        .sort_values("bias_mean", ascending=False)
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the wait-time baseline model.")
    parser.parse_args(argv)
    metrics = train_model()
    print(json.dumps({k: metrics[k] for k in ("n_train", "n_test", "mae_minutes", "naive_mae_minutes", "mae_lift_vs_naive")}, indent=2))
    print(f"Wrote {MODEL_PATH} and {METRICS_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
