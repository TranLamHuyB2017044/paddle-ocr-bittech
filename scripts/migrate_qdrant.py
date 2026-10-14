"""
Copy một collection Qdrant từ nguồn (cloud) sang đích (local Docker).

Env:
  SRC_URL, SRC_API_KEY  : Qdrant nguồn
  DST_URL               : Qdrant đích (mặc định http://qdrant:6333)
  DST_API_KEY           : (tuỳ chọn)
Args:
  python scripts/migrate_qdrant.py <collection> [<collection> ...]
"""
import os
import sys
from qdrant_client import QdrantClient
from qdrant_client.http import models

BATCH = 256


def main():
    collections = sys.argv[1:]
    if not collections:
        print("Usage: migrate_qdrant.py <collection> [...]")
        sys.exit(1)

    src = QdrantClient(url=os.environ["SRC_URL"], api_key=os.environ.get("SRC_API_KEY") or None,
                       check_compatibility=False, timeout=120)
    dst = QdrantClient(url=os.getenv("DST_URL", "http://qdrant:6333"),
                       api_key=os.getenv("DST_API_KEY") or None,
                       check_compatibility=False, timeout=120)

    for name in collections:
        info = src.get_collection(name)
        print(f"[{name}] source points: {info.points_count}")

        if not dst.collection_exists(name):
            dst.create_collection(
                collection_name=name,
                vectors_config=info.config.params.vectors,
            )
            print(f"[{name}] created on destination")

        # Copy payload indexes
        for field, schema in (info.payload_schema or {}).items():
            try:
                dst.create_payload_index(name, field_name=field, field_schema=schema.data_type)
            except Exception as e:
                print(f"[{name}] index {field}: {e}")

        offset, total = None, 0
        while True:
            points, offset = src.scroll(
                collection_name=name, limit=BATCH, offset=offset,
                with_payload=True, with_vectors=True,
            )
            if points:
                dst.upsert(
                    collection_name=name,
                    points=[models.PointStruct(id=p.id, vector=p.vector, payload=p.payload) for p in points],
                )
                total += len(points)
                print(f"[{name}] copied {total}")
            if offset is None:
                break

        print(f"[{name}] done. destination points: {dst.get_collection(name).points_count}")


if __name__ == "__main__":
    main()
