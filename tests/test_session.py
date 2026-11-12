from services import session

KEY = b"test-secret"


def test_roundtrip():
    token = session.create_token("User@Example.com", expires_at=2_000_000_000, key=KEY)
    assert session.verify_token("user@example.com", token, key=KEY, now=1_900_000_000)
    assert session.token_expiry(token) == 2_000_000_000


def test_expired():
    token = session.create_token("a@b.com", expires_at=100, key=KEY)
    assert not session.verify_token("a@b.com", token, key=KEY, now=101)


def test_other_user_or_tampered_expiry_rejected():
    token = session.create_token("a@b.com", expires_at=2_000_000_000, key=KEY)
    assert not session.verify_token("evil@b.com", token, key=KEY, now=0)
    sig = token.split(".", 1)[1]
    assert not session.verify_token("a@b.com", f"2100000000.{sig}", key=KEY, now=0)


def test_wrong_key_and_garbage_rejected():
    token = session.create_token("a@b.com", expires_at=2_000_000_000, key=KEY)
    assert not session.verify_token("a@b.com", token, key=b"other", now=0)
    for bad in [None, "", "nodot", "abc.def", "fallback_temporary_dev_secret_key"]:
        assert not session.verify_token("a@b.com", bad, key=KEY, now=0)
