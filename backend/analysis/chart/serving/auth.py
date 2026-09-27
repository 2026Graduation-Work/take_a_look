"""Supabase request headers for both hosted secret keys and local JWT keys."""


def service_headers(key):
    headers = {"apikey": key}
    # The local CLI exposes a legacy service_role JWT. PostgREST needs this
    # bearer token to apply the service role; hosted sb_secret_ keys do not.
    if key.startswith("eyJ") and key.count(".") == 2:
        headers["Authorization"] = f"Bearer {key}"
    return headers
