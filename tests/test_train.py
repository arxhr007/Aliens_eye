import csv

import pytest

from aliens_eye.core.features import FEATURE_SCHEMA
from aliens_eye.ml.train import load_dataset

sklearn = pytest.importorskip("sklearn")

from aliens_eye.ml.inference import MLModel  # noqa: E402
from aliens_eye.ml.train import train_model  # noqa: E402


def write_dataset(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(FEATURE_SCHEMA + ["label"])
        writer.writerows(rows)


def make_rows(n=40):
    rows = []
    for i in range(n):
        label = i % 2
        row = [0.0] * len(FEATURE_SCHEMA)
        # Separate classes on the http_200 / http_404 features with noise from i.
        row[FEATURE_SCHEMA.index("http_200")] = float(label)
        row[FEATURE_SCHEMA.index("http_404")] = float(1 - label)
        row[FEATURE_SCHEMA.index("content_length")] = 1000.0 * label + i
        rows.append(row + [float(label)])
    return rows


def test_load_dataset_validates_columns(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        load_dataset(path)


def test_load_dataset_empty(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text(",".join(FEATURE_SCHEMA + ["label"]) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_dataset(path)


def test_train_and_inference_roundtrip(tmp_path):
    data_path = tmp_path / "data.csv"
    model_path = tmp_path / "model.json"
    write_dataset(data_path, make_rows())

    info = train_model(data_path, model_path)
    assert info["training"]["samples"] == 40
    assert model_path.exists()

    model = MLModel.load(model_path)
    found = model.predict_proba({"http_200": 1.0, "content_length": 1500.0})
    missing = model.predict_proba({"http_404": 1.0})
    assert found > 0.5
    assert missing < 0.5
