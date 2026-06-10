from aliens_eye.core.analyzer import FeatureExtractor


def extract(html, url="https://example.com/torvalds", username="torvalds", code=200):
    extractor = FeatureExtractor()
    return extractor.extract(html, url, username, "example", code, 0.1, {"Server": "nginx"}, 0)


def test_found_page_features(found_html):
    bundle = extract(found_html)
    f = bundle.features
    assert f["http_200"] == 1.0
    assert f["has_username_in_path"] == 1.0
    assert f["title_has_username"] == 1.0
    assert f["meta_has_username"] == 1.0
    assert f["positive_keyword_count"] >= 3
    assert f["img_count"] == 6.0
    assert f["profile_section_count"] >= 1
    assert f["is_homepage"] == 0.0


def test_not_found_page_features(not_found_html):
    bundle = extract(not_found_html, code=404)
    f = bundle.features
    assert f["http_404"] == 1.0
    assert f["http_4xx"] == 1.0
    assert f["error_keyword_count"] >= 3
    assert f["error_section_count"] >= 1
    assert f["form_count"] == 1.0
    assert f["input_count"] == 3.0
    assert f["title_has_username"] == 0.0


def test_homepage_detection():
    bundle = extract("<html></html>", url="https://example.com/")
    assert bundle.features["is_homepage"] == 1.0
    assert bundle.features["has_username_in_path"] == 0.0


def test_auth_pattern_detection():
    bundle = extract("<html></html>", url="https://example.com/login")
    assert bundle.features["has_auth_pattern"] == 1.0


def test_empty_content_safe():
    bundle = extract("", code=500)
    assert bundle.features["http_5xx"] == 1.0
    assert bundle.features["content_length"] == 0.0


def test_fingerprint_fields(found_html):
    bundle = extract(found_html)
    assert "torvalds" in bundle.fingerprint["title"].lower()
    assert bundle.fingerprint["server"] == "nginx"
    assert "img:6" in bundle.fingerprint["dom_signature"]


def test_signals_structure(found_html):
    bundle = extract(found_html)
    assert bundle.signals["site"] == "example"
    assert bundle.signals["url_analysis"]["domain"] == "example.com"
    assert len(bundle.signals["meta_samples"]) <= 5
