
FEATURE_SCHEMA = [
    "http_200",
    "http_3xx",
    "http_404",
    "http_4xx",
    "http_5xx",
    "has_username_in_path",
    "is_homepage",
    "has_auth_pattern",
    "error_keyword_count",
    "positive_keyword_count",
    "meta_error_keyword_count",
    "meta_positive_keyword_count",
    "profile_section_count",
    "error_section_count",
    "img_count",
    "input_count",
    "form_count",
    "title_has_username",
    "meta_has_username",
    "response_time",
    "content_length",
    "redirect_count",
    "fingerprint_match_found",
    "fingerprint_match_not_found",
    # Structured-data signals (strong profile indicators)
    "og_type_profile",
    "has_json_ld_person",
    "username_in_canonical",
    "link_count",
    "text_length",
    "heuristic_score",
]


def vectorize_features(features: dict[str, float]) -> list[float]:
    """Return features as an ordered list aligned with FEATURE_SCHEMA."""
    return [float(features.get(name, 0.0)) for name in FEATURE_SCHEMA]
