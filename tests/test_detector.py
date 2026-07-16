from aliens_eye.core.detector import (
    FOUND_THRESHOLD,
    NOT_FOUND_THRESHOLD,
    Detector,
    _sigmoid,
)


def make_found_features():
    return {
        "http_200": 1.0,
        "has_username_in_path": 1.0,
        "positive_keyword_count": 6.0,
        "profile_section_count": 3.0,
        "meta_has_username": 1.0,
        "img_count": 10.0,
    }


def make_not_found_features():
    return {
        "http_404": 1.0,
        "error_keyword_count": 5.0,
        "error_section_count": 2.0,
        "meta_error_keyword_count": 2.0,
    }


def test_heuristic_found():
    detector = Detector()
    result = detector.predict(make_found_features())
    assert result.status == "Found"
    assert result.method == "heuristic"
    assert result.probability is not None
    assert result.probability > FOUND_THRESHOLD
    assert 0 < result.confidence <= 99


def test_heuristic_not_found():
    detector = Detector()
    result = detector.predict(make_not_found_features())
    assert result.status == "Not Found"
    assert result.probability < NOT_FOUND_THRESHOLD


def test_heuristic_maybe_on_empty():
    detector = Detector()
    result = detector.predict({})
    assert result.status == "Maybe"


def test_predict_sets_heuristic_score_feature():
    detector = Detector()
    features = make_found_features()
    detector.predict(features)
    assert "heuristic_score" in features


def test_status_boundaries():
    detector = Detector()
    status, _ = detector._status_from_probability(FOUND_THRESHOLD + 0.01)
    assert status == "Found"
    status, _ = detector._status_from_probability(NOT_FOUND_THRESHOLD - 0.01)
    assert status == "Not Found"
    status, _ = detector._status_from_probability(0.5)
    assert status == "Maybe"


def test_confidence_scales_with_probability():
    detector = Detector()
    _, low = detector._status_from_probability(FOUND_THRESHOLD + 0.01)
    _, high = detector._status_from_probability(0.99)
    assert high > low


def test_load_model_missing_falls_back(logger, tmp_path):
    detector = Detector()
    detector.load_model(logger, tmp_path / "missing.json")
    assert detector.model is None
    result = detector.predict(make_found_features())
    assert result.method == "heuristic"


def test_load_packaged_model_blends(logger):
    detector = Detector()
    detector.load_model(logger)
    assert detector.model is not None
    result = detector.predict(make_found_features())
    assert result.method == "ml+heuristic"
    assert 0.0 <= result.probability <= 1.0


def test_redirect_off_username_path_penalized():
    # Same base features, but one landed on a generic page after a redirect
    # (visitor/login/geo-block-wall pattern) -> should score lower.
    detector = Detector()
    base = {"http_200": 1.0, "positive_keyword_count": 3.0}
    on_profile = {**base, "has_username_in_path": 1.0, "redirect_count": 1.0}
    bounced = {**base, "has_username_in_path": 0.0, "redirect_count": 1.0}
    assert detector.predict(on_profile).score > detector.predict(bounced).score


def test_redirect_without_leaving_username_path_not_penalized():
    # A redirect that still lands on a URL containing the username (e.g. a
    # canonical-URL normalization) should not be penalized.
    detector = Detector()
    base = {"http_200": 1.0, "has_username_in_path": 1.0}
    assert detector.predict({**base, "redirect_count": 0.0}).score == detector.predict(
        {**base, "redirect_count": 1.0}
    ).score


def test_sigmoid_bounds():
    assert _sigmoid(1000) == 1.0
    assert _sigmoid(-1000) < 1e-20
    assert abs(_sigmoid(0) - 0.5) < 1e-9
