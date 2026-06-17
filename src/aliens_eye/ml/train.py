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
import math
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


def _optimize_thresholds(
    y: list[int], probas: list[float]
) -> tuple[float, float]:
    """Find Found/NotFound thresholds that maximise F1 on the training set."""
    from sklearn.metrics import precision_recall_curve

    prec, rec, thresholds = precision_recall_curve(y, probas)
    denom = prec + rec + 1e-9
    f1 = 2 * prec * rec / denom
    best_idx = int(f1[:-1].argmax())  # last element has no threshold
    found_thr = float(thresholds[best_idx])
    # keep maybe-band ratio ~0.58 of the found threshold
    not_found_thr = round(max(0.05, found_thr * 0.58), 4)
    found_thr = round(found_thr, 4)
    return found_thr, not_found_thr



def train_model(dataset_path: Path, output_path: Path, logger=None) -> dict:
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.model_selection import GridSearchCV, StratifiedKFold
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

    min_class = int(min((y == 0).sum(), (y == 1).sum()))
    n_splits = min(5, max(2, min_class))

    cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
    param_grid = {"C": [0.01, 0.1, 1.0, 10.0, 100.0]}
    base_clf = LogisticRegression(max_iter=2000, class_weight="balanced")

    cv_accuracy = None
    best_params = {"C": 1.0}

    if min_class >= 2:
        search = GridSearchCV(base_clf, param_grid, cv=cv, scoring="f1", n_jobs=-1)
        search.fit(X_scaled, y)
        clf = search.best_estimator_
        best_params = {k: float(v) if isinstance(v, float) else v for k, v in search.best_params_.items()}
        cv_accuracy = float(search.best_score_)
        if logger:
            logger.info("GridSearchCV best: %s  (F1=%.3f)", best_params, cv_accuracy)
    else:
        clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0)
        clf.fit(X_scaled, y)

    # Compute final training-set probabilities for threshold optimisation
    train_probas = clf.predict_proba(X_scaled)[:, 1]
    found_thr, not_found_thr = _optimize_thresholds(y, train_probas)
    if logger:
        logger.info(
            "Threshold optimisation: found=%.4f  not_found=%.4f", found_thr, not_found_thr
        )

    # Blend weight optimisation via OOF (out-of-fold) predictions.
    # heuristic_score is stored as a feature; derive heuristic_prob from it.
    h_idx = FEATURE_SCHEMA.index("heuristic_score")

    def _sig(z: float) -> float:
        return 1.0 / (1.0 + math.exp(-max(-50.0, min(50.0, z / 6.0))))

    oof_h = np.array([_sig(float(row[h_idx])) for row in X_list])
    oof_ml = np.zeros(len(y))
    if min_class >= 2:
        blend_cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=0)
        best_C = best_params.get("C", 1.0)
        for tr_idx, val_idx in blend_cv.split(X_scaled, y):
            fold_clf = LogisticRegression(max_iter=2000, class_weight="balanced", C=best_C)
            fold_clf.fit(X_scaled[tr_idx], y[tr_idx])
            oof_ml[val_idx] = fold_clf.predict_proba(X_scaled[val_idx])[:, 1]

        best_w, best_f1 = 0.4, -1.0
        for i in range(1, 10):
            w = i / 10.0
            blended = w * oof_ml + (1 - w) * oof_h
            preds = (blended > found_thr).astype(int)
            tp = int(((preds == 1) & (y == 1)).sum())
            fp = int(((preds == 1) & (y == 0)).sum())
            fn = int(((preds == 0) & (y == 1)).sum())
            f1_val = 2 * tp / (2 * tp + fp + fn + 1e-9)
            if f1_val > best_f1:
                best_f1, best_w = f1_val, w
        if logger:
            logger.info("Blend search: best ml_weight=%.1f  (OOF F1=%.3f)", best_w, best_f1)
    else:
        best_w = 0.4

    scale = np.where(scaler.scale_ == 0, 1.0, scaler.scale_)
    model = {
        "version": __version__,
        "feature_schema": FEATURE_SCHEMA,
        "mean": scaler.mean_.tolist(),
        "scale": scale.tolist(),
        "coef": clf.coef_[0].tolist(),
        "intercept": float(clf.intercept_[0]),
        "ml_weight": round(best_w, 1),
        "thresholds": {
            "found": found_thr,
            "not_found": not_found_thr,
        },
        "training": {
            "samples": int(len(y)),
            "positives": int((y == 1).sum()),
            "negatives": int((y == 0).sum()),
            "cv_f1": cv_accuracy,
            "best_params": best_params,
        },
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    if logger:
        logger.info(
            "Model trained on %d samples (cv F1: %s) -> %s",
            len(y),
            f"{cv_accuracy:.3f}" if cv_accuracy is not None else "n/a",
            output_path,
        )
    return model
