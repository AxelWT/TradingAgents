from supabase import create_client, Client
from app.config import get_settings

_client: Client | None = None
_admin_client: Client | None = None


def get_supabase_client() -> Client:
    global _client
    if _client is None:
        settings = get_settings()
        _client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _client


def get_supabase_admin_client() -> Client:
    global _admin_client
    if _admin_client is None:
        settings = get_settings()
        service_key = settings.SUPABASE_SERVICE_KEY or settings.SUPABASE_KEY
        _admin_client = create_client(settings.SUPABASE_URL, service_key)
    return _admin_client
