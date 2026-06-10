import math
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DetectionResult:
    status: str
    confidence: int
    score: float
    method: str
    probability: float | None


# Blend weights and probability thresholds, calibrated by out-of-fold grid
# search on the seed dataset and validated against the selfcheck set.
ML_WEIGHT = 0.4
HEURISTIC_WEIGHT = 0.6
HEURISTIC_SIGMOID_SCALE = 6.0
FOUND_THRESHOLD = 0.6
NOT_FOUND_THRESHOLD = 0.35


def _sigmoid(z: float) -> float:
    z = max(-50.0, min(50.0, z))
    return 1.0 / (1.0 + math.exp(-z))


class Detector:
    """Detection combining a trained ML model with heuristic scoring.

    Falls back to heuristics alone when no model is available.
    """

    def __init__(self) -> None:
        self.model = None

    def load_model(self, logger, model_path: Path | None = None) -> None:
        from aliens_eye.ml.inference import MLModel, ModelError

        try:
            self.model = MLModel.load(model_path)
            logger.debug("Loaded ML model (version %s)", self.model.version)
        except (FileNotFoundError, ModelError, OSError) as exc:
            self.model = None
            logger.debug("ML model unavailable, using heuristics only: %s", exc)

    def predict(self, features: dict[str, float]) -> DetectionResult:
        heuristic_score = self._heuristic_score(features)
        heuristic_prob = _sigmoid(heuristic_score / HEURISTIC_SIGMOID_SCALE)
        features["heuristic_score"] = heuristic_score

        if self.model is not None:
            ml_prob = self.model.predict_proba(features)
            probability = ML_WEIGHT * ml_prob + HEURISTIC_WEIGHT * heuristic_prob
            method = "ml+heuristic"
        else:
            probability = heuristic_prob
            method = "heuristic"

        status, confidence = self._status_from_probability(probability)
        return DetectionResult(
            status=status,
            confidence=confidence,
            score=heuristic_score,
            method=method,
            probability=round(probability, 4),
        )

    def _heuristic_score(self, features: dict[str, float]) -> float:
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

    @staticmethod
    def _status_from_probability(probability: float) -> tuple[str, int]:
        if probability > FOUND_THRESHOLD:
            status = "Found"
            distance = (probability - FOUND_THRESHOLD) / (1.0 - FOUND_THRESHOLD)
        elif probability < NOT_FOUND_THRESHOLD:
            status = "Not Found"
            distance = (NOT_FOUND_THRESHOLD - probability) / NOT_FOUND_THRESHOLD
        else:
            status = "Maybe"
            center = (FOUND_THRESHOLD + NOT_FOUND_THRESHOLD) / 2
            half_band = (FOUND_THRESHOLD - NOT_FOUND_THRESHOLD) / 2
            distance = 1.0 - abs(probability - center) / half_band
            return status, int(50 + 20 * max(0.0, min(1.0, distance)))

        confidence = int(60 + 39 * max(0.0, min(1.0, distance)))
        return status, confidence
