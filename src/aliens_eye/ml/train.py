"""Train the detection model from a labeled feature CSV.

Requires the ``train`` extra: ``pip install aliens-eye[train]``.

The CSV must have one column per FEATURE_SCHEMA entry plus a final ``label``
column (1 = profile exists, 0 = does not exist). Output is a JSON file with
StandardScaler statistics and LogisticRegression coefficients consumed by
:mod:`aliens_eye.ml.inference`.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from aliens_eye import __version__
from aliens_eye.core.features import FEATURE_SCHEMA


def load_dataset(path: Path) -> tuple[list[list[float]], list[int]]:
    X: list[list[float]] = []
    y: list[int] = []
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in FEATURE_SCHEMA + ["label"] if name not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"Dataset is missing columns: {missing}")
        for row in reader:
            X.append([float(row[name]) for name in FEATURE_SCHEMA])
            y.append(int(float(row["label"])))
    if not X:
        raise ValueError("Dataset is empty")
    return X, y


def train_model(dataset_path: Path, output_path: Path, logger=None) -> dict:
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import cross_val_score
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError(
            "Training requires scikit-learn. Install with: pip install aliens-eye[train]"
        ) from exc

    X_list, y_list = load_dataset(dataset_path)
    X = np.array(X_list, dtype=float)
    y = np.array(y_list, dtype=int)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)

    n_splits = min(5, int(min((y == 0).sum(), (y == 1).sum())))
    cv_accuracy = None
    if n_splits >= 2:
        scores = cross_val_score(clf, X_scaled, y, cv=n_splits)
        cv_accuracy = float(scores.mean())

    clf.fit(X_scaled, y)

    scale = np.where(scaler.scale_ == 0, 1.0, scaler.scale_)
    model = {
        "version": __version__,
        "feature_schema": FEATURE_SCHEMA,
        "mean": scaler.mean_.tolist(),
        "scale": scale.tolist(),
        "coef": clf.coef_[0].tolist(),
        "intercept": float(clf.intercept_[0]),
        "training": {
            "samples": int(len(y)),
            "positives": int((y == 1).sum()),
            "negatives": int((y == 0).sum()),
            "cv_accuracy": cv_accuracy,
        },
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    if logger:
        logger.info(
            "Model trained on %d samples (cv accuracy: %s) -> %s",
            len(y),
            f"{cv_accuracy:.3f}" if cv_accuracy is not None else "n/a",
            output_path,
        )
    return model
