import os
import redis
from rq import Queue

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Redis connection
redis_conn = redis.from_url(REDIS_URL)

# RAG Queue
rag_queue = Queue("rag_tasks", connection=redis_conn)
