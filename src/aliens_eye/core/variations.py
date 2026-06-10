

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
