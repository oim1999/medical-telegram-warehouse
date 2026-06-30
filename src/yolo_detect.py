"""
src/yolo_detect.py
-------------------
Object detection on scraped Telegram images using YOLOv8 nano.

Scans every image in data/raw/images/{channel}/{message_id}.jpg, runs
YOLOv8 detection, and classifies each image into one of four categories
based on the detected objects:

  - promotional    : person + product-like object (bottle/box) in same image
  - product_display: product-like object only, no person
  - lifestyle       : person only, no product-like object
  - other           : neither detected

Results are saved to a CSV file for loading into PostgreSQL.

Usage:
    python src/yolo_detect.py
    python src/yolo_detect.py --channel CheMed2
    python src/yolo_detect.py --confidence 0.4
"""

import os
import csv
import argparse
from pathlib import Path
from datetime import datetime

import cv2
import torch
from ultralytics import YOLO
from ultralytics.nn.tasks import DetectionModel
from loguru import logger
from tqdm import tqdm

# PyTorch 2.6+ defaults torch.load(weights_only=True), which blocks loading
# ultralytics' DetectionModel class unless it's explicitly allowlisted. This
# only affects loading the .pt checkpoint and has no bearing on the safety of
# inference itself — the YOLOv8 nano weights are downloaded directly from
# Ultralytics' official GitHub releases, a trusted source.
torch.serialization.add_safe_globals([DetectionModel])

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent.parent
IMAGES_DIR = BASE_DIR / "data" / "raw" / "images"
RESULTS_DIR = BASE_DIR / "data" / "processed"
LOGS_DIR    = BASE_DIR / "logs"

RESULTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logger.add(
    LOGS_DIR / f"yolo_detect_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log",
    level="INFO",
    rotation="10 MB",
)

# ── Classification rules ───────────────────────────────────────────────────────
# COCO class names relevant to our classification scheme.
# YOLOv8n is trained on the COCO dataset (80 general object classes) — it does
# NOT know "pill bottle" or "cosmetic cream" specifically. We approximate
# "product" using COCO classes that commonly represent packaged goods.
PERSON_CLASSES = {"person"}
PRODUCT_CLASSES = {
    "bottle", "cup", "bowl", "vase", "wine glass",
    "handbag", "suitcase", "backpack", "box",
}

MODEL_NAME = "yolov8n.pt"   # Nano model — fastest, smallest, good enough for
                            # broad object presence detection on a laptop CPU.


def classify_image(detected_labels: set[str]) -> str:
    """
    Classify an image into one of four categories based on which COCO
    object classes were detected above the confidence threshold.

    Classification scheme (per challenge document):
      - promotional     : person + product-like object together
      - product_display : product-like object, no person
      - lifestyle        : person, no product-like object
      - other             : neither
    """
    has_person = bool(detected_labels & PERSON_CLASSES)
    has_product = bool(detected_labels & PRODUCT_CLASSES)

    if has_person and has_product:
        return "promotional"
    elif has_product and not has_person:
        return "product_display"
    elif has_person and not has_product:
        return "lifestyle"
    else:
        return "other"


def extract_message_id(image_path: Path) -> int | None:
    """
    Extract the message_id from an image filename.
    Expected format: data/raw/images/{channel}/{message_id}.jpg
    """
    try:
        return int(image_path.stem)
    except ValueError:
        logger.warning(f"Could not parse message_id from filename: {image_path.name}")
        return None


def run_detection(
    model: YOLO,
    image_path: Path,
    channel_name: str,
    confidence_threshold: float = 0.35,
) -> list[dict]:
    """
    Run YOLOv8 detection on a single image and return one row per
    detected object above the confidence threshold, plus the overall
    image classification.

    Returns an empty list if the image cannot be read or processed
    (e.g., corrupted file) — this is a non-fatal error that is logged
    and skipped, since a single bad image should not halt the batch.
    """
    message_id = extract_message_id(image_path)
    if message_id is None:
        return []

    # Load the image with OpenCV rather than letting YOLO read the path
    # internally. This gives us an explicit, fast-failing check for
    # corrupted or unreadable files before handing pixel data to the model,
    # and keeps image I/O on one consistent library (cv2) instead of mixing
    # PIL and OpenCV array formats.
    image = cv2.imread(str(image_path))
    if image is None:
        logger.warning(f"cv2 could not read image (corrupted or unsupported): {image_path}")
        return []

    try:
        # YOLO accepts a BGR numpy array directly — no need to convert to
        # RGB since ultralytics handles the channel order internally.
        results = model.predict(
            source=image,
            conf=confidence_threshold,
            verbose=False,
        )
    except Exception as e:
        logger.error(f"YOLO inference failed for {image_path}: {e}")
        return []

    result = results[0]
    detected_labels = set()
    rows = []

    for box in result.boxes:
        class_id = int(box.cls[0])
        label = model.names[class_id]
        confidence = float(box.conf[0])
        detected_labels.add(label)

        rows.append({
            "message_id": message_id,
            "channel_name": channel_name,
            "image_path": str(image_path.relative_to(BASE_DIR)),
            "detected_class": label,
            "confidence_score": round(confidence, 4),
        })

    # If no objects detected, still record a row with image_category="other"
    # so the image isn't silently dropped from the dataset.
    image_category = classify_image(detected_labels)

    if not rows:
        rows.append({
            "message_id": message_id,
            "channel_name": channel_name,
            "image_path": str(image_path.relative_to(BASE_DIR)),
            "detected_class": None,
            "confidence_score": None,
        })

    # Attach the same image-level category to every detection row
    for row in rows:
        row["image_category"] = image_category

    return rows


def scan_images(channel_filter: str | None = None) -> list[Path]:
    """
    Discover all downloaded images in the data lake, optionally filtered
    to a single channel.
    """
    if not IMAGES_DIR.exists():
        logger.warning(f"Images directory not found: {IMAGES_DIR}")
        return []

    channel_dirs = (
        [IMAGES_DIR / channel_filter] if channel_filter
        else [d for d in IMAGES_DIR.iterdir() if d.is_dir()]
    )

    image_paths = []
    for channel_dir in channel_dirs:
        if not channel_dir.exists():
            logger.warning(f"Channel directory not found: {channel_dir}")
            continue
        image_paths.extend(sorted(channel_dir.glob("*.jpg")))

    return image_paths


def save_results_csv(all_rows: list[dict], output_path: Path) -> None:
    """Write detection results to a CSV file."""
    if not all_rows:
        logger.warning("No detection rows to save.")
        return

    fieldnames = [
        "message_id", "channel_name", "image_path",
        "detected_class", "confidence_score", "image_category",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    logger.info(f"Saved {len(all_rows)} detection rows to {output_path}")


def main(channel_filter: str | None, confidence: float) -> None:
    logger.info(f"Loading YOLOv8 model: {MODEL_NAME}")
    model = YOLO(MODEL_NAME)   # Auto-downloads the nano weights on first run

    image_paths = scan_images(channel_filter)
    logger.info(f"Found {len(image_paths)} images to process.")

    if not image_paths:
        logger.warning("No images found. Run the scraper first.")
        return

    all_rows = []
    failed_count = 0

    for img_path in tqdm(image_paths, desc="Running YOLOv8 detection"):
        channel_name = img_path.parent.name
        rows = run_detection(model, img_path, channel_name, confidence)
        if not rows:
            failed_count += 1
        all_rows.extend(rows)

    logger.info(f"Processed {len(image_paths)} images, {failed_count} failures.")

    output_path = RESULTS_DIR / "yolo_detections.csv"
    save_results_csv(all_rows, output_path)

    # Summary stats
    categories = {}
    for row in all_rows:
        cat = row["image_category"]
        categories[cat] = categories.get(cat, 0) + 1
    logger.info(f"Category breakdown: {categories}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run YOLOv8 object detection on scraped Telegram images."
    )
    parser.add_argument(
        "--channel",
        default=None,
        help="Limit detection to a single channel directory (default: all channels).",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.35,
        help="Minimum confidence threshold for detections (default: 0.35).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(args.channel, args.confidence)