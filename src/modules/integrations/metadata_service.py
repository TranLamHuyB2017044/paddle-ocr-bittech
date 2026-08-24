"""
Metadata Extraction Service
Extracts OpenGraph, meta tags, and structured metadata from raw HTML.
"""
from bs4 import BeautifulSoup
from typing import Dict, Any, List


class MetadataService:
    @staticmethod
    def extract_metadata(html: str) -> Dict[str, Any]:
        """
        Extract metadata from HTML string using BeautifulSoup4.
        Returns:
            Dict containing title, description, thumbnail, author, published_at, language, and keywords.
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # 1. Extract Title
        title = None
        # Try og:title first
        og_title = soup.find('meta', property='og:title') or soup.find('meta', attrs={'name': 'og:title'})
        if og_title:
            title = og_title.get('content')
        # Fallback to <title> tag
        if not title:
            title_tag = soup.find('title')
            if title_tag:
                title = title_tag.get_text(strip=True)
        # Ensure it is a clean string or default
        title = title.strip() if title else ""
        
        # 2. Extract Description
        description = None
        # Try og:description first
        og_desc = soup.find('meta', property='og:description') or soup.find('meta', attrs={'name': 'og:description'})
        if og_desc:
            description = og_desc.get('content')
        # Fallback to meta description
        if not description:
            desc_tag = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', property='description')
            if desc_tag:
                description = desc_tag.get('content')
        description = description.strip() if description else ""

        # 3. Extract Thumbnail (og:image)
        thumbnail = None
        og_img = soup.find('meta', property='og:image') or soup.find('meta', attrs={'name': 'og:image'})
        if og_img:
            thumbnail = og_img.get('content')
        thumbnail = thumbnail.strip() if thumbnail else ""

        # 4. Extract Author
        author = None
        author_tag = (
            soup.find('meta', attrs={'name': 'author'}) or 
            soup.find('meta', property='og:author') or
            soup.find('meta', property='article:author') or
            soup.find('meta', attrs={'name': 'article:author'})
        )
        if author_tag:
            author = author_tag.get('content')
        author = author.strip() if author else ""

        # 5. Extract Published Date
        published_at = None
        pub_tag = (
            soup.find('meta', property='article:published_time') or 
            soup.find('meta', attrs={'name': 'publish-date'}) or 
            soup.find('meta', attrs={'name': 'publication-date'}) or
            soup.find('meta', property='og:pubdate') or
            soup.find('meta', attrs={'name': 'pubdate'})
        )
        if pub_tag:
            published_at = pub_tag.get('content')
        published_at = published_at.strip() if published_at else ""

        # 6. Extract Language
        language = None
        lang_tag = soup.find('html')
        if lang_tag and lang_tag.has_attr('lang'):
            language = lang_tag['lang']
        if not language:
            meta_lang = soup.find('meta', attrs={'name': 'language'}) or soup.find('meta', property='og:locale')
            if meta_lang:
                language = meta_lang.get('content')
        language = language.strip() if language else ""

        # 7. Extract Keywords
        keywords: List[str] = []
        keywords_tag = soup.find('meta', attrs={'name': 'keywords'}) or soup.find('meta', attrs={'name': 'keyword'})
        if keywords_tag:
            content = keywords_tag.get('content', '')
            keywords = [k.strip() for k in content.split(',') if k.strip()]
            
        return {
            "title": title,
            "description": description,
            "thumbnail": thumbnail,
            "author": author,
            "published_at": published_at,
            "language": language,
            "keywords": keywords
        }


# Global instance
metadata_service = MetadataService()
