from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import google.auth
from google.auth.exceptions import DefaultCredentialsError
from google.oauth2.credentials import Credentials

from app.cloud import configure_credentials, persist_listing_catalog, upload_listing_images
from app.models import Listing


ALLOWED_SOURCES = {
    "Ho Chi Minh City": ("batdongsan.com.vn", "https://batdongsan.com.vn/"),
    "Bangkok": ("propertyhub.in.th", "https://propertyhub.in.th/"),
    "Kuala Lumpur": ("propertygenie.com.my", "https://www.propertygenie.com.my/"),
}


def gallery_paths(image_root: Path, listing_id: str) -> list[str]:
    return [
        str(path)
        for path in sorted(image_root.glob(f"{listing_id}*"))
        if path.is_file() and path.suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"}
    ]


def configure_local_credentials() -> None:
    """Prefer ADC, then borrow the active gcloud user's short-lived token."""
    try:
        credentials, _ = google.auth.default()
    except DefaultCredentialsError:
        gcloud = shutil.which("gcloud") or shutil.which("gcloud.cmd")
        if not gcloud:
            raise SystemExit("Google Cloud CLI is required when ADC is unavailable")
        completed = subprocess.run(
            [gcloud, "auth", "print-access-token"],
            check=True,
            capture_output=True,
            text=True,
        )
        token = completed.stdout.strip()
        if not token:
            raise SystemExit("gcloud did not return an access token")
        credentials = Credentials(token=token)
    configure_credentials(credentials)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Firestore and Cloud Storage from the verified local snapshot.")
    parser.add_argument("--database", default="data/roamstead.db")
    parser.add_argument("--images", default="data/listing_images")
    parser.add_argument("--project", default=os.getenv("GCP_PROJECT_ID"))
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    database = Path(args.database).resolve()
    image_root = Path(args.images).resolve()
    if not database.exists() or not image_root.is_dir():
        raise SystemExit("The verified local database and listing image directory are required")

    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT payload_json FROM listing_catalog ORDER BY transaction_mode, id").fetchall()
    listings = [Listing.model_validate(json.loads(row[0])) for row in rows]
    if not listings:
        raise SystemExit("The local catalog is empty")
    invalid = []
    for item in listings:
        source_contract = ALLOWED_SOURCES.get(item.city)
        if (
            item.demo
            or not source_contract
            or item.source_domain != source_contract[0]
            or not item.source_url.startswith(source_contract[1])
            or not gallery_paths(image_root, item.id)
        ):
            invalid.append(item.id)
    if invalid:
        raise SystemExit(f"Refusing to seed {len(invalid)} listings that fail the real-source/photo contract")
    if args.validate_only:
        print(f"Validated {len(listings)} real listings with exact-listing photographs")
        for city in ALLOWED_SOURCES:
            for mode in ("BUY", "RENT"):
                print(f"{city} {mode}: {sum(item.city == city and item.transaction_mode == mode for item in listings)}")
        return

    if not args.project:
        raise SystemExit("--project or GCP_PROJECT_ID is required for a cloud seed")
    os.environ["GCP_PROJECT_ID"] = args.project

    configure_local_credentials()
    uploaded = 0
    for mode in ("BUY", "RENT"):
        selected = [item for item in listings if item.transaction_mode == mode]
        if len(selected) < 25:
            raise SystemExit(f"{mode} has only {len(selected)} verified listings")
        latest = max(item.source_checked_at for item in selected)
        persisted = persist_listing_catalog(
            mode,
            [item.model_dump(mode="json") for item in selected],
            {
                "transaction_mode": mode,
                "last_attempt_at": latest,
                "last_success_at": latest,
                "returned_count": len(selected),
                "last_error": None,
                "seed_source": "verified_local_snapshot",
            },
        )
        if not persisted:
            raise SystemExit(f"Cloud persistence was not enabled for {mode}")
        for item in selected:
            uploaded += upload_listing_images(item.id, gallery_paths(image_root, item.id))
        print(f"Seeded {len(selected)} verified {mode} listings")
    print(f"Uploaded {uploaded} exact-listing photographs")


if __name__ == "__main__":
    main()
