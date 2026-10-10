# ai/severity.py
"""
AI WasteWatch - Waste Severity & Priority Scoring Engine

Heuristic scoring engine assessing waste hazard, quantity, mixed-waste
composition, and environmental/sanitation risks from detected waste objects.

All weights and thresholds are heuristic rules for municipal routing triage,
not scientifically validated risk measurements. An image alone does not establish
exact physical danger or collection urgency.
"""

from typing import List, Dict, Any


# ---------------------------------------------------------------------------
# HEURISTIC HAZARD REFERENCE MATRIX (0 - 100)
# ---------------------------------------------------------------------------
HAZARD_SCORES = {
    "Hazardous": 95,       # E-waste, chemicals, medical discard, batteries
    "Glass": 70,           # Broken glass, shards, physical laceration risk
    "Metal": 60,           # Sharp edges, rusty metals, tetanus hazard
    "Organic": 55,         # Food/vegetation, biological decay, pest attraction
    "Plastic": 50,         # Non-biodegradable polymers, drain blockage risk
    "Other": 40,           # Uncategorized municipal debris
    "Paper/Cardboard": 25  # Biodegradable, dry packaging, combustible
}
DEFAULT_HAZARD_SCORE = 35


def _calculate_box_iou(box1: Dict[str, float], box2: Dict[str, float]) -> float:
    """Calculate Intersection over Union (IoU) of two bounding box dicts."""
    if not isinstance(box1, dict) or not isinstance(box2, dict):
        return 0.0

    x1_a = box1.get("x1", 0.0)
    y1_a = box1.get("y1", 0.0)
    x2_a = box1.get("x2", 0.0)
    y2_a = box1.get("y2", 0.0)

    x1_b = box2.get("x1", 0.0)
    y1_b = box2.get("y1", 0.0)
    x2_b = box2.get("x2", 0.0)
    y2_b = box2.get("y2", 0.0)

    inter_x1 = max(x1_a, x1_b)
    inter_y1 = max(y1_a, y1_b)
    inter_x2 = min(x2_a, x2_b)
    inter_y2 = min(y2_a, y2_b)

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    area_a = max(0.0, (x2_a - x1_a) * (y2_a - y1_a))
    area_b = max(0.0, (x2_b - x1_b) * (y2_b - y1_b))
    union_area = area_a + area_b - inter_area

    if union_area <= 0:
        return 0.0
    return inter_area / union_area


def deduplicate_detections(detections: List[Dict[str, Any]], iou_threshold: float = 0.5) -> List[Dict[str, Any]]:
    """
    Avoid double-counting duplicate detections of the same waste category
    occupying overlapping bounding boxes.
    """
    if not detections:
        return []

    sorted_dets = sorted(
        detections,
        key=lambda d: d.get("confidence", 0.5),
        reverse=True
    )
    kept = []

    for det in sorted_dets:
        box = det.get("box")
        w_type = det.get("waste_type")
        is_dup = False

        if box and isinstance(box, dict):
            for accepted in kept:
                if accepted.get("waste_type") == w_type and accepted.get("box"):
                    if _calculate_box_iou(box, accepted["box"]) > iou_threshold:
                        is_dup = True
                        break

        if not is_dup:
            kept.append(det)

    return kept


def calculate_severity(detections: List[Dict[str, Any]], is_mixed: bool = False) -> Dict[str, Any]:
    """
    Calculate severity and priority score (0 - 100) from YOLO waste detections.

    Parameters:
        detections: List of detection dictionaries containing at least 'waste_type' and 'confidence'.
        is_mixed: Boolean indicator for mixed waste categories.

    Returns:
        Dict with keys:
            - 'severity': 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
            - 'priority_score': int between 0 and 100
            - 'reason': clear explanatory text
            - 'status': 'detected' | 'no_detection'
    """
    # -----------------------------------------------------------------------
    # 0. Empty detections guard
    # -----------------------------------------------------------------------
    if not detections:
        return {
            "severity": "LOW",
            "priority_score": 0,
            "reason": "No waste detected in image (visual detection unconfirmed)",
            "status": "no_detection"
        }

    # Deduplicate overlapping detections to avoid double-counting
    deduped = deduplicate_detections(detections)
    if not deduped:
        return {
            "severity": "LOW",
            "priority_score": 0,
            "reason": "No valid waste objects detected after deduplication",
            "status": "no_detection"
        }

    # -----------------------------------------------------------------------
    # 1. Hazard Score (Weight ~ 40%)
    # -----------------------------------------------------------------------
    hazard_values = [
        HAZARD_SCORES.get(d.get("waste_type", "Other"), DEFAULT_HAZARD_SCORE)
        for d in deduped
    ]
    highest_hazard = max(hazard_values)
    hazard_contribution = highest_hazard * 0.40

    # -----------------------------------------------------------------------
    # 2. Quantity Score (Weight ~ 25%)
    # -----------------------------------------------------------------------
    object_count = len(deduped)
    quantity_score = min(object_count * 4, 25)

    # -----------------------------------------------------------------------
    # 3. Mixed Waste Score (Weight ~ 15%)
    # -----------------------------------------------------------------------
    categories_present = set(d.get("waste_type") for d in deduped if d.get("waste_type"))
    has_mixed = is_mixed or (len(categories_present) > 1)
    mixed_score = 15 if has_mixed else 0

    # -----------------------------------------------------------------------
    # 4. Environmental & Sanitation Risk Score (Weight ~ 15%)
    # -----------------------------------------------------------------------
    environmental_score = 0
    if "Hazardous" in categories_present:
        environmental_score += 15
    if "Organic" in categories_present:
        environmental_score += 10
    if "Plastic" in categories_present:
        environmental_score += 5
    environmental_score = min(environmental_score, 15)

    # -----------------------------------------------------------------------
    # 5. Detection Confidence Factor
    # (Confidence measures model certainty, not physical danger. Low certainty
    # moderately tempers unverified high hazard claims without adding raw points.)
    # -----------------------------------------------------------------------
    confidences = [d.get("confidence", 0.5) for d in deduped]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.5

    if avg_confidence < 0.35:
        certainty_factor = 0.85
    elif avg_confidence < 0.55:
        certainty_factor = 0.95
    else:
        certainty_factor = 1.0

    # -----------------------------------------------------------------------
    # FINAL PRIORITY SCORE (0 - 100)
    # -----------------------------------------------------------------------
    raw_priority = (
        hazard_contribution
        + quantity_score
        + mixed_score
        + environmental_score
    ) * certainty_factor

    priority_score = max(0, min(100, round(raw_priority)))

    # -----------------------------------------------------------------------
    # SEVERITY CLASSIFICATION
    # -----------------------------------------------------------------------
    if priority_score >= 80:
        severity = "CRITICAL"
    elif priority_score >= 55:
        severity = "HIGH"
    elif priority_score >= 30:
        severity = "MEDIUM"
    else:
        severity = "LOW"

    # -----------------------------------------------------------------------
    # UNDERSTANDABLE REASON
    # -----------------------------------------------------------------------
    if "Hazardous" in categories_present:
        reason = "Hazardous waste detected (e-waste or toxic/chemical risk)"
    elif highest_hazard >= 70:
        reason = "Potential physical hazards detected (glass/metal shards)"
    elif has_mixed and object_count >= 4:
        reason = "High volume of mixed municipal waste requiring immediate clearance"
    elif has_mixed:
        reason = "Mixed municipal waste detected requiring sorting"
    elif "Organic" in categories_present:
        reason = "Organic waste accumulation with decomposition/sanitation risk"
    elif "Plastic" in categories_present:
        reason = "Plastic waste accumulation detected"
    elif priority_score >= 55:
        reason = "High accumulation of waste requiring scheduled priority collection"
    elif priority_score >= 30:
        reason = "Moderate municipal waste accumulation detected"
    else:
        reason = "Low accumulation of low-hazard municipal waste"

    return {
        "severity": severity,
        "priority_score": priority_score,
        "reason": reason,
        "status": "detected"
    }


# ---------------------------------------------------------------------------
# DIRECT MODULE TEST
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    sample_detections = [
        {
            "waste_type": "Paper/Cardboard",
            "confidence": 0.458,
            "box": {"x1": 205.4, "y1": 440.4, "x2": 291.7, "y2": 487.8}
        },
        {
            "waste_type": "Plastic",
            "confidence": 0.447,
            "box": {"x1": 241.9, "y1": 151.2, "x2": 453.0, "y2": 431.8}
        },
        {
            "waste_type": "Glass",
            "confidence": 0.432,
            "box": {"x1": 317.2, "y1": 406.2, "x2": 342.2, "y2": 437.2}
        }
    ]

    result = calculate_severity(sample_detections, is_mixed=True)
    print("\n===== WasteWatch Severity =====")
    print("Severity:      ", result["severity"])
    print("Priority Score:", result["priority_score"])
    print("Reason:        ", result["reason"])
    print("Status:        ", result["status"])