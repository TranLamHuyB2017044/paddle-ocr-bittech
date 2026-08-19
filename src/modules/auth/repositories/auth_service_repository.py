from src.core.database.base_repository import BaseRepository

class AuthServiceRepository(BaseRepository):
    def __init__(self):
        super().__init__("auth_services")

auth_service_repo = AuthServiceRepository()
