
import json
import os
from src.utils.logger import Log

class TokenService:
    def __init__(self, db_file="user_tokens.json"):
        self.db_file = db_file
        self._ensure_db()

    def _ensure_db(self):
        if not os.path.exists(self.db_file):
            with open(self.db_file, 'w') as f:
                json.dump({}, f)

    def _load_db(self):
        try:
            with open(self.db_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            Log.error(f"[TokenService] ❌ Failed to load DB: {e}")
            return {}

    def _save_db(self, data):
        try:
            with open(self.db_file, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            Log.error(f"[TokenService] ❌ Failed to save DB: {e}")

    def save_user_tokens(self, email, tokens):
        """
        Saves tokens for a user.
        tokens: dict containing access_token, refresh_token, etc.
        """
        db = self._load_db()
        db[email] = tokens
        self._save_db(db)
        Log.info(f"[TokenService] 💾 Saved tokens for user: {email}")

    def get_user_tokens(self, email):
        """Retrieves tokens for a specific user."""
        db = self._load_db()
        return db.get(email)

    def delete_user_tokens(self, email):
        """
        Deletes tokens for a specific user (disconnect Drive).
        Returns True if tokens were found and deleted, False otherwise.
        """
        db = self._load_db()
        if email in db:
            del db[email]
            self._save_db(db)
            Log.info(f"[TokenService] 🗑️ Deleted tokens for user: {email}")
            return True
        else:
            Log.warning(f"[TokenService] ⚠️ No tokens found for user: {email}")
            return False

token_service = TokenService()
