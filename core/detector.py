from dataclasses import dataclass
from typing import Dict

from .features import vectorize_features


@dataclass
class DetectionResult:
    status: str
    confidence: int
    score: float
    method: str
    probability: float | None


class Detector:
    """Heuristic-only detection based on structured response features."""

    def load_model(self, logger) -> None:
        logger.debug("ML model loading is disabled; using heuristics only.")

    def predict(self, features: Dict[str, float]) -> DetectionResult:
        heuristic_score = self._heuristic_score(features)
        status, confidence = self._status_from_score(heuristic_score)
        return DetectionResult(
            status=status,
            confidence=confidence,
            score=heuristic_score,
            method="heuristic",
            probability=None,
        )

    def _heuristic_score(self, features: Dict[str, float]) -> float:
        score = 0.0
        score -= features.get("error_keyword_count", 0.0) * 2
        score += features.get("positive_keyword_count", 0.0) * 1.5

        if features.get("http_200", 0.0) > 0:
            score += 5
        if features.get("http_404", 0.0) > 0:
            score -= 10
        if features.get("http_5xx", 0.0) > 0:
            score -= 3
        if features.get("http_3xx", 0.0) > 0:
            if features.get("has_auth_pattern", 0.0) > 0:
                score -= 3
            if features.get("has_username_in_path", 0.0) > 0:
                score += 2

        if features.get("has_username_in_path", 0.0) > 0 and features.get("is_homepage", 0.0) == 0:
            score += 3
        if features.get("is_homepage", 0.0) > 0 and features.get("http_200", 0.0) > 0:
            score -= 5

        score -= features.get("error_section_count", 0.0) * 3
        score += features.get("profile_section_count", 0.0) * 4

        if features.get("img_count", 0.0) > 5:
            score += 2
        if features.get("form_count", 0.0) > 0 and features.get("input_count", 0.0) > 2:
            score -= 2

        if features.get("meta_has_username", 0.0) > 0:
            score += 5
        score -= features.get("meta_error_keyword_count", 0.0) * 3
        score += features.get("meta_positive_keyword_count", 0.0) * 2

        score += features.get("fingerprint_match_found", 0.0) * 2
        score -= features.get("fingerprint_match_not_found", 0.0) * 2

        return score

    def _status_from_score(self, score: float) -> tuple[str, int]:
        if score > 10:
            confidence = 95
        elif score > 6:
            confidence = 85
        elif score > 2:
            confidence = 70
        elif score < -10:
            confidence = 95
        elif score < -6:
            confidence = 85
        elif score < -2:
            confidence = 70
        else:
            confidence = 55

        if score > 8:
            return "Found", confidence
        if score < -8:
            return "Not Found", confidence
        return "Maybe", confidence
