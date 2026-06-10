from aliens_eye.core.variations import generate_username_variations


def test_basic_returns_only_original():
    assert generate_username_variations("alice", "basic") == ["alice"]


def test_intermediate_adds_variations():
    variations = generate_username_variations("alice", "intermediate")
    assert "alice" in variations
    assert "alice_" in variations
    assert "alice123" in variations
    assert len(variations) > 5


def test_advanced_adds_prefixes_and_suffixes():
    variations = generate_username_variations("alice", "advanced")
    assert "realalice" in variations
    assert "alice_official" in variations
    assert len(variations) > 100


def test_no_duplicates():
    for level in ("basic", "intermediate", "advanced"):
        variations = generate_username_variations("alice", level)
        assert len(variations) == len(set(variations))


def test_original_always_first():
    for level in ("basic", "intermediate", "advanced"):
        assert generate_username_variations("alice", level)[0] == "alice"
