import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from bson import ObjectId
from src.modules.chatbot.repositories import category_repo
from src.modules.ocr.repositories.documents_repository import documents_repo
from src.modules.rag.qdrant_service import qdrant_service

ws_id = "6aa12586ef90b1945a90f71f"
cat_id = "6ad086d4cc6f8008b005120a"
old_slug = "test"
new_slug = "giao-thong"

print(f"Migrating category {cat_id} from '{old_slug}' to '{new_slug}' in workspace {ws_id}...")

# 1. Update category slug
category_repo.collection.update_one(
    {"_id": ObjectId(cat_id)},
    {"$set": {"slug": new_slug}}
)
print(f"Updated category record to slug: {new_slug}")

# 2. Update documents in MongoDB
affected_docs = documents_repo.rename_category(ws_id, old_slug, new_slug)
print(f"Updated {affected_docs} documents in MongoDB")

# 3. Update Qdrant vector payload
try:
    qdrant_service.rename_category(ws_id, old_slug, new_slug)
    print("Updated Qdrant points payload successfully")
except Exception as e:
    print(f"Qdrant payload update notice: {e}")

# 4. Verify
cat = category_repo.find_active_by_slug(ws_id, new_slug)
print("Updated category:", cat)

docs = documents_repo.find_by_workspace(ws_id)
for d in docs:
    print(f"Doc {d.get('_id')}: {d.get('filename')} -> category='{d.get('category')}'")
