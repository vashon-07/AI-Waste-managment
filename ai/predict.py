
"""
AI WasteWatch - YOLOv8 Waste Detection and Severity Pipeline
"""

import base64
import io
from pathlib import Path
from typing import Any, Dict, List, Union

from PIL import Image
from ultralytics import YOLO

try:
    from ai.severity import calculate_severity
except ModuleNotFoundError:
    from severity import calculate_severity


BASE_DIR = Path(__file__).resolve().parent
MODEL_PATH = BASE_DIR / "models" / "best.pt"

CLASS_NAMES = {
    0: "Plastic",
    1: "Paper/Cardboard",
    2: "Glass",
    3: "Metal",
    4: "Organic",
    5: "Hazardous",
    6: "Other",
}

_model = None


def get_model():
    """Load the YOLO model once and reuse it."""
    global _model

    if _model is None:
        if not MODEL_PATH.is_file():
            raise FileNotFoundError(
                f"YOLO model not found: {MODEL_PATH}"
            )

        _model = YOLO(str(MODEL_PATH))

    return _model


def prepare_image(
    image_input: Union[str, Path, bytes, bytearray, Image.Image]
):
    """Convert supported image inputs into a format YOLO can read."""

    if isinstance(image_input, Image.Image):
        return image_input.convert("RGB")

    if isinstance(image_input, (bytes, bytearray)):
        if not image_input:
            raise ValueError("The uploaded image is empty.")

        with Image.open(io.BytesIO(image_input)) as image:
            return image.convert("RGB")

    if isinstance(image_input, (str, Path)):
        value = str(image_input).strip()

        if not value:
            raise ValueError("No image path was provided.")

        if value.startswith("data:image"):
            encoded = value.split(",", 1)[1]
            raw_bytes = base64.b64decode(encoded)

            with Image.open(io.BytesIO(raw_bytes)) as image:
                return image.convert("RGB")

        image_path = Path(value)

        if image_path.is_file():
            with Image.open(image_path) as image:
                return image.convert("RGB")

        # Also support a raw base64 string.
        try:
            raw_bytes = base64.b64decode(value, validate=True)

            with Image.open(io.BytesIO(raw_bytes)) as image:
                return image.convert("RGB")
        except Exception:
            raise FileNotFoundError(
                f"Image file not found or invalid: {value}"
            )

    raise TypeError(
        f"Unsupported image input type: {type(image_input).__name__}"
    )


def predict_waste(
    image_input: Union[str, Path, bytes, bytearray, Image.Image],
    confidence: float = 0.25,
    iou_threshold: float = 0.45,
) -> Dict[str, Any]:
    """Detect waste objects and calculate severity and priority."""

    try:
        image = prepare_image(image_input)
        model = get_model()

        results = model.predict(
            source=image,
            conf=confidence,
            iou=iou_threshold,
            verbose=False,
        )

        detections: List[Dict[str, Any]] = []

        for result in results:
            if result.boxes is None:
                continue

            for box in result.boxes:
                class_id = int(box.cls[0].item())
                score = float(box.conf[0].item())
                coords = box.xyxy[0].tolist()

                detections.append({
                    "class_id": class_id,
                    "waste_type": CLASS_NAMES.get(class_id, "Other"),
                    "confidence": round(score, 3),
                    "box": {
                        "x1": round(coords[0], 1),
                        "y1": round(coords[1], 1),
                        "x2": round(coords[2], 1),
                        "y2": round(coords[3], 1),
                    },
                })

        detections.sort(
            key=lambda item: item["confidence"],
            reverse=True,
        )

        categories = list(dict.fromkeys(
            item["waste_type"] for item in detections
        ))
        object_count = len(detections)
        is_mixed = len(categories) > 1

        if detections:
            primary = detections[0]
            confidence_score = primary["confidence"]

            # Prefer a detected hazardous object as the primary category.
            hazardous = next(
                (
                    item for item in detections
                    if item["waste_type"] == "Hazardous"
                ),
                None,
            )

            if hazardous:
                primary = hazardous
                confidence_score = hazardous["confidence"]

            waste_type = (
                f"Mixed Waste ({', '.join(categories)})"
                if is_mixed
                else primary["waste_type"]
            )

            raw_label = ", ".join(
                f"{item['waste_type']} "
                f"({item['confidence'] * 100:.1f}%)"
                for item in detections[:3]
            )
        else:
            confidence_score = 0.0
            waste_type = "No Waste Detected"
            raw_label = "no_detection"

        severity_result = calculate_severity(
            detections,
            is_mixed=is_mixed,
        )

        return {
            "success": True,
            "detections": detections,
            "categories": categories,
            "object_count": object_count,
            "total_objects": object_count,
            "is_mixed": is_mixed,
            "waste_type": waste_type,
            "raw_label": raw_label,
            "confidence_score": confidence_score,
            "confidence_percent": round(
                confidence_score * 100, 2
            ),
            "severity": severity_result["severity"],
            "priority_score": severity_result["priority_score"],
            "reason": severity_result["reason"],
            "error": None,
            "model_name": "WasteWatch-YOLOv8",
            "is_ready": True,
        }

    except Exception as error:
        return {
            "success": False,
            "detections": [],
            "categories": [],
            "object_count": 0,
            "total_objects": 0,
            "is_mixed": False,
            "waste_type": None,
            "raw_label": None,
            "confidence_score": 0.0,
            "confidence_percent": 0.0,
            "severity": None,
            "priority_score": None,
            "reason": None,
            "error": str(error),
            "model_name": "WasteWatch-YOLOv8",
            "is_ready": False,
        }


if __name__ == "__main__":
    test_image = (
        BASE_DIR.parent / "test_waste.jpg"
    )

    if not test_image.is_file():
        print(f"Test image not found: {test_image}")
    else:
        result = predict_waste(test_image)

        print("\n===== AI WasteWatch Results =====")
        print("Success:", result["success"])
        print("Waste type:", result["waste_type"])
        print("Objects detected:", result["object_count"])
        print("Categories:", result["categories"])
        print("Mixed waste:", result["is_mixed"])
        print("Severity:", result["severity"])
        print("Priority score:", result["priority_score"])
        print("Reason:", result["reason"])

        if result["error"]:
            print("Error:", result["error"])

        for detection in result["detections"]:
            print(
                f"- {detection['waste_type']}: "
                f"{detection['confidence'] * 100:.1f}%"
            )
