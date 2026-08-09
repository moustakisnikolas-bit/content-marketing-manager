import uuid

import jwt
import pytest

from content_studio.config import get_settings
from content_studio.modules.publishing.exceptions import InvalidOAuthState
from content_studio.modules.publishing.oauth_state import create_oauth_state, decode_oauth_state


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
