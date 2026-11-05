from __future__ import annotations

from typing import Any

_REASONS = {
    "http_gone": "The site returned HTTP 404/410; the profile was not observed.",
    "http_error": "An HTTP error cannot confirm that a profile exists.",
    "bot_wall": "The page contains challenge, blocking, or error-page signals.",
    "same_as_control": "The response resembles the site's response to a random control username.",
    "control_unavailable": "The control response was unavailable; it did not verify this result.",
    "control_disabled": "The control comparison was disabled.",
    "fetch_error": "The page could not be fetched; account existence is unknown.",
    "extraction_error": "Page analysis failed; account existence is unknown.",
    "site_deadline": "The per-site deadline expired; account existence is unknown.",
    "worker_error": "The site check failed; account existence is unknown.",
    "browser_unavailable": "Browser fallback failed; the HTTP detector verdict was retained.",
}

_SIGNALS = {
    "http_200": "HTTP 200 response",
    "meta_has_username": "Username in page metadata",
    "og_type_profile": "OpenGraph profile markup",
    "has_json_ld_person": "Person structured data",
    "username_in_canonical": "Username in canonical URL",
    "error_keyword_count": "Error wording",
    "has_auth_pattern": "Authentication-related URL",
    "profile_section_count": "Profile-like page sections",
}


def detector_evidence(detection, source: str = "http") -> dict[str, Any]:
    return {
        **detection.diagnostics,
        "status": detection.status,
        "confidence": detection.confidence,
        "heuristic_score": detection.score,
        "probability": detection.probability,
        "source": source,
    }


def build_explanation(
    status: str,
    confidence: int,
    *,
    code: int = 0,
    detector: dict | None = None,
    initial: dict | None = None,
    checks: dict | None = None,
    features: dict | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    checks = checks or {
        "http": {"outcome": "unavailable", "code": code, "source": "http"},
        "bot_wall": {"outcome": "not_run"},
        "control": {"outcome": "not_run"},
        "browser": {"outcome": "not_run"},
    }
    reasons = [reason] if reason else []
    control = checks.get("control", {}).get("outcome")
    if control in {"unavailable", "disabled"}:
        reasons.append(f"control_{control}")
    if checks.get("browser", {}).get("outcome") == "unavailable":
        reasons.append("browser_unavailable")
    summary = _REASONS.get(reason, f"The detector reported {status}; this is not proof of identity.")
    if reasons:
        summary = " ".join(dict.fromkeys([summary, *(_REASONS[r] for r in reasons if r in _REASONS)]))
    return {
        "schema_version": 1,
        "summary": summary,
        "reason_codes": reasons,
        "detector": detector,
        "initial_detector": initial,
        "checks": checks,
        "final": {"status": status, "confidence": confidence, "override_reason": reason},
        "observed_signals": [
            {"name": key, "description": label, "value": features[key]}
            for key, label in _SIGNALS.items() if features and features.get(key, 0) > 0
        ],
    }


def explanation_lines(info: dict[str, Any]) -> list[str]:
    evidence = (info.get("ai_analysis") or {}).get("explanation")
    if not isinstance(evidence, dict) or evidence.get("schema_version") != 1:
        return ["Detailed evidence was not recorded."]
    lines = [str(evidence.get("summary", ""))]
    detector = evidence.get("detector")
    if isinstance(detector, dict):
        lines.append(
            f"Detector ({detector.get('source', 'unknown')}): {detector.get('status')}; "
            f"blended probability={detector.get('probability')}; "
            f"Found > {detector.get('found_threshold')}, Not Found < {detector.get('not_found_threshold')}."
        )
        lines.append(
            f"Heuristic probability={detector.get('heuristic_probability')}; "
            f"ML probability={detector.get('ml_probability')}; ML weight={detector.get('ml_weight')}; "
            f"model={detector.get('model_version')}."
        )
    for name, check in evidence.get("checks", {}).items():
        if isinstance(check, dict):
            detail = f" (HTTP {check['code']})" if "code" in check else ""
            lines.append(f"{name.replace('_', ' ').capitalize()}: {check.get('outcome', 'not_run')}{detail}.")
    lines.append("Confidence is a display score, not a probability of ownership.")
    return lines
