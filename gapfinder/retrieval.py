"""Retrieval has no dependency on generation; every query is scoped to one user."""
import hashlib
import math
import re
from threading import RLock

from qdrant_client import QdrantClient, models

STOP = set("a an the and or is are was were of in on to for with from by as it this that which what how".split())


def terms(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 2]


class Encoder:
    def __init__(self, settings):
        self.backend = settings.embedding_backend
        self.model_name = settings.embedding_model
        self.model = None
        self.cache_dir = settings.data_dir / "models"
        self.lock = RLock()

    def embed(self, texts):
        if not texts:
            return []
        if self.backend == "fastembed":
            with self.lock:
                if self.model is None:
                    from fastembed import TextEmbedding
                    self.model = TextEmbedding(model_name=self.model_name, cache_dir=str(self.cache_dir))
                return [v.tolist() for v in self.model.embed(texts)]
        # Deliberately lexical, offline baseline; never described as semantic AI.
        vectors = []
        for text in texts:
            vector = [0.0] * 512
            for word in terms(text):
                index = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=4).digest(), "big") % 512
                vector[index] += 1
            norm = math.sqrt(sum(x * x for x in vector)) or 1
            vectors.append([x / norm for x in vector])
        return vectors


class Retrieval:
    def __init__(self, settings):
        self.encoder = Encoder(settings)
        self.lock = RLock()
        self.remote = bool(settings.qdrant_url)
        self.client = (QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_key or None, timeout=30)
                       if settings.qdrant_url else QdrantClient(path=str(settings.data_dir / "qdrant")))
        identity = f"{settings.embedding_backend}:{settings.embedding_model}"
        self.collection = "material_" + hashlib.sha256(identity.encode()).hexdigest()[:12]

    def index(self, chunks):
        if not chunks:
            return
        vectors = self.encoder.embed([c["text"] for c in chunks])
        with self.lock:
            if not self.client.collection_exists(self.collection):
                self.client.create_collection(self.collection, vectors_config=models.VectorParams(
                    size=len(vectors[0]), distance=models.Distance.COSINE))
                # Payload indexes are useful for server/cloud deployments; embedded Qdrant filters directly.
                if self.remote:
                    for key in ("user_id", "topic_id", "kind"):
                        self.client.create_payload_index(self.collection, key, models.PayloadSchemaType.KEYWORD)
            points = [models.PointStruct(id=c["id"], vector=v, payload=c) for c, v in zip(chunks, vectors)]
            self.client.upsert(self.collection, points, wait=True)

    def search(self, user_id, query, *, topic_id=None, kind=None, limit=5):
        with self.lock:
            if not self.client.collection_exists(self.collection):
                return []
        vector = self.encoder.embed([query])[0]
        filters = [models.FieldCondition(key="user_id", match=models.MatchValue(value=user_id))]
        for key, value in (("topic_id", topic_id), ("kind", kind)):
            if value:
                filters.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
        with self.lock:
            result = self.client.query_points(self.collection, query=vector,
                query_filter=models.Filter(must=filters), limit=limit, with_payload=True)
        return [{**p.payload, "score": p.score} for p in result.points]

    def close(self):
        self.client.close()
