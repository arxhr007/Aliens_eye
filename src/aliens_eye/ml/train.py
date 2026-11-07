"""Train the detection model from a labeled feature CSV.

Requires the ``train`` extra: ``pip install aliens-eye[train]``.

The CSV must have one column per FEATURE_SCHEMA entry plus a final ``label``
column (1 = profile exists, 0 = does not exist). Output is a JSON file with
StandardScaler statistics and LogisticRegression coefficients consumed by
:mod:`aliens_eye.ml.inference`.
"""

from __future__ import annotations

import csv
import hashlib
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
            features = [float(row[name]) for name in FEATURE_SCHEMA]
            label = float(row["label"])
            if not all(math.isfinite(value) for value in features) or label not in (0, 1):
                raise ValueError("Dataset requires finite features and binary labels")
            X.append(features)
            y.append(int(label))
    if not X:
        raise ValueError("Dataset is empty")
    return X, y


def _optimize_thresholds(
    y: list[int], probas: list[float], max_fpr: float = 0.02,
) -> tuple[float, float]:
    """Find Found/NotFound thresholds that maximise F1 on the training set."""
    from sklearn.metrics import precision_recall_curve

    prec, rec, thresholds = precision_recall_curve(y, probas)
    denom = prec + rec + 1e-9
    f1 = 2 * prec * rec / denom
    import numpy as np

    tp = rec[:-1] * sum(y)
    fp = tp / np.maximum(prec[:-1], 1e-12) - tp
    eligible = (fp / max(1, len(y) - sum(y)) <= max_fpr + 1e-12) & (thresholds > 0.05) & (thresholds < 0.9999)
    best_idx = int(np.where(eligible, f1[:-1], -1).argmax())  # last element has no threshold
    found_thr = math.nextafter(float(thresholds[best_idx]), -math.inf) if eligible.any() else 0.9999
    # keep maybe-band ratio ~0.58 of the found threshold
    not_found_thr = round(max(0.05, found_thr * 0.58), 4)
    return found_thr, not_found_thr



def training_folds(X, y, groups=None, seed=42):
    import numpy as np
    from sklearn.model_selection import StratifiedGroupKFold, StratifiedKFold

    if set(y) != {0, 1}:
        raise ValueError("Training requires both label classes")
    count = min(5, int(min((y == 0).sum(), (y == 1).sum())))
    if groups is not None:
        count = min(count, len(set(groups)))
    for n in range(count, 1, -1):
        cv = (
            StratifiedGroupKFold(n_splits=n, shuffle=True, random_state=seed)
            if groups is not None else StratifiedKFold(n_splits=n, shuffle=True, random_state=seed)
        )
        folds = list(cv.split(X, y, groups))
        if all(len(np.unique(y[train])) == 2 for train, _ in folds):
            return folds
    raise ValueError("Too few independent samples/site groups for cross-validation")


def _fit_pipeline(X, y, groups=None):
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GridSearchCV
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(max_iter=2000, class_weight="balanced")),
    ])
    try:
        folds = training_folds(X, y, groups)
    except ValueError:
        return pipeline.fit(X, y), None
    search = GridSearchCV(
        pipeline, {"classifier__C": [0.01, 0.1, 1.0, 10.0, 100.0]},
        cv=folds, scoring="f1", n_jobs=1,
    )
    search.fit(X, y)
    return search.best_estimator_, float(search.best_score_)


def train_model(dataset_path: Path, output_path: Path, logger=None, *, max_fpr: float = 0.02) -> dict:
    try:
        import numpy as np
        import sklearn
    except ImportError as exc:
        raise RuntimeError(
            "Training requires scikit-learn. Install with: pip install aliens-eye[train]"
        ) from exc

    X_list, y_list = load_dataset(dataset_path)
    X = np.array(X_list, dtype=float)
    y = np.array(y_list, dtype=int)
    if not math.isfinite(max_fpr) or not 0 <= max_fpr <= 1:
        raise ValueError("max_fpr must be between zero and one")
    with Path(dataset_path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        group_key = next((key for key in ("site_group", "site") if key in (reader.fieldnames or [])), None)
        group_values = [row[group_key].strip() for row in reader] if group_key else None
    if group_values is not None and not all(group_values):
        raise ValueError("Site groups must be provided for every training row")
    groups = np.array(group_values) if group_values is not None else None
    if group_key == "site":
        from aliens_eye.core.scanner import load_sites_data
        from aliens_eye.core.sites import training_group

        templates = load_sites_data()
        groups = np.array([training_group(site, templates.get(site)) for site in group_values])
    folds = training_folds(X, y, groups)
    if groups is None and logger:
        logger.warning("Legacy dataset has no site groups; row-stratified validation does not measure unseen-site performance")
    pipeline, cv_accuracy = _fit_pipeline(X, y, groups)
    scaler, clf = pipeline.named_steps["scaler"], pipeline.named_steps["classifier"]
    best_params = {"C": float(clf.C)}

    # Compute final training-set probabilities for threshold optimisation
    train_probas = np.zeros(len(y))
    for tr_idx, val_idx in folds:
        fold, _ = _fit_pipeline(X[tr_idx], y[tr_idx], groups[tr_idx] if groups is not None else None)
        train_probas[val_idx] = fold.predict_proba(X[val_idx])[:, 1]
    found_thr, not_found_thr = _optimize_thresholds(y, train_probas, max_fpr)
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
    oof_ml = train_probas
    best_w, best_f1 = 0.4, -1.0
    for i in range(1, 11):
        w = i / 10.0
        blended = w * oof_ml + (1 - w) * oof_h
        candidate_found, candidate_missing = _optimize_thresholds(y, blended, max_fpr)
        preds = (blended > candidate_found).astype(int)
        tp = int(((preds == 1) & (y == 1)).sum())
        fp = int(((preds == 1) & (y == 0)).sum())
        fn = int(((preds == 0) & (y == 1)).sum())
        f1_val = 2 * tp / (2 * tp + fp + fn + 1e-9)
        if f1_val > best_f1:
            best_f1, best_w = f1_val, w
            found_thr, not_found_thr = candidate_found, candidate_missing
    if logger:
        logger.info("Blend search: best ml_weight=%.1f  (OOF F1=%.3f)", best_w, best_f1)

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
            "validation": "site-grouped" if groups is not None else "row-stratified-legacy",
            "site_groups": len(set(groups)) if groups is not None else None,
            "calibration": "nested-out-of-fold",
            "calibration_f1": best_f1,
            "max_fpr": max_fpr,
            "sklearn_version": sklearn.__version__,
            "dataset_sha256": hashlib.sha256(Path(dataset_path).read_bytes()).hexdigest(),
            "cv_f1_scope": "hyperparameter selection, not an independent test score",
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
