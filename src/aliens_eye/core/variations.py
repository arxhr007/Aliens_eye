import re


def usernames_from_email(email: str) -> list[str]:
    """Derive candidate usernames from an email address.

    Uses the local part plus common separator splits, e.g.
    ``john.doe@x.com`` -> ``john.doe``, ``johndoe``, ``john_doe``, ``john``.
    """
    local = str(email).strip().split("@", 1)[0].lower()
    if not local:
        return []
    parts = [p for p in re.split(r"[._\-+]", local) if p]
    candidates = [local]
    if len(parts) > 1:
        joined = "".join(parts)
        candidates.extend([joined, "_".join(parts), ".".join(parts), parts[0]])
    return list(dict.fromkeys(c for c in candidates if len(c) >= 2))


def usernames_from_name(name: str) -> list[str]:
    """Derive candidate usernames from a real name.

    ``John Doe`` -> ``john``, ``doe``, ``johndoe``, ``john.doe``,
    ``john_doe``, ``jdoe``, ``doej``.
    """
    parts = [p for p in re.split(r"\s+", str(name).strip().lower()) if p.isalnum()]
    if not parts:
        return []
    if len(parts) == 1:
        return [parts[0]] if len(parts[0]) >= 2 else []
    first, last = parts[0], parts[-1]
    candidates = [
        first,
        last,
        f"{first}{last}",
        f"{first}.{last}",
        f"{first}_{last}",
        f"{first[0]}{last}",
        f"{last}{first[0]}",
    ]
    return list(dict.fromkeys(c for c in candidates if len(c) >= 2))


def generate_username_variations(username: str, level: str) -> list[str]:
    """Generate username variations based on scan level."""
    variations = [username]
    if level == "basic":
        return variations

    if level in {"intermediate", "advanced"}:
        variations.extend(
            [
                f"{username}_",
                f"_{username}",
                f"{username}.",
                f".{username}",
                f"{username.replace(' ', '_')}",
                f"{username.replace(' ', '.')}",
                f"{username}1",
                f"{username}123",
                f"{username}007",
                f"{username}098",
                f"{username}x",
                f"__{username}",
                f"__{username}__",
            ]
        )

    if level == "advanced":
        prefixes = [
            "real",
            "official",
            "the",
            "its",
            "im",
            "actual",
            "true",
            "mr",
            "ms",
            "dr",
            "iam",
            "thisis",
            "hey",
            "yo",
            "only",
            "itz",
            "iamthe",
            "theonly",
        ]
        suffixes = [
            "official",
            "real",
            "account",
            "verified",
            "original",
            "tv",
            "here",
            "live",
            "online",
            "page",
            "world",
            "spot",
            "media",
            "inc",
            "group",
            "team",
            "zone",
            "plus",
            "today",
        ]
        for prefix in prefixes:
            variations.append(f"{prefix}{username}")
            variations.append(f"{prefix}_{username}")
            variations.append(f"{prefix}.{username}")
        for suffix in suffixes:
            variations.append(f"{username}{suffix}")
            variations.append(f"{username}_{suffix}")
            variations.append(f"{username}.{suffix}")

    return list(dict.fromkeys(variations))
