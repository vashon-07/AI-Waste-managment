"""
AI WasteWatch - Inference & Waste Classification Engine
Module: ai/predict.py

Dual-engine inference layer supporting:
1. Custom YOLOv8 object detection model (best.pt / waste_best.pt) if installed and present.
2. Hugging Face Vision Transformer (ViT: watersplash/waste-classification) with automatic fallback.
"""

import os
import sys
import io
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from PIL import Image

logger = logging.getLogger("WastePredict")

try:
    from .classifier import get_classifier, HuggingFaceWasteClassifier
except (ImportError, ValueError):
    try:
        from ai.classifier import get_classifier, HuggingFaceWasteClassifier
    except ImportError:
        _parent_dir = str(Path(__file__).resolve().parent.parent)
        if _parent_dir not in sys.path:
            sys.path.insert(0, _parent_dir)
        try:
            from ai.classifier import get_classifier, HuggingFaceWasteClassifier
        except ImportError:
            from classifier import get_classifier, HuggingFaceWasteClassifier

# Paths configuration
BASE_DIR = Path(__file__).resolve().parent
MODELS_DIR = BASE_DIR / "models"
PREDICTIONS_DIR = BASE_DIR / "predictions"
MODEL_PATH = MODELS_DIR / "best.pt"

# WasteWatch 7 classes for YOLO model
CLASS_NAMES = {
    0: "Plastic",
    1: "Paper/Cardboard",
    2: "Glass",
    3: "Metal",
    4: "Organic",
    5: "Hazardous",
    6: "Other"
}

# Optional YOLO model loader (safe against missing ultralytics or missing best.pt)
_yolo_model = None

def _get_yolo_model():
    global _yolo_model
    if _yolo_model is not None:
        return _yolo_model

    # Check potential YOLO weight locations
    candidate_paths = [
        MODEL_PATH,
        MODELS_DIR / "waste_best.pt",
        Path(os.environ.get("YOLO_MODEL_PATH", "")) if os.environ.get("YOLO_MODEL_PATH") else None
    ]

    found_path = None
    for p in candidate_paths:
        if p and p.is_file():
            found_path = p
            break

    if not found_path:
        return None

    try:
        from ultralytics import YOLO
        logger.info(f"[*] Loading YOLO weights from: {found_path}")
        _yolo_model = YOLO(str(found_path))
        return _yolo_model
    except ImportError:
        logger.info("[!] ultralytics not installed; running ViT classifier engine.")
        return None
    except Exception as e:
        logger.warning(f"[!] Could not load YOLO model from {found_path}: {e}")
        return None


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
        obj.get("waste_type", obj.get("label", "")).lower() in ["hazardous", "chemical", "medical", "e-waste", "battery"]
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
        "Paper/Cardboard": 10.0,
        "Mixed Municipal Waste": 15.0,
        "Other": 10.0
    }

    base_severity = severity_weights.get(severity, 20.0)
    base_type = type_weights.get(waste_type, 15.0)
    count_factor = min(object_count * 2.5, 25.0)

    # Score out of 100, scaled by model confidence
    raw_score = (base_severity + base_type + count_factor) * max(confidence_score, 0.5)
    return round(min(max(raw_score, 10.0), 100.0), 2)


def _load_image_as_pil(image_input: Union[str, bytes, io.BytesIO, Image.Image]) -> Image.Image:
    """Helper to convert various image input formats into a PIL Image."""
    if isinstance(image_input, Image.Image):
        return image_input.convert("RGB")
    if isinstance(image_input, bytes):
        return Image.open(io.BytesIO(image_input)).convert("RGB")
    if isinstance(image_input, io.BytesIO):
        return Image.open(image_input).convert("RGB")
    if isinstance(image_input, str):
        # Could be file path or base64 data URI
        if image_input.startswith("data:image"):
            import base64
            header, encoded = image_input.split(",", 1)
            img_bytes = base64.b64decode(encoded)
            return Image.open(io.BytesIO(img_bytes)).convert("RGB")
        return Image.open(image_input).convert("RGB")
    raise ValueError(f"Unsupported image input type: {type(image_input)}")


def predict_waste(
    image_input: Union[str, bytes, io.BytesIO, Image.Image],
    confidence: float = 0.25,
    model_name: Optional[str] = None,
    save_annotated: bool = False
) -> Dict[str, Any]:
    """
    Performs AI waste detection and classification on a single image.
    Uses YOLOv8 if best.pt is present; otherwise falls back to Hugging Face ViT.

    Args:
        image_input: Path, bytes, io.BytesIO, base64 data URL, or PIL Image.
        confidence: Minimum confidence threshold for YOLO detections.
        model_name: Optional custom Hugging Face model repository.
        save_annotated: Flag for saving annotated prediction images.

    Returns:
        dict containing:
            - success: bool
            - waste_type: str
            - confidence_score: float
            - confidence_percent: float
            - severity: str
            - priority_score: float
            - raw_label: str
            - detections: list[dict]
            - top_predictions: list[dict]
            - model_name: str
    """
    yolo = _get_yolo_model()
    if yolo is not None:
        try:
            pil_img = _load_image_as_pil(image_input)
            results = yolo.predict(source=pil_img, conf=confidence, verbose=False)
            detections = []

            for result in results:
                if result.boxes is None:
                    continue
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    waste_type_name = CLASS_NAMES.get(class_id, "Other")
                    detections.append({
                        "class_id": class_id,
                        "waste_type": waste_type_name,
                        "confidence": round(conf, 3),
                        "box": [round(float(coord), 1) for coord in box.xyxy[0].tolist()] if hasattr(box, "xyxy") else []
                    })

            if detections:
                # Pick detection with highest confidence or highest hazard
                sorted_by_conf = sorted(detections, key=lambda d: d["confidence"], reverse=True)
                primary_detection = sorted_by_conf[0]
                primary_waste_type = primary_detection["waste_type"]
                best_conf = primary_detection["confidence"]
                
                # Check if any detection is hazardous
                for d in detections:
                    if "hazard" in d["waste_type"].lower():
                        primary_waste_type = d["waste_type"]
                        best_conf = max(best_conf, d["confidence"])
                        break

                severity = calculate_severity(detections, primary_waste_type)
                priority_score = calculate_priority_score(
                    waste_type=primary_waste_type,
                    severity=severity,
                    confidence_score=best_conf,
                    object_count=len(detections)
                )

                return {
                    "success": True,
                    "waste_type": primary_waste_type,
                    "confidence_score": best_conf,
                    "confidence_percent": round(best_conf * 100, 2),
                    "severity": severity,
                    "priority_score": priority_score,
                    "raw_label": primary_waste_type.lower(),
                    "detections": detections,
                    "total_objects": len(detections),
                    "model_name": "WasteWatch-YOLOv8",
                    "is_ready": True
                }
        except Exception as e:
            logger.warning(f"[!] YOLO inference encountered an error: {e}. Falling back to ViT.")

    # ViT / Hugging Face classifier engine fallback
    classifier = get_classifier(model_name) if model_name else get_classifier()
    result = classifier.predict(image_input)

    # If the model is not ready, return the loading response directly
    if not result.get("success"):
        return result

    # Enhance with domain calculations for genuine model predictions
    waste_type = result.get("waste_type", "Mixed Municipal Waste")
    confidence_val = result.get("confidence_score", 0.85)
    severity = result.get("severity") or calculate_severity([], waste_type)
    priority_score = calculate_priority_score(
        waste_type=waste_type,
        severity=severity,
        confidence_score=confidence_val,
        object_count=1
    )

    result["severity"] = severity
    result["priority_score"] = priority_score
    if "detections" not in result:
        result["detections"] = [{
            "class_id": None,
            "waste_type": waste_type,
            "confidence": round(confidence_val, 3)
        }]

    return result


if __name__ == "__main__":
    test_img = sys.argv[1] if len(sys.argv) > 1 else "test_waste.jpg"
    if not os.path.exists(test_img):
        test_img = os.path.join(BASE_DIR, "test", "sample_plastic_bottle.jpg")

    print(f"[*] Running WasteWatch AI prediction on: {test_img}")
    if _get_yolo_model() is None:
        clf = get_classifier()
        if not clf._is_ready:
            print("[*] Synchronously preparing Vision Transformer pipeline...")
            clf._load_pipeline_sync()

    res = predict_waste(test_img)

    print("\n===== WasteWatch AI Result =====")
    if res.get("success"):
        print(f"Primary Waste Type: {res.get('waste_type')}")
        print(f"Confidence:         {res.get('confidence_percent', 0):.1f}%")
        print(f"Severity:           {res.get('severity')}")
        print(f"Priority Score:     {res.get('priority_score')}/100")
        if res.get("detections"):
            print("\nDetected Objects:")
            for d in res["detections"]:
                print(f"  - {d.get('waste_type')} ({d.get('confidence') * 100:.1f}%)")
    else:
        print(f"Model status: {res.get('status', 'unavailable')} - {res.get('message')}")