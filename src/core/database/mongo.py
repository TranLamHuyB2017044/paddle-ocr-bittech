
import logging
import os
from pymongo.mongo_client import MongoClient
from src.core.config import MONGODB_URI

logger = logging.getLogger(__name__)

uri = MONGODB_URI
DB_NAME = os.getenv("MONGODB_DB_NAME", "ocr_bittech_db")

client = None


def init_mongo_client(ping: bool = False):
    """
    Initialize or re-initialize MongoClient instance.
    """
    global client
    try:
        client = MongoClient(
            uri,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=10000,
            socketTimeoutMS=20000,
        )
        if ping:
            client.admin.command('ping')
            print("Pinged your deployment. You successfully connected to MongoDB!")
    except Exception as e:
        print(f"MongoDB connection warning: {e}")
    return client


def get_client() -> MongoClient:
    """
    Get the current MongoClient instance, initializing it if necessary.
    """
    global client
    if client is None:
        init_mongo_client()
    return client


def get_database():
    """
    Get the default application MongoDB database.
    """
    return get_client()[DB_NAME]


def close_mongo_client():
    """
    Safely close current MongoClient instance.
    """
    global client
    if client is not None:
        try:
            client.close()
        except Exception as e:
            logger.warning(f"Could not close MongoClient: {e}")
        finally:
            client = None


# Initial client initialization (e.g. for standalone scripts or master process)
init_mongo_client(ping=False)
