"""Thin Google Cloud integration seam used by production deployments.

The golden demo remains deterministic without credentials. When GCP_PROJECT_ID is
present, feedback/profile events are mirrored to Firestore and Pub/Sub.
"""

import json
import os
from datetime import datetime, timezone


_explicit_credentials = None


def configure_credentials(credentials) -> None:
    """Inject short-lived credentials for one-time administrative utilities."""
    global _explicit_credentials
    _explicit_credentials = credentials


def cloud_enabled() -> bool:
    return bool(os.getenv("GCP_PROJECT_ID"))


def firestore_primary() -> bool:
    return cloud_enabled() and os.getenv("PERSISTENCE_BACKEND", "sqlite").casefold() == "firestore"


def _firestore_client():
    from google.cloud import firestore

    return firestore.Client(
        project=os.environ["GCP_PROJECT_ID"],
        database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        credentials=_explicit_credentials,
    )


def persist_document(collection: str, document_id: str, payload: dict) -> bool:
    if not cloud_enabled():
        return False
    _firestore_client().collection(collection).document(document_id).set(payload, merge=True)
    return True


def get_document(collection: str, document_id: str) -> dict | None:
    if not firestore_primary():
        return None
    snapshot = _firestore_client().collection(collection).document(document_id).get()
    return snapshot.to_dict() if snapshot.exists else None


def query_documents(collection: str, field: str, value: str) -> list[dict]:
    if not firestore_primary():
        return []
    from google.cloud.firestore_v1.base_query import FieldFilter

    query = _firestore_client().collection(collection).where(filter=FieldFilter(field, "==", value))
    return [snapshot.to_dict() for snapshot in query.stream()]


def persist_semantic_memory(document_id: str, payload: dict) -> bool:
    """Persist a memory with Firestore's native Vector value when available."""
    if not cloud_enabled():
        return False
    stored = dict(payload)
    vector = stored.get("embedding") or []
    if vector:
        from google.cloud.firestore_v1.vector import Vector

        stored["embedding"] = Vector(vector)
    _firestore_client().collection("semantic_memory").document(document_id).set(stored, merge=True)
    return True


def query_semantic_memory(
    profile_id: str,
    query_vector: list[float],
    limit: int = 20,
    distance_threshold: float = 0.30,
) -> list[dict]:
    """Run native cosine KNN with a profile pre-filter in production Firestore."""
    if not firestore_primary() or not query_vector:
        return []
    from google.cloud.firestore_v1.base_query import FieldFilter
    from google.cloud.firestore_v1.vector import Vector
    from google.cloud.firestore_v1.base_vector_query import DistanceMeasure

    query = _firestore_client().collection("semantic_memory").where(
        filter=FieldFilter("profile_id", "==", profile_id)
    )
    nearest = query.find_nearest(
        vector_field="embedding",
        query_vector=Vector(query_vector),
        distance_measure=DistanceMeasure.COSINE,
        limit=limit,
        distance_result_field="cosine_distance",
        distance_threshold=distance_threshold,
    )
    return [snapshot.to_dict() for snapshot in nearest.stream()]


def upload_listing_images(listing_id: str, paths: list[str]) -> int:
    bucket_name = os.getenv("LISTING_IMAGE_BUCKET")
    if not cloud_enabled() or not bucket_name:
        return 0
    from google.cloud import storage

    client = storage.Client(project=os.environ["GCP_PROJECT_ID"], credentials=_explicit_credentials)
    bucket = client.bucket(bucket_name)
    uploaded = 0
    for index, path in enumerate(paths):
        extension = os.path.splitext(path)[1].lower()
        blob = bucket.blob(f"listing_images/{listing_id}/{index}{extension}")
        if blob.exists():
            continue
        blob.upload_from_filename(path, content_type={".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(extension))
        uploaded += 1
    return uploaded


def download_listing_image(listing_id: str, image_index: int = 0) -> tuple[bytes, str] | None:
    bucket_name = os.getenv("LISTING_IMAGE_BUCKET")
    if not cloud_enabled() or not bucket_name:
        return None
    from google.cloud import storage

    client = storage.Client(project=os.environ["GCP_PROJECT_ID"], credentials=_explicit_credentials)
    bucket = client.bucket(bucket_name)
    prefix = f"listing_images/{listing_id}/{image_index}"
    blobs = list(client.list_blobs(bucket, prefix=prefix, max_results=3))
    match = next((blob for blob in blobs if os.path.splitext(blob.name)[0] == prefix), None)
    if not match:
        return None
    return match.download_as_bytes(), match.content_type or "application/octet-stream"


def cloud_listing_image_count(listing_id: str) -> int:
    bucket_name = os.getenv("LISTING_IMAGE_BUCKET")
    if not cloud_enabled() or not bucket_name:
        return 0
    from google.cloud import storage

    client = storage.Client(project=os.environ["GCP_PROJECT_ID"], credentials=_explicit_credentials)
    bucket = client.bucket(bucket_name)
    return sum(1 for _ in client.list_blobs(bucket, prefix=f"listing_images/{listing_id}/"))


def upload_city_orientation(city_slug: str, asset_kind: str, path: str, content_type: str) -> str:
    """Upload a generated city-orientation asset to the existing private media bucket."""
    bucket_name = os.getenv("LISTING_IMAGE_BUCKET")
    if not cloud_enabled() or not bucket_name:
        raise RuntimeError("Google Cloud media storage is not configured")
    from google.cloud import storage

    extension = os.path.splitext(path)[1].lower()
    object_name = f"city_orientations/{city_slug}/{asset_kind}{extension}"
    client = storage.Client(project=os.environ["GCP_PROJECT_ID"], credentials=_explicit_credentials)
    blob = client.bucket(bucket_name).blob(object_name)
    blob.upload_from_filename(path, content_type=content_type)
    blob.cache_control = "public, max-age=604800, immutable"
    blob.patch()
    return object_name


def download_city_orientation(city_slug: str, asset_kind: str) -> tuple[bytes, str] | None:
    bucket_name = os.getenv("LISTING_IMAGE_BUCKET")
    if not cloud_enabled() or not bucket_name:
        return None
    from google.cloud import storage

    client = storage.Client(project=os.environ["GCP_PROJECT_ID"], credentials=_explicit_credentials)
    bucket = client.bucket(bucket_name)
    prefix = f"city_orientations/{city_slug}/{asset_kind}"
    blobs = list(client.list_blobs(bucket, prefix=prefix, max_results=3))
    match = next((blob for blob in blobs if os.path.splitext(blob.name)[0] == prefix), None)
    if not match:
        return None
    return match.download_as_bytes(), match.content_type or "application/octet-stream"


def persist_profile(profile: dict) -> None:
    if not cloud_enabled():
        return
    client = _firestore_client()
    client.collection("profiles").document(profile["profile_id"]).set(profile)


def persist_revision(profile_id: str, revision: dict) -> None:
    if not cloud_enabled():
        return
    client = _firestore_client()
    client.collection("profiles").document(profile_id).collection("revisions").document().set(revision)


def publish_event(event_type: str, payload: dict) -> None:
    topic = os.getenv("PUBSUB_TOPIC")
    if not cloud_enabled() or not topic:
        return
    from google.cloud import pubsub_v1

    publisher = pubsub_v1.PublisherClient()
    path = publisher.topic_path(os.environ["GCP_PROJECT_ID"], topic)
    publisher.publish(path, json.dumps({"type": event_type, "payload": payload}).encode("utf-8"))


def persist_listing_catalog(mode: str, listings: list[dict], refresh: dict) -> bool:
    """Mirror a successful local catalog refresh to Firestore when ADC exists."""
    if not cloud_enabled():
        return False

    client = _firestore_client()
    batch = client.batch()
    persisted_at = datetime.now(timezone.utc).isoformat()
    collection = client.collection("listing_catalog")
    for listing in listings:
        batch.set(
            collection.document(listing["id"]),
            {**listing, "persisted_at": persisted_at},
            merge=True,
        )
    batch.set(
        client.collection("listing_refresh").document(mode),
        {**refresh, "persisted_at": persisted_at},
        merge=True,
    )
    batch.commit()
    return True
