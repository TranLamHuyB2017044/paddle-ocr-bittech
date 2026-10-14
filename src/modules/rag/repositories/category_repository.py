# Re-export from chatbot package for backward compatibility
from src.modules.chatbot.repositories.category_repository import (
    slugify,
    KnowledgeCategoryRepository,
    category_repo
)

__all__ = [
    "slugify",
    "KnowledgeCategoryRepository",
    "category_repo"
]
