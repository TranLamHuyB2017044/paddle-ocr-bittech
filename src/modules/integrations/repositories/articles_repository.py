from datetime import datetime
from typing import Any, Dict, Optional
from src.core.database.base_repository import BaseRepository

class ArticlesRepository(BaseRepository):
    def __init__(self):
        super().__init__("articles")

    def create_article(self, title: str, description: str, content: str, thumbnail: str, 
                       source_url: str, source_domain: str, **kwargs) -> str:
        """
        Save a crawled article to MongoDB.
        """
        data = {
            "title": title,
            "description": description,
            "content": content,
            "thumbnail": thumbnail,
            "source_url": source_url,
            "source_domain": source_domain,
            "crawl_at": datetime.now().isoformat(),
            **kwargs
        }
        return self.create(data)

    def find_by_source_url(self, source_url: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve an article by its source URL.
        """
        return self.find_one({"source_url": source_url})

# Global instance
articles_repo = ArticlesRepository()
