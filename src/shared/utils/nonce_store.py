from src.shared.utils.redis_client import redis_conn

class RedisNonceStore:
    def contains(self, nonce: str) -> bool:
        """
        Checks if the nonce exists in Redis (meaning it has already been used).
        """
        # redis_conn.exists returns the number of keys that exist
        return redis_conn.exists(f"auth_nonce:{nonce}") == 1

    def add(self, nonce: str, ttl_seconds: int) -> None:
        """
        Adds the nonce to Redis with a specific time-to-live (TTL).
        """
        redis_conn.setex(f"auth_nonce:{nonce}", ttl_seconds, "1")

nonce_store = RedisNonceStore()
