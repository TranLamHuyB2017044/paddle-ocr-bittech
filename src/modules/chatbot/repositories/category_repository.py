import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from bson import ObjectId
from src.core.database.base_repository import BaseRepository
from src.shared.utils.logger import Log

def slugify(text: str) -> str:
    """
    Generate URL-friendly slug from Vietnamese / Unicode text.
    Ví dụ: 'Luật Đất đai 2024' -> 'luat-dat-dai-2024'
    """
    if not text:
        return ""
    text = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])
    # Thay thế d/D gạch ngang tiếng Việt (đ, Đ)
    text = text.replace('đ', 'd').replace('Đ', 'd')
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s_-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    return text.strip('-')

class KnowledgeCategoryRepository(BaseRepository):
    def __init__(self):
        super().__init__("knowledge_categories")
        self._ensure_indexes()

    def _ensure_indexes(self):
        try:
            # Partial unique index: cho phép trùng slug nếu category trước đó đã bị soft deleted
            self.collection.create_index(
                [("workspace_id", 1), ("slug", 1)],
                unique=True,
                partialFilterExpression={"is_deleted": False}
            )
            self.collection.create_index([("workspace_id", 1), ("is_deleted", 1)])
        except Exception as e:
            Log.debug(f"[CategoryRepo] Index initialization info: {e}")

    def find_active_by_name(self, workspace_id: str, name: str, exclude_id: Optional[str] = None) -> Optional[dict]:
        clean_name = name.strip()
        query: Dict[str, Any] = {
            "workspace_id": str(workspace_id),
            "name": {"$regex": f"^{re.escape(clean_name)}$", "$options": "i"},
            "is_deleted": False
        }
        if exclude_id:
            try:
                query["_id"] = {"$ne": ObjectId(exclude_id)}
            except Exception:
                pass
        doc = self.collection.find_one(query)
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    def create_category(self, workspace_id: str, name: str, description: Optional[str] = None,
                        icon: Optional[str] = None, created_by: Optional[str] = None) -> Optional[dict]:
        clean_name = name.strip() if name else ""
        if not clean_name:
            raise ValueError("Tên category không được để trống")

        slug = slugify(clean_name)
        if not slug:
            raise ValueError("Tên category không hợp lệ để tạo slug")

        # Check existing active category with this name or slug in workspace/chatbot
        existing_name = self.find_active_by_name(workspace_id, clean_name)
        if existing_name:
            raise ValueError(f"Category với tên '{clean_name}' đã tồn tại trong chatbot này")

        existing_slug = self.find_active_by_slug(workspace_id, slug)
        if existing_slug:
            raise ValueError(f"Category với slug '{slug}' đã tồn tại trong chatbot này")

        now = datetime.now(timezone.utc)
        data = {
            "workspace_id": str(workspace_id),
            "name": clean_name,
            "slug": slug,
            "description": description.strip() if description else None,
            "icon": icon.strip() if icon else None,
            "is_deleted": False,
            "deleted_at": None,
            "deleted_by": None,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now
        }
        res = self.collection.insert_one(data)
        data["_id"] = str(res.inserted_id)
        return data

    def list_by_workspace(self, workspace_id: str, include_deleted: bool = False) -> List[dict]:
        query = {"workspace_id": str(workspace_id)}
        if not include_deleted:
            query["is_deleted"] = False
        cursor = self.collection.find(query).sort("created_at", -1)
        results = []
        for doc in cursor:
            doc["_id"] = str(doc["_id"])
            results.append(doc)
        return results

    def find_active_by_slug(self, workspace_id: str, slug: str, exclude_id: Optional[str] = None) -> Optional[dict]:
        query: Dict[str, Any] = {
            "workspace_id": str(workspace_id),
            "slug": slug,
            "is_deleted": False
        }
        if exclude_id:
            try:
                query["_id"] = {"$ne": ObjectId(exclude_id)}
            except Exception:
                pass
        doc = self.collection.find_one(query)
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    def find_by_slug_any_status(self, workspace_id: str, slug: str) -> Optional[dict]:
        doc = self.collection.find_one({
            "workspace_id": str(workspace_id),
            "slug": slug
        })
        if doc:
            doc["_id"] = str(doc["_id"])
        return doc

    def update_category(self, workspace_id: str, slug: str, name: Optional[str] = None,
                        description: Optional[str] = None, icon: Optional[str] = None) -> Optional[dict]:
        cat = self.find_active_by_slug(workspace_id, slug)
        if not cat:
            return None

        update_fields: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        if name is not None:
            clean_name = name.strip()
            if not clean_name:
                raise ValueError("Tên category không được để trống")

            # Check duplicate name with other active categories
            existing_name = self.find_active_by_name(workspace_id, clean_name, exclude_id=cat["_id"])
            if existing_name:
                raise ValueError(f"Category với tên '{clean_name}' đã tồn tại trong chatbot này")

            # Slug đi theo category
            new_slug = slugify(clean_name)
            if not new_slug:
                raise ValueError("Tên category không hợp lệ để tạo slug")

            existing_slug = self.find_active_by_slug(workspace_id, new_slug, exclude_id=cat["_id"])
            if existing_slug:
                raise ValueError(f"Category với slug '{new_slug}' đã tồn tại trong chatbot này")

            update_fields["name"] = clean_name
            update_fields["slug"] = new_slug

        if description is not None:
            update_fields["description"] = description.strip() if description else None
        if icon is not None:
            update_fields["icon"] = icon.strip() if icon else None

        res = self.collection.find_one_and_update(
            {"_id": ObjectId(cat["_id"]), "is_deleted": False},
            {"$set": update_fields},
            return_document=True
        )
        if res:
            res["_id"] = str(res["_id"])
            if "slug" in update_fields and update_fields["slug"] != slug:
                res["_old_slug"] = slug
        return res

    def soft_delete(self, workspace_id: str, slug: str, deleted_by: Optional[str] = None) -> Optional[dict]:
        now = datetime.now(timezone.utc)
        res = self.collection.find_one_and_update(
            {"workspace_id": str(workspace_id), "slug": slug, "is_deleted": False},
            {"$set": {
                "is_deleted": True,
                "deleted_at": now,
                "deleted_by": deleted_by,
                "updated_at": now
            }},
            return_document=True
        )
        if res:
            res["_id"] = str(res["_id"])
        return res

    def restore(self, workspace_id: str, slug: str) -> Optional[dict]:
        # Kiểm tra xem có slug nào đang active trùng hay không
        active = self.find_active_by_slug(workspace_id, slug)
        if active:
            raise ValueError(f"Không thể khôi phục vì category với slug '{slug}' đang tồn tại")

        now = datetime.now(timezone.utc)
        res = self.collection.find_one_and_update(
            {"workspace_id": str(workspace_id), "slug": slug, "is_deleted": True},
            {"$set": {
                "is_deleted": False,
                "deleted_at": None,
                "deleted_by": None,
                "updated_at": now
            }},
            return_document=True
        )
        if res:
            res["_id"] = str(res["_id"])
        return res

category_repo = KnowledgeCategoryRepository()
