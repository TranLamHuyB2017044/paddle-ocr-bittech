from typing import Any, Dict, List, Optional
from bson import ObjectId
from pymongo.results import InsertOneResult, UpdateResult, DeleteResult
from src.core.database.mongo import client
import os

# Get DB Name from Env or Default
DB_NAME = os.getenv("MONGODB_DB_NAME", "ocr_bittech_db")

class BaseRepository:
    def __init__(self, collection_name: str):
        self.db = client[DB_NAME]
        self.collection = self.db[collection_name]

    def find_all(self, filter: Dict = {}) -> List[Dict[str, Any]]:
        """Find all documents matching the filter"""
        cursor = self.collection.find(filter)
        return list(cursor)

    def find_one(self, filter: Dict) -> Optional[Dict[str, Any]]:
        """Find one document matching the filter"""
        return self.collection.find_one(filter)

    def find_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        """Find a document by its ID string"""
        try:
            return self.collection.find_one({"_id": ObjectId(id)})
        except:
            return None

    def create(self, data: Dict) -> str:
        """Insert a new document and return its ID"""
        result: InsertOneResult = self.collection.insert_one(data)
        return str(result.inserted_id)

    def update(self, id: str, data: Dict) -> bool:
        """Update a document by ID"""
        try:
            result: UpdateResult = self.collection.update_one(
                {"_id": ObjectId(id)},
                {"$set": data}
            )
            return result.modified_count > 0
        except:
            return False

    def delete(self, id: str) -> bool:
        """Delete a document by ID"""
        try:
            result: DeleteResult = self.collection.delete_one({"_id": ObjectId(id)})
            return result.deleted_count > 0
        except:
            return False
