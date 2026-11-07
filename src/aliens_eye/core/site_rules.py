from __future__ import annotations

import json
import secrets
import string
from dataclasses import replace
from urllib.parse import urljoin

from .control import http_unavailable, page_shape, same_page
from .explain import build_explanation, detector_evidence
from .sites import SiteDefinition


def rule_evidence(site: SiteDefinition, response) -> dict:
    verdict, reason, strength = None, "no_rule_evidence", "none"
    presence = [s for s in site.presence if s in response.content]
    absence = [s for s in site.absence if s in response.content]
    if response.error or http_unavailable(response.status):
        reason = "http_unavailable"
    elif response.status in (404, 410):
        verdict, reason, strength = "Not Found", "http_gone", "explicit"
    elif any(marker in response.content for marker in site.error_markers):
        reason = "site_error"
    elif presence and absence:
        reason = "conflicting_markers"
    elif absence:
        verdict, reason, strength = "Not Found", "absence_marker", "explicit"
    elif not 200 <= response.status < 300:
        reason = "http_unavailable"
    elif presence:
        verdict, reason, strength = "Found", "presence_marker", "explicit"
    elif site.check_type == "message" and site.absence and not site.presence:
        verdict, reason, strength = "Found", "absence_not_seen", "weak"
    elif site.check_type in {"status_code", "response_url"}:
        verdict = "Not Found" if response.status in site.error_codes else "Found"
        reason, strength = "status_rule", "weak"
    return {
        "verdict": verdict, "reason": reason, "strength": strength,
        "presence_matches": presence[:5], "absence_matches": absence[:5],
        "source": site.source, "engine": site.engine,
    }


def json_profile(content: str, username: str, url: str) -> dict | None:
    try:
        data = json.loads(content)
    except (ValueError, RecursionError):
        return None
    pending, visited = [(data, 0)], 0
    while pending and visited < 200:
        item, depth = pending.pop()
        visited += 1
        if depth > 4:
            continue
        if isinstance(item, list):
            pending.extend((value, depth + 1) for value in item[:50])
        elif isinstance(item, dict):
            identifiers = (item.get(k) for k in ("login", "username", "acct", "screen_name", "handle", "uniqueId"))
            if any(isinstance(v, str) and v.lstrip("@").casefold() == username.lstrip("@").casefold() for v in identifiers):
                def text(*keys, record=item):
                    return next((record[k].strip() for k in keys if isinstance(record.get(k), str) and record[k].strip()), "")

                name = text("display_name", "displayName", "name")
                bio = text("bio", "description", "note")
                avatar = text("avatar_url", "avatar", "profile_image_url_https", "profile_image_url")
                return {
                    "name": name[:200], "bio": bio[:500], "avatar": urljoin(url, avatar) if avatar else "",
                    "name_from_profile": bool(name),
                    "field_sources": {
                        key: "site_api" if value else "missing"
                        for key, value in (("name", name), ("bio", bio), ("avatar", avatar))
                    },
                }
            pending.extend((value, depth + 1) for value in item.values() if isinstance(value, (dict, list)))
    return None


def negative_username(site: SiteDefinition, username: str, rng=None) -> str | None:
    lengths = list(dict.fromkeys((16, len(username), 12, 8, 5, 3)))
    choose = rng.choice if rng is not None else secrets.choice
    for length in lengths:
        for alphabet in (string.ascii_lowercase + string.digits, string.ascii_lowercase, string.digits):
            candidate = "".join(choose(alphabet) for _ in range(length))
            if candidate.casefold() != username.casefold() and site.accepts(candidate):
                return candidate
    return None


async def scan_defined_site(scanner, site: SiteDefinition, username, session, rate_limiter) -> dict:
    from .scanner import _looks_like_bot_wall

    profile_url = site.profile_url(username)
    request = site.request(username)
    source = getattr(scanner.sites_data, "sources", {}).get(site.source, {})
    analysis = {
        "site_definition": {
            "fingerprint": site.fingerprint, "source": site.source, "upstream_name": site.upstream_name,
            "source_sha256": source.get("sha256"), "revision": source.get("revision"),
            "tags": list(site.tags), "engine": site.engine, "live_verified": False,
        },
        "request": {"url": request.url, "identity": request.identity, "follow_redirects": request.follow_redirects},
    }
    checks = {
        "http": {"outcome": "not_run", "source": "http"},
        "bot_wall": {"outcome": "not_run", "source": "http"},
        "control": {"outcome": "not_run" if scanner.config.control_check else "disabled"},
        "browser": {"outcome": "disabled", "source": "http"},
    }
    details, initial, reason = None, None, None
    response = None
    status, confidence = "Skipped", 0
    if not site.accepts(username):
        reason = "invalid_site_username"
    else:
        config = replace(scanner.config, request=request)
        response = await scanner.fetch(session, request.url, config, rate_limiter, scanner.logger)
        checks["http"].update(outcome="unavailable" if response.error else "received", code=response.status)
        if response.error:
            status = "Timeout" if response.status == 408 else "Error"
            analysis["error"], reason = response.error, "fetch_error"
        else:
            evidence = rule_evidence(site, response)
            analysis["rule"] = evidence
            checks["site_rule"] = {"outcome": evidence["reason"], "source": site.source}
            content_type = next((v for k, v in response.headers.items() if k.lower() == "content-type"), "")
            is_json = "json" in content_type.lower() or response.content.lstrip().startswith(("{", "["))
            analysis["model_applicable"] = not is_json
            signals, features = {}, {}
            if is_json:
                profile = json_profile(response.content, username, profile_url)
                signals["profile"] = profile or {}
                status, confidence = ("Found", 75) if profile and evidence["verdict"] == "Found" else ("Maybe", 50)
                analysis.update(method="site-rule-json", probability=None, features={}, signals=signals)
                if not profile:
                    reason = "username_not_confirmed"
            else:
                bundle = scanner.extractor.extract(
                    response.content, response.final_url, username, site.name, response.status,
                    response.response_time, response.headers, response.redirect_count,
                )
                signals, features = bundle.signals, bundle.features
                detection = scanner.detector.predict(features)
                details = initial = detector_evidence(detection)
                status, confidence = detection.status, detection.confidence
                analysis.update(
                    method=f"{detection.method}+site-rule", probability=detection.probability,
                    score=detection.score, features=features, signals=signals,
                )
                if evidence["verdict"] == "Found" and evidence["strength"] == "explicit":
                    if status == "Not Found":
                        status, confidence, reason = "Maybe", 50, "rule_model_conflict"
                    else:
                        status, confidence = "Found", max(confidence, 75)
            blocked = _looks_like_bot_wall(signals)
            checks["bot_wall"]["outcome"] = "detected" if blocked else "clear"
            if blocked:
                status, confidence, reason = "Maybe", 50, "bot_wall"
            elif evidence["verdict"] == "Not Found":
                status, confidence = "Not Found", 90
                reason = "http_gone" if response.status in (404, 410) else "rule_absence"
            elif evidence["verdict"] is None and site.check_type is not None:
                status, confidence, reason = "Maybe", 50, evidence["reason"]
            elif status == "Not Found" and http_unavailable(response.status):
                status, confidence, reason = "Maybe", min(confidence, 50), "http_unavailable"

            if status == "Found" and scanner.config.control_check:
                key = site.fingerprint
                cached = key in scanner._defined_controls
                if not cached:
                    name = negative_username(site, username)
                    recorded = getattr(scanner.fetch, "control_for", None)
                    if recorded is not None:
                        candidate = recorded(site.name)
                        name = candidate[0] if candidate and site.accepts(candidate[0]) else None
                    control = None
                    if name:
                        control_request = site.request(name)
                        control = await scanner.fetch(
                            session, control_request.url, replace(scanner.config, request=control_request),
                            rate_limiter, scanner.logger,
                        )
                    scanner._defined_controls[key] = (name, control)
                name, control = scanner._defined_controls[key]
                outcome = "unavailable"
                if control is not None:
                    control_evidence = rule_evidence(site, control)
                    if control_evidence["verdict"] == "Not Found":
                        equal = same_page(
                            page_shape(response.content, response.final_url, username),
                            page_shape(control.content, control.final_url, name),
                        )
                        outcome = "same" if equal else "different"
                    elif control_evidence["verdict"] == "Found":
                        outcome = "same"
                checks["control"].update(outcome=outcome, cached=cached, source="http")
                if outcome != "different":
                    status, confidence = "Maybe", min(confidence, 55)
                    reason = "same_as_control" if outcome == "same" else "control_unavailable"

    analysis["explanation"] = build_explanation(
        status, confidence, code=response.status if response else 0,
        detector=details, initial=initial, checks=checks, features=analysis.get("features"), reason=reason,
    )
    return {
        "site": site.name, "url": profile_url,
        "final_url": profile_url if site.probe_url else (response.final_url if response else profile_url),
        "status": status, "code": response.status if response else 0,
        "response_time": round(response.response_time, 2) if response else 0.0,
        "confidence": confidence, "ai_analysis": analysis,
    }
