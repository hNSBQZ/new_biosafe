from biosafe.auth import decode_admin_token, hash_password, issue_admin_token, verify_password


def test_password_hash_roundtrip_and_rejects_wrong_password() -> None:
    stored = hash_password("secret", salt=b"0123456789abcdef", iterations=1000)

    assert verify_password("secret", stored) is True
    assert verify_password("wrong", stored) is False
    assert verify_password("secret", "invalid") is False


def test_admin_token_roundtrip_and_rejects_tampering() -> None:
    token = issue_admin_token("admin", "token-secret", 60)

    payload = decode_admin_token(token, "token-secret")
    assert payload is not None
    assert payload.username == "admin"
    assert decode_admin_token(token + "x", "token-secret") is None
    assert decode_admin_token(token, "other-secret") is None
