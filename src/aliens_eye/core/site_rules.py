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


# Keys that hold an account's handle and nothing else: a different value under
# one of them means the answer is about another account.
HANDLE_KEYS = ("login", "username", "acct", "screen_name", "handle", "uniqueId", "user_name", "userName")
# Keys that often hold the handle but may hold a display name instead: a match
# confirms the account, a mismatch says nothing.
LOOSE_HANDLE_KEYS = ("name", "slug")


def _handle(value: str) -> str:
    """A handle as sites compare them: no ``@``, case folded, ``_`` and space alike."""
    return value.strip().lstrip("@").replace("_", " ").casefold()


def _json_records(content: str):
    """Every object in a JSON answer, down to a bounded depth and count."""
    try:
        data = json.loads(content)
    except (ValueError, RecursionError):
        return
    pending, visited = [(data, 0)], 0
    while pending and visited < 200:
        item, depth = pending.pop()
        visited += 1
        if depth > 4:
            continue
        if isinstance(item, list):
            pending.extend((value, depth + 1) for value in item[:50])
        elif isinstance(item, dict):
            yield item
            pending.extend((value, depth + 1) for value in item.values() if isinstance(value, (dict, list)))


def json_names_another_user(content: str, username: str) -> bool:
    """True when a JSON answer carries handles and none of them is ``username``.

    A search or lookup endpoint can answer with the closest account instead of
    the requested one; such an answer matches the site's presence marker while
    describing somebody else.
    """
    wanted, seen = _handle(username), False
    for record in _json_records(content):
        for key in HANDLE_KEYS:
            value = record.get(key)
            if isinstance(value, str) and value.strip():
                if _handle(value) == wanted:
                    return False
                seen = True
    return seen


def json_profile(content: str, username: str, url: str) -> dict | None:
    wanted = _handle(username)
    for item in _json_records(content):
        identifiers = (item.get(k) for k in (*HANDLE_KEYS, *LOOSE_HANDLE_KEYS))
        if not any(isinstance(v, str) and _handle(v) == wanted for v in identifiers):
            continue

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


def _control_is_wall(scanner, control, name: str, site: SiteDefinition) -> bool:
    """Whether the control answer is a challenge or error page rather than the site's own."""
    from .scanner import _looks_like_bot_wall

    try:
        bundle = scanner.extractor.extract(
            control.content, control.final_url, name, site.name, control.status,
            control.response_time, control.headers, control.redirect_count,
        )
    except Exception:  # noqa: BLE001 - an unreadable control verifies nothing
        return True
    return _looks_like_bot_wall(bundle.signals)


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
    # A Found that rests on thin evidence is only kept when the site itself
    # says the control username does not exist; a merely different page is not enough.
    strict_control = False
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
                status, confidence = "Maybe", 50
                if evidence["verdict"] == "Found" and (profile or not json_names_another_user(response.content, username)):
                    # The answer names the username, or the site's own marker for
                    # an existing account matched: either is the site saying yes.
                    # A bare status code is thinner, and needs the control's "no".
                    if profile or evidence["strength"] == "explicit":
                        status, confidence = "Found", 75
                    elif scanner.config.control_check:
                        status, confidence, strict_control = "Found", 65, True
                analysis.update(method="site-rule-json", probability=None, features={}, signals=signals)
                if status != "Found" and not profile:
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
                if (
                    status == "Found" and not is_json and evidence["reason"] == "no_rule_evidence"
                    and scanner.config.control_check
                ):
                    # The rule's markers matched nothing (sites change their
                    # markup), but the page itself reads as a profile.
                    confidence, strict_control = min(confidence, 65), True
                    analysis["method"] = f"{analysis['method']}-stale-rule"
                else:
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

                    def compared() -> str:
                        equal = same_page(
                            page_shape(response.content, response.final_url, username),
                            page_shape(control.content, control.final_url, name),
                        )
                        return "same" if equal else "different"

                    if control_evidence["verdict"] == "Not Found":
                        outcome = compared()
                    elif control_evidence["verdict"] == "Found":
                        outcome = "same"
                    elif (
                        not strict_control
                        and control_evidence["reason"] in {"no_rule_evidence", "conflicting_markers"}
                        and (site.check_type is None or (evidence["verdict"] == "Found" and evidence["strength"] == "explicit"))
                        and not _control_is_wall(scanner, control, name, site)
                    ):
                        # The site answered the control with an ordinary page that
                        # carries none of its markers (a sign-in or search page).
                        # With an explicit marker on the real page, or no rule at
                        # all, the two pages are told apart by what they show.
                        outcome = compared()
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
