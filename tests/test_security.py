from app.core.config import Settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hashing_round_trip() -> None:
    hashed = hash_password("a-very-secure-password", rounds=4)

    assert hashed != "a-very-secure-password"
    assert verify_password("a-very-secure-password", hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_and_refresh_tokens_have_expected_type() -> None:
    settings = Settings(jwt_secret_key="test-secret-key-with-at-least-32-chars")

    access = create_access_token(subject="user-id", settings=settings)
    refresh = create_refresh_token(subject="user-id", settings=settings)

    assert (
        decode_token(access, settings=settings, expected_type="access")["sub"]
        == "user-id"
    )
    assert (
        decode_token(refresh, settings=settings, expected_type="refresh")["sub"]
        == "user-id"
    )
