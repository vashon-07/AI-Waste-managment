from ultralytics import YOLO
from pathlib import Path

# Path to trained WasteWatch model
MODEL_PATH = Path(__file__).parent / "models" / "best.pt"

# Load model once
model = YOLO(str(MODEL_PATH))

# WasteWatch 7 classes
CLASS_NAMES = {
    0: "Plastic",
    1: "Paper/Cardboard",
    2: "Glass",
    3: "Metal",
    4: "Organic",
    5: "Hazardous",
    6: "Other"
}


def predict_waste(image_path, confidence=0.25):
    """
    Detect waste objects in an image.
    Returns individual detections with class and confidence.
    """

    results = model.predict(
        source=image_path,
        conf=confidence,
        verbose=False
    )

    detections = []

    for result in results:
        if result.boxes is None:
            continue

        for box in result.boxes:
            class_id = int(box.cls[0])
            conf = float(box.conf[0])

            detections.append({
                "class_id": class_id,
                "waste_type": CLASS_NAMES.get(class_id, "Other"),
                "confidence": round(conf, 3)
            })

    return detections


if __name__ == "__main__":

    # Change this to a test image when testing
    test_image = "test_waste.jpg"

    detections = predict_waste(test_image)

    print("\n===== WasteWatch AI Result =====")

    if not detections:
        print("No waste detected.")
    else:
        for detection in detections:
            print(
                f"{detection['waste_type']} "
                f"- {detection['confidence'] * 100:.1f}%"
            )