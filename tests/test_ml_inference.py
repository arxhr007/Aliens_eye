import json

import pytest

from aliens_eye.core.features import FEATURE_SCHEMA
from aliens_eye.ml.inference import MLModel, ModelError


def make_model_dict(coef_value=1.0, intercept=0.0):
    n = len(FEATURE_SCHEMA)
    return {
        "version": "test",
        "feature_schema": list(FEATURE_SCHEMA),
        "mean": [0.0] * n,
        "scale": [1.0] * n,
        "coef": [coef_value] * n,
        "intercept": intercept,
    }


def test_predict_proba_zero_features_is_half():
    model = MLModel.from_dict(make_model_dict())
    assert abs(model.predict_proba({}) - 0.5) < 1e-9


def test_predict_proba_monotonic():
    model = MLModel.from_dict(make_model_dict())
    low = model.predict_proba({FEATURE_SCHEMA[0]: 0.0})
    high = model.predict_proba({FEATURE_SCHEMA[0]: 5.0})
    assert high > low


def test_predict_proba_in_unit_interval():
    model = MLModel.from_dict(make_model_dict(coef_value=100.0))
    p = model.predict_proba({name: 100.0 for name in FEATURE_SCHEMA})
    assert 0.0 <= p <= 1.0


def test_schema_mismatch_rejected():
    data = make_model_dict()
    data["feature_schema"] = data["feature_schema"][:-1] + ["bogus_feature"]
    with pytest.raises(ModelError):
        MLModel.from_dict(data)


def test_length_mismatch_rejected():
    data = make_model_dict()
    data["coef"] = data["coef"][:-1]
    with pytest.raises(ModelError):
        MLModel.from_dict(data)


def test_zero_scale_rejected():
    data = make_model_dict()
    data["scale"][0] = 0.0
    with pytest.raises(ModelError):
        MLModel.from_dict(data)


def test_missing_key_rejected():
    data = make_model_dict()
    del data["intercept"]
    with pytest.raises(ModelError):
        MLModel.from_dict(data)


def test_load_invalid_json_rejected(tmp_path):
    path = tmp_path / "model.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ModelError):
        MLModel.load(path)


def test_load_packaged_model():
    model = MLModel.load()
    assert model.feature_schema == FEATURE_SCHEMA
    p = model.predict_proba({name: 0.0 for name in FEATURE_SCHEMA})
    assert 0.0 <= p <= 1.0


def test_load_custom_path(tmp_path):
    path = tmp_path / "model.json"
    path.write_text(json.dumps(make_model_dict()), encoding="utf-8")
    model = MLModel.load(path)
    assert model.version == "test"
