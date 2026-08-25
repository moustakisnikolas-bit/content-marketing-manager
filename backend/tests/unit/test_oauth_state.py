import uuid

import jwt
import pytest

from content_studio.config import get_settings
from content_studio.modules.publishing.exceptions import InvalidOAuthState
from content_studio.modules.publishing.oauth_state import (
    create_oauth_state,
    create_plugin_pairing_token,
    decode_oauth_state,
    decode_plugin_pairing_token,
)


def test_create_and_decode_round_trips_claims() -> None:
    org_id, workspace_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    state = create_oauth_state(organization_id=org_id, workspace_id=workspace_id, user_id=user_id, platform="facebook")

    claims = decode_oauth_state(state)
    assert claims["organization_id"] == str(org_id)
    assert claims["workspace_id"] == str(workspace_id)
    assert claims["user_id"] == str(user_id)
    assert claims["platform"] == "facebook"


def test_decode_rejects_garbage_token() -> None:
    with pytest.raises(InvalidOAuthState):
        decode_oauth_state("not-a-real-jwt")


def test_decode_rejects_token_of_wrong_type() -> None:
    settings = get_settings()
    other_token = jwt.encode({"type": "access", "sub": "x"}, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(InvalidOAuthState):
        decode_oauth_state(other_token)


def test_plugin_pairing_token_round_trips_claims() -> None:
    org_id, workspace_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token = create_plugin_pairing_token(organization_id=org_id, workspace_id=workspace_id, user_id=user_id)

    claims = decode_plugin_pairing_token(token)
    assert claims["organization_id"] == str(org_id)
    assert claims["workspace_id"] == str(workspace_id)
    assert claims["user_id"] == str(user_id)


def test_plugin_pairing_token_rejects_an_oauth_state_token() -> None:
    # The two token types must not be interchangeable — a leaked/replayed
    # oauth_state token should never be usable to pair a plugin install.
    state = create_oauth_state(
        organization_id=uuid.uuid4(), workspace_id=uuid.uuid4(), user_id=uuid.uuid4(), platform="facebook",
    )
    with pytest.raises(InvalidOAuthState):
        decode_plugin_pairing_token(state)
