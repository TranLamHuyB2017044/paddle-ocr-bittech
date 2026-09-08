from datetime import timezone
from datetime import datetime
from bson import ObjectId
from src.core.database.base_repository import BaseRepository

class WorkspacesRepository(BaseRepository):
    def __init__(self):
        super().__init__("workspaces")

    def create_workspace(self, name, user_id, description="", account_id=None):
        # Convert user_id to ObjectId if it's a string
        uid = ObjectId(user_id) if isinstance(user_id, str) else user_id
        
        workspace = {
            "name": name,
            "user_id": uid,
            "description": description,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        if account_id:
            workspace["account_id"] = ObjectId(account_id) if isinstance(account_id, str) else account_id
        return self.create(workspace)

    def find_by_user(self, user_id):
        # Convert to ObjectId for querying
        uid = ObjectId(user_id) if isinstance(user_id, str) else user_id
        workspaces = list(self.collection.find({"user_id": uid}))
        
        # Format results for JSON response
        for w in workspaces:
            w["_id"] = str(w["_id"])
            if "user_id" in w:
                w["user_id"] = str(w["user_id"])
        return workspaces

    def find_workspace_by_id(self, workspace_id):
        """
        Custom fetch to ensure user_id is stringified for comparison in routes
        """
        workspace = self.find_by_id(workspace_id)
        if workspace:
            workspace["_id"] = str(workspace["_id"])
            if "user_id" in workspace:
                workspace["user_id"] = str(workspace["user_id"])
        return workspace

    def update_workspace(self, workspace_id, name=None, description=None):
        update_data = {"updated_at": datetime.utcnow()}
        if name:
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
            
        return self.update(workspace_id, update_data)

    def delete_workspace(self, workspace_id):
        return self.delete(workspace_id)

    def delete_by_user(self, user_id):
        # Convert to ObjectId for querying
        uid = ObjectId(user_id) if isinstance(user_id, str) else user_id
        result = self.collection.delete_many({"user_id": uid})
        return result.deleted_count

workspaces_repo = WorkspacesRepository()
