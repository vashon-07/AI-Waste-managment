"""
AI Waste Microservice - Vision Transformer Classifier
Module: ai_service/classifier.py

Encapsulates Hugging Face Vision Transformer (watersplash/waste-classification).
Loads once into memory on service startup and stays warm for all requests.
"""

import io
import os
import base64
import logging
from typing import Dict, Any, List, Union
from PIL import Image

logger = logging.getLogger("AIServiceClassifier")
logging.basicConfig(level=logging.INFO)

DEFAULT_HF_MODEL = "watersplash/waste-classification"

# Normalization mapping for waste types
CATEGORY_MAPPING = {
    # Organic / Biodegradable
    "organic": ("Organic Waste", "Medium", 65.0),
    "biodegradable": ("Organic Waste", "Medium", 65.0),
    "biological": ("Organic Waste", "Low", 40.0),
    "food": ("Organic Waste", "Medium", 65.0),
    "vegetation": ("Organic Waste", "Low", 45.0),
    
    # Recyclable / Plastic
    "plastic": ("Plastic Waste", "High", 78.0),
    "polythene": ("Plastic Waste", "High", 80.0),
    "bottle": ("Plastic / Recyclable", "Medium", 60.0),
    
    # Paper / Cardboard
    "paper": ("Paper & Cardboard", "Low", 45.0),
    "cardboard": ("Paper & Cardboard", "Low", 45.0),
    
    # Metal
    "metal": ("Metal Waste", "Medium", 68.0),
    "can": ("Metal Waste", "Medium", 62.0),
    "aluminium": ("Metal Waste", "Medium", 65.0),
    
    # Glass
    "glass": ("Glass Waste", "Medium", 58.0),
    "white-glass": ("Glass Waste", "Medium", 55.0),
    "brown-glass": ("Glass Waste", "Medium", 55.0),
    "green-glass": ("Glass Waste", "Medium", 55.0),
    
    # Clothes / Shoes
    "clothes": ("Textile / Clothes", "Low", 40.0),
    "shoes": ("Footwear / Dry Waste", "Low", 45.0),
    
    # Electronic & Hazardous
    "electronic": ("E-Waste", "High", 85.0),
    "e-waste": ("E-Waste", "High", 88.0),
    "battery": ("Hazardous Waste", "Critical", 95.0),
    "hazardous": ("Hazardous Waste", "Critical", 95.0),
    "medical": ("Hazardous Waste", "Critical", 96.0),
    "chemical": ("Hazardous Waste", "Critical", 95.0),
    
    # Non-recyclable / General
    "non-recyclable": ("Non-Recyclable Waste", "Medium", 65.0),
    "non_recyclable": ("Non-Recyclable Waste", "Medium", 65.0),
    "recyclable": ("Recyclable Waste", "Medium", 60.0),
    "trash": ("Mixed Municipal Waste", "Medium", 65.0),
    "waste": ("Mixed Municipal Waste", "Medium", 60.0),
}


class ServiceWasteClassifier:
    """FastAPI Service Classifier singleton for watersplash/waste-classification."""

    def __init__(self, model_name: str = DEFAULT_HF_MODEL):
        self.model_name = model_name
        self._pipeline = None
        self._is_ready = False

    def load_model(self):
        """Loads the ViT pipeline into memory synchronously upon server startup."""
        if self._is_ready and self._pipeline is not None:
            return

        logger.info(f"[*] Initializing Hugging Face pipeline '{self.model_name}'...")
        from transformers import pipeline

        self._pipeline = pipeline(
            task="image-classification",
            model=self.model_name
        )
        self._is_ready = True
        logger.info(f"[OK] Vision Transformer model '{self.model_name}' loaded in memory.")

    def is_ready(self) -> bool:
        return self._is_ready and self._pipeline is not None

    def _prepare_image(self, image_input: Union[str, bytes, Image.Image]) -> Image.Image:
        if isinstance(image_input, Image.Image):
            return image_input.convert("RGB")

        if isinstance(image_input, bytes):
            return Image.open(io.BytesIO(image_input)).convert("RGB")

        if isinstance(image_input, str):
            if image_input.startswith("data:image") or ";base64," in image_input:
                b64_str = image_input.split(";base64,")[-1]
                return Image.open(io.BytesIO(base64.b64decode(b64_str))).convert("RGB")
            if os.path.exists(image_input):
                return Image.open(image_input).convert("RGB")
            # Raw base64 string
            return Image.open(io.BytesIO(base64.b64decode(image_input))).convert("RGB")

        raise ValueError(f"Unsupported image type: {type(image_input)}")

    def _map_label(self, raw_label: str, raw_score: float) -> tuple:
        label_clean = raw_label.lower().strip().replace("_", " ").replace("-", " ")
        for key, (wtype, sev, prio) in CATEGORY_MAPPING.items():
            if key in label_clean:
                adjusted_prio = round(min(max(prio * raw_score, 10.0), 100.0), 2)
                return wtype, sev, adjusted_prio

        formatted_title = raw_label.replace("_", " ").title() + " Waste"
        return formatted_title, "Medium", round(raw_score * 70.0, 2)

    def predict(self, image_input: Union[str, bytes, Image.Image], top_k: int = 5) -> Dict[str, Any]:
        """Runs ViT inference on the provided image input using warm in-memory model."""
        if not self.is_ready():
            raise RuntimeError("Vision Transformer model is not loaded yet.")

        pil_img = self._prepare_image(image_input)
        raw_results = self._pipeline(pil_img, top_k=top_k)

        top_pred = raw_results[0]
        raw_label = top_pred.get("label", "Unknown")
        confidence = float(top_pred.get("score", 0.0))

        waste_type, severity, priority_score = self._map_label(raw_label, confidence)

        return {
            "success": True,
            "raw_label": raw_label,
            "waste_type": waste_type,
            "confidence_score": round(confidence, 4),
            "confidence_percent": round(confidence * 100, 2),
            "severity": severity,
            "priority_score": priority_score,
            "top_predictions": [
                {"label": r.get("label", ""), "score": round(float(r.get("score", 0.0)), 4)}
                for r in raw_results
            ],
            "model_name": self.model_name,
            "is_ready": True
        }


# Singleton instance
classifier_instance = ServiceWasteClassifier()
