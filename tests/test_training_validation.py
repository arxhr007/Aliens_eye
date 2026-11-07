import csv
import math

import pytest

from aliens_eye.core.features import FEATURE_SCHEMA
from aliens_eye.ml.inference import MLModel, ModelError
from aliens_eye.ml.train import load_dataset, train_model, training_folds

pytest.importorskip("sklearn")


def test_canonical_aliases_are_excluded_from_new_training():
    from aliens_eye.core.scanner import load_sites_data
    from aliens_eye.core.sites import training_group
    from aliens_eye.ml.collect import load_selfcheck_data, training_sites

    templates = load_sites_data()
    train = training_sites(templates, "train")
    holdout = load_selfcheck_data("holdout")
    assert "chess.com" not in train
    assert not {training_group(s, templates.get(s)) for s in train} & {
        training_group(s, templates.get(s)) for s in holdout
    }


def test_new_split_assignment_keeps_aliases_together():
    from aliens_eye.eval.groundtruth import GroundTruthEntry, assign_splits

    entries = {s: GroundTruthEntry(s, ["alice"], "curated") for s in ("first", "alias")}
    templates = {"first": "https://example.org/{}", "alias": "http://www.example.org/{}/"}
    assert assign_splits(entries, {"first"}, {"alias"}, site_templates=templates) == {
        "first": "holdout", "alias": "holdout",
    }


def test_training_rows_keep_group_metadata(tmp_path):
    from aliens_eye.ml.collect import write_rows

    path = tmp_path / "rows.csv"
    write_rows(path, [[0.0] * len(FEATURE_SCHEMA) + [1.0]], metadata=[{
        "site": "example", "site_group": "example.org", "label_source": "curated", "split": "train",
    }])
    with path.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["site_group"] == "example.org"
    assert row["split"] == "train"
    with pytest.raises(ValueError, match="schemas"):
        write_rows(path, [[0.0] * len(FEATURE_SCHEMA) + [0.0]], append=True)


def dataset(path, *, grouped=True, invalid=None):
    fields = FEATURE_SCHEMA + ["label"] + (["site_group"] if grouped else [])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for group in range(6):
            for label in (0, 1):
                row = dict.fromkeys(FEATURE_SCHEMA, 0.0)
                row.update(http_200=label, http_404=1 - label, content_length=1000 + 500 * label)
                row["label"] = label
                if grouped:
                    row["site_group"] = f"site-{group}"
                if invalid:
                    row.update(invalid)
                writer.writerow(row)


@pytest.mark.parametrize("invalid", [{"http_200": "nan"}, {"http_200": "inf"}, {"label": 0.5}, {"label": 2}])
def test_dataset_rejects_nonfinite_features_and_nonbinary_labels(tmp_path, invalid):
    path = tmp_path / "data.csv"
    dataset(path, invalid=invalid)
    with pytest.raises(ValueError):
        load_dataset(path)


def test_group_folds_never_share_a_site():
    import numpy as np

    groups = np.array([f"site-{i // 2}" for i in range(12)])
    y = np.array([i % 2 for i in range(12)])
    folds = training_folds(np.zeros((12, 2)), y, groups)
    for train, test in folds:
        assert not set(groups[train]) & set(groups[test])
        assert set(y[train]) == {0, 1}
    assert sorted(i for _, test in folds for i in test) == list(range(12))


def test_grouped_training_records_validation_and_fold_local_scaling(tmp_path, monkeypatch):
    from sklearn.preprocessing import StandardScaler

    path = tmp_path / "data.csv"
    dataset(path)
    sizes = []
    original = StandardScaler.fit

    def fit(self, X, y=None, **kwargs):
        sizes.append(len(X))
        return original(self, X, y, **kwargs)

    monkeypatch.setattr(StandardScaler, "fit", fit)
    result = train_model(path, tmp_path / "model.json")
    assert result["training"]["validation"] == "site-grouped"
    assert result["training"]["calibration"] == "nested-out-of-fold"
    assert result["training"]["site_groups"] == 6
    assert any(size < 12 for size in sizes)
    assert 12 in sizes
    assert 0 < result["thresholds"]["not_found"] < result["thresholds"]["found"] < 1


def test_legacy_training_is_explicit_about_missing_site_groups(tmp_path):
    path = tmp_path / "legacy.csv"
    dataset(path, grouped=False)
    result = train_model(path, tmp_path / "model.json")
    assert result["training"]["validation"] == "row-stratified-legacy"
    assert result["training"]["site_groups"] is None


@pytest.mark.parametrize("field,value", [("intercept", math.nan), ("ml_weight", 2), ("scale", [-1] * len(FEATURE_SCHEMA))])
def test_model_rejects_invalid_numeric_parameters(field, value):
    data = {
        "feature_schema": FEATURE_SCHEMA,
        "mean": [0] * len(FEATURE_SCHEMA),
        "scale": [1] * len(FEATURE_SCHEMA),
        "coef": [0] * len(FEATURE_SCHEMA),
        "intercept": 0,
    }
    data[field] = value
    with pytest.raises(ModelError):
        MLModel.from_dict(data)
