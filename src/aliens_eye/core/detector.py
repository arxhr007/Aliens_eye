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


# FALLBACK blend weight and probability thresholds, used only when no model is
# loaded or when a model file omits these fields. A loaded model overrides all
# three (see Detector.predict and MLModel.from_dict).
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

    Detection results use three states:

        - Found
        - Maybe
        - Not Found

    Challenge / anti-bot responses are treated as uncertain evidence.
    They should not be enough by themselves to produce a Found result.
    """

    def __init__(self) -> None:
        self.model = None

    def load_model(self, logger, model_path: Path | None = None) -> None:
        from aliens_eye.ml.inference import MLModel, ModelError

        try:
            self.model = MLModel.load(model_path)

            logger.debug(
                "Loaded ML model (version %s)",
                self.model.version,
            )

        except (FileNotFoundError, ModelError, OSError) as exc:
            self.model = None

            logger.debug(
                "ML model unavailable, using heuristics only: %s",
                exc,
            )

    def judges(
        self,
        features: dict[str, float],
    ) -> tuple[float, float, float | None]:
        """Run the heuristic and optional ML judges.

        Returns:

            (
                heuristic_score,
                heuristic_probability,
                ml_probability,
            )

        ml_probability is None when no model is loaded.

        The heuristic score is stored in the feature dictionary because the
        ML model can use it as an input feature.
        """

        heuristic_score = self._heuristic_score(features)

        heuristic_prob = _sigmoid(
            heuristic_score / HEURISTIC_SIGMOID_SCALE
        )

        features["heuristic_score"] = heuristic_score

        ml_prob = (
            self.model.predict_proba(features)
            if self.model is not None
            else None
        )

        return (
            heuristic_score,
            heuristic_prob,
            ml_prob,
        )

    def predict(
        self,
        features: dict[str, float],
    ) -> DetectionResult:
        heuristic_score, heuristic_prob, ml_prob = self.judges(
            features
        )

        if ml_prob is not None:
            ml_w = getattr(
                self.model,
                "ml_weight",
                ML_WEIGHT,
            )

            probability = (
                ml_w * ml_prob
                + (1.0 - ml_w) * heuristic_prob
            )

            method = "ml+heuristic"

        else:
            probability = heuristic_prob
            method = "heuristic"

        found_thr = (
            getattr(
                self.model,
                "found_threshold",
                FOUND_THRESHOLD,
            )
            if self.model
            else FOUND_THRESHOLD
        )

        not_found_thr = (
            getattr(
                self.model,
                "not_found_threshold",
                NOT_FOUND_THRESHOLD,
            )
            if self.model
            else NOT_FOUND_THRESHOLD
        )

        status, confidence = self._status_from_probability(
            probability,
            found_thr,
            not_found_thr,
        )

        # A challenge/block page means the scanner was unable to reliably
        # inspect the profile. Never let challenge evidence alone become
        # a confirmed Found result.
        if self._is_challenge(features):
            status = "Maybe"

            # Challenge results should not advertise high certainty.
            confidence = min(confidence, 59)

        return DetectionResult(
            status=status,
            confidence=confidence,
            score=heuristic_score,
            method=method,
            probability=round(probability, 4),
        )

    @staticmethod
    def _is_challenge(
        features: dict[str, float],
    ) -> bool:
        """Return True when the response appears to be blocked/challenged."""

        return (
            features.get("challenge_detected", 0.0) > 0
            or features.get("challenge_keyword_count", 0.0) > 0
            or features.get("challenge_meta_keyword_count", 0.0) > 0
            or features.get("challenge_header_count", 0.0) > 0
            or features.get("rate_limited", 0.0) > 0
            or features.get("http_403", 0.0) > 0
            or features.get("http_429", 0.0) > 0
        )

    def _heuristic_score(
        self,
        features: dict[str, float],
    ) -> float:
        score = 0.0

        # ------------------------------------------------------------
        # Error / positive keywords
        # ------------------------------------------------------------

        score -= (
            features.get("error_keyword_count", 0.0)
            * 2
        )

        score += (
            features.get("positive_keyword_count", 0.0)
            * 1.5
        )

        # ------------------------------------------------------------
        # HTTP status
        # ------------------------------------------------------------

        if features.get("http_200", 0.0) > 0:
            score += 5

        if features.get("http_404", 0.0) > 0:
            score -= 10

        if features.get("http_5xx", 0.0) > 0:
            score -= 3

        # 401 usually indicates authentication is required.
        if features.get("http_401", 0.0) > 0:
            score -= 4

        # 403 means access was denied. It is not evidence that the
        # username exists.
        if features.get("http_403", 0.0) > 0:
            score -= 3

        # 429 means the service is rate-limiting us. This is unknown,
        # not a positive profile match.
        if features.get("http_429", 0.0) > 0:
            score -= 3

        # ------------------------------------------------------------
        # Challenge / anti-bot signals
        # ------------------------------------------------------------

        if features.get("challenge_detected", 0.0) > 0:
            score -= 5

        score -= (
            features.get("challenge_keyword_count", 0.0)
            * 2
        )

        score -= (
            features.get("challenge_meta_keyword_count", 0.0)
            * 2
        )

        score -= (
            features.get("challenge_header_count", 0.0)
            * 2
        )

        if features.get("rate_limited", 0.0) > 0:
            score -= 5

        # ------------------------------------------------------------
        # Redirects
        # ------------------------------------------------------------

        if features.get("http_3xx", 0.0) > 0:
            if features.get("has_auth_pattern", 0.0) > 0:
                score -= 3

            if features.get("has_username_in_path", 0.0) > 0:
                score += 2

        if (
            features.get("has_username_in_path", 0.0) > 0
            and features.get("is_homepage", 0.0) == 0
        ):
            score += 3

        if (
            features.get("is_homepage", 0.0) > 0
            and features.get("http_200", 0.0) > 0
        ):
            score -= 5

        # Redirected away from username URL.
        #
        # This can indicate a login page, visitor page, geo page,
        # bot wall, or other interstitial rather than a profile.
        if (
            features.get("redirect_count", 0.0) > 0
            and features.get("has_username_in_path", 0.0) == 0
        ):
            score -= 4

        # ------------------------------------------------------------
        # Page structure
        # ------------------------------------------------------------

        score -= (
            features.get("error_section_count", 0.0)
            * 3
        )

        score += (
            features.get("profile_section_count", 0.0)
            * 4
        )

        if features.get("img_count", 0.0) > 5:
            score += 2

        if (
            features.get("form_count", 0.0) > 0
            and features.get("input_count", 0.0) > 2
        ):
            score -= 2

        # ------------------------------------------------------------
        # Metadata
        # ------------------------------------------------------------

        if features.get("meta_has_username", 0.0) > 0:
            score += 5

        score -= (
            features.get("meta_error_keyword_count", 0.0)
            * 3
        )

        score += (
            features.get("meta_positive_keyword_count", 0.0)
            * 2
        )

        # ------------------------------------------------------------
        # Fingerprints
        # ------------------------------------------------------------

        score += (
            features.get("fingerprint_match_found", 0.0)
            * 2
        )

        score -= (
            features.get("fingerprint_match_not_found", 0.0)
            * 2
        )

        # ------------------------------------------------------------
        # Structured-data signals
        # ------------------------------------------------------------

        score += (
            features.get("og_type_profile", 0.0)
            * 6
        )

        score += (
            features.get("has_json_ld_person", 0.0)
            * 5
        )

        score += (
            features.get("username_in_canonical", 0.0)
            * 4
        )

        return score

    @staticmethod
    def _status_from_probability(
        probability: float,
        found_threshold: float = FOUND_THRESHOLD,
        not_found_threshold: float = NOT_FOUND_THRESHOLD,
    ) -> tuple[str, int]:
        """Convert probability into Found, Maybe, or Not Found."""

        probability = max(
            0.0,
            min(1.0, probability),
        )

        # ------------------------------------------------------------
        # Strong positive evidence
        # ------------------------------------------------------------

        if probability >= found_threshold:
            distance = (
                probability - found_threshold
            ) / max(
                1.0 - found_threshold,
                0.001,
            )

            confidence = int(
                60
                + 39
                * max(
                    0.0,
                    min(1.0, distance),
                )
            )

            return "Found", confidence

        # ------------------------------------------------------------
        # Strong negative evidence
        # ------------------------------------------------------------

        if probability <= not_found_threshold:
            distance = (
                not_found_threshold - probability
            ) / max(
                not_found_threshold,
                0.001,
            )

            confidence = int(
                50
                + 49
                * max(
                    0.0,
                    min(1.0, distance),
                )
            )

            return "Not Found", confidence

        # ------------------------------------------------------------
        # Uncertain
        # ------------------------------------------------------------

        distance = (
            probability - not_found_threshold
        ) / max(
            found_threshold - not_found_threshold,
            0.001,
        )

        confidence = int(
            50
            + 10
            * max(
                0.0,
                min(1.0, distance),
            )
        )

        return "Maybe", confidence