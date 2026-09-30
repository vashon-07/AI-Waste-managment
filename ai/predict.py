"""
AI WasteWatch - Inference & Waste Classification Engine
Module: ai/predict.py

This module runs inference on captured or uploaded waste images using the
fine-tuned computer vision model. It extracts:
- waste type (primary detected category)
- confidence score (probability)
- detected objects (list of bounding boxes, labels, and individual confidences)
- severity (e.g., Low, Medium, High, Critical)
- priority score (dynamic numeric score for municipal cleanup routing)

This module is designed to be easily imported directly by Flask routes
or run standalone from the command line.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional

# Paths configuration
BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
PREDICTIONS_DIR = BASE_DIR / "predictions"


def calculate_severity(detected_objects: List[Dict[str, Any]]) -> str:
    """
    Computes a severity rating ('Low', 'Medium', 'High', 'Critical')
    based on the number of detected items and presence of hazardous/electronic waste.

    TODO:
    - Tune weighting factors and thresholds with domain heuristics.
    """
    if not detected_objects:
        return "Low"

    count = len(detected_objects)
    has_hazardous = any(
        obj.get("label", "").lower() in ["hazardous", "chemical", "medical", "e-waste", "battery"]
        for obj in detected_objects
    )

    if has_hazardous or count >= 10:
        return "Critical"
    elif count >= 5:
        return "High"
    elif count >= 2:
        return "Medium"
    return "Low"


def calculate_priority_score(
    waste_type: str,
    severity: str,
    confidence_score: float,
    object_count: int
) -> float:
    """
    Calculates a numerical priority score (0.0 - 100.0) for routing municipal cleanup.

    TODO:
    - Incorporate location density and time elapsed when integrating with database.
    """
    severity_weights = {
        "Critical": 40.0,
        "High": 30.0,
        "Medium": 20.0,
        "Low": 10.0
    }

    type_weights = {
        "Hazardous": 35.0,
        "E-Waste": 30.0,
        "Plastic": 20.0,
        "Metal": 15.0,
        "Glass": 15.0,
        "Organic": 10.0,
        "Paper": 10.0,
        "Mixed": 15.0
    }

    base_severity = severity_weights.get(severity, 10.0)
    base_type = type_weights.get(waste_type, 15.0)
    count_factor = min(object_count * 2.5, 25.0)

    # Score out of 100, scaled by model confidence
    raw_score = (base_severity + base_type + count_factor) * confidence_score
    return round(min(max(raw_score, 0.0), 100.0), 2)


def predict_waste(
    image_path: str,
    model_path: Optional[str] = None,
    save_annotated: bool = True,
    conf_threshold: float = 0.35
) -> Dict[str, Any]:
    """
    Performs AI waste detection on a single image.

    Args:
        image_path: Path to the uploaded or captured image file.
        model_path: Optional path to the trained model weights.
        save_annotated: Whether to save visual prediction with bounding boxes into ai/predictions/
        conf_threshold: Minimum confidence threshold for detected objects.

    Returns:
        dict containing:
            - waste_type: str
            - confidence_score: float
            - detected_objects: list[dict]
            - severity: str
            - priority_score: float
            - annotated_image_path: Optional[str]

    TODO:
    1. Load model checkpoint (e.g. YOLOv8 / YOLOv11 or PyTorch model from `ai/models/`).
       - If weights do not yet exist, provide fallback/mock predictions for testing UI flows.
    2. Run inference:
       - Detect waste objects, extract bounding boxes, class labels, and confidence.
    3. Aggregate results:
       - Determine primary waste type (e.g. majority class or highest-risk class).
       - Compute average confidence score.
       - Calculate severity and priority score using helper functions.
    4. Save annotated image with bounding boxes into `ai/predictions/` if save_annotated is True.
    """
    PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)

    if model_path is None:
        model_path = str(MODELS_DIR / "waste_best.pt")

    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Input image not found: {image_path}")

    # TODO: Connect actual trained weights when available.
    # Below is the production inference structure with a development placeholder.
    if os.path.exists(model_path):
        # --- Production Flow ---
        # from ultralytics import YOLO
        # model = YOLO(model_path)
        # results = model.predict(image_path, conf=conf_threshold, save=False)
        #
        # Parse detections...
        # detected_objects = [...]
        # waste_type = determine_primary_class(detected_objects)
        # confidence_score = calculate_average_confidence(detected_objects)
        pass

    # Development placeholder (until model weights are trained and saved)
    detected_objects: List[Dict[str, Any]] = [
        {
            "label": "Plastic Bottle",
            "category": "Plastic",
            "confidence": 0.92,
            "box": [120, 80, 310, 450]
        }
    ]

    waste_type = "Plastic"
    confidence_score = 0.92
    severity = calculate_severity(detected_objects)
    priority_score = calculate_priority_score(
        waste_type=waste_type,
        severity=severity,
        confidence_score=confidence_score,
        object_count=len(detected_objects)
    )

    annotated_filename = f"pred_{Path(image_path).name}"
    annotated_path = str(PREDICTIONS_DIR / annotated_filename)

    return {
        "waste_type": waste_type,
        "confidence_score": confidence_score,
        "detected_objects": detected_objects,
        "severity": severity,
        "priority_score": priority_score,
        "annotated_image_path": annotated_path if save_annotated else None
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_img = sys.argv[1]
        print(f"[*] Running prediction on: {test_img}")
        res = predict_waste(test_img)
        print("[*] Results:", res)
    else:
        print("[*] Usage: python -m ai.predict <path_to_image>")
        print("[*] Prediction module initialized successfully.")
