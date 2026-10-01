"""
AI WasteWatch - Inference & Waste Classification Engine
Module: ai/predict.py

Modular inference layer supporting the Hugging Face Vision Transformer
model: watersplash/waste-classification.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from PIL import Image

try:
    from .classifier import get_classifier, HuggingFaceWasteClassifier
except ImportError:
    from ai.classifier import get_classifier, HuggingFaceWasteClassifier

# Paths configuration
BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
PREDICTIONS_DIR = BASE_DIR / "predictions"


def calculate_severity(detected_objects: List[Dict[str, Any]], primary_waste_type: str = "") -> str:
    """
    Computes a severity rating ('Low', 'Medium', 'High', 'Critical')
    based on the primary waste type and detected objects.
    """
    primary_lower = primary_waste_type.lower()
    if any(k in primary_lower for k in ["hazard", "chemical", "medical", "battery", "toxic"]):
        return "Critical"
    if any(k in primary_lower for k in ["e-waste", "electronic", "plastic"]):
        return "High"

    if not detected_objects:
        return "Medium"

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
    object_count: int = 1
) -> float:
    """
    Calculates a numerical priority score (0.0 - 100.0) for routing municipal cleanup.
    """
    severity_weights = {
        "Critical": 40.0,
        "High": 30.0,
        "Medium": 20.0,
        "Low": 10.0
    }

    type_weights = {
        "Hazardous Waste": 35.0,
        "Hazardous": 35.0,
        "E-Waste": 30.0,
        "Plastic Waste": 25.0,
        "Plastic": 20.0,
        "Metal Waste": 18.0,
        "Glass Waste": 15.0,
        "Organic Waste": 12.0,
        "Paper & Cardboard": 10.0,
        "Mixed Municipal Waste": 15.0
    }

    base_severity = severity_weights.get(severity, 20.0)
    base_type = type_weights.get(waste_type, 15.0)
    count_factor = min(object_count * 2.5, 25.0)

    # Score out of 100, scaled by model confidence
    raw_score = (base_severity + base_type + count_factor) * max(confidence_score, 0.5)
    return round(min(max(raw_score, 10.0), 100.0), 2)


def predict_waste(
    image_input: Union[str, bytes, Image.Image],
    model_name: Optional[str] = None,
    save_annotated: bool = False
) -> Dict[str, Any]:
    """
    Performs AI waste classification on a single image using Hugging Face ViT.

    Args:
        image_input: Path, bytes, base64 data URL, or PIL Image.
        model_name: Optional custom Hugging Face model repository.
        save_annotated: Flag for saving annotated prediction images.

    Returns:
        dict containing:
            - waste_type: str
            - confidence_score: float
            - confidence_percent: float
            - severity: str
            - priority_score: float
            - raw_label: str
            - top_predictions: list[dict]
            - model_name: str
    """
    classifier = get_classifier(model_name) if model_name else get_classifier()
    result = classifier.predict(image_input)

    # If the model is not ready, return the loading response directly
    if not result.get("success"):
        return result

    # Enhance with domain calculations for genuine model predictions
    severity = result.get("severity") or calculate_severity([], result.get("waste_type", ""))
    confidence = result.get("confidence_score", 0.85)
    priority_score = calculate_priority_score(
        waste_type=result.get("waste_type", "Mixed Municipal Waste"),
        severity=severity,
        confidence_score=confidence,
        object_count=1
    )

    result["severity"] = severity
    result["priority_score"] = priority_score

    return result


if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_img = sys.argv[1]
        print(f"[*] Running Hugging Face waste prediction on: {test_img}")
        res = predict_waste(test_img)
        print("[*] Results:", res)
    else:
        print("[*] Usage: python -m ai.predict <path_to_image>")
        print("[*] Hugging Face prediction module initialized successfully.")
