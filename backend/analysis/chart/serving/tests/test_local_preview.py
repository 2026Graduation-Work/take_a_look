import pytest
from serving.auth import service_headers
from serving.local_preview import require_local_url


def test_local_preview_never_targets_remote_project():
    require_local_url("http://127.0.0.1:54321")
    require_local_url("http://localhost:54321")
    with pytest.raises(ValueError, match="loopback"):
        require_local_url("https://project.supabase.co")


def test_local_jwt_uses_service_role_bearer_but_hosted_secret_does_not():
    jwt = "eyJheader.eyJpayload.signature"
    assert service_headers(jwt) == {"apikey": jwt, "Authorization": f"Bearer {jwt}"}
    assert service_headers("sb_secret_example") == {"apikey": "sb_secret_example"}
