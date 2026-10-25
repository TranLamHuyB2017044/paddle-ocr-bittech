
import logging
from pymongo.mongo_client import MongoClient
from src.core.config import MONGODB_URI

logger = logging.getLogger(__name__)

uri = MONGODB_URI

# Create a new client and connect to the server
# Pymongo will automatically parse connection options directly from the URI
client = MongoClient(
    uri,
    serverSelectionTimeoutMS=10000,
    connectTimeoutMS=10000,
    socketTimeoutMS=20000,
)

# Send a ping to confirm a successful connection
try:
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(f"MongoDB connection warning: {e}")