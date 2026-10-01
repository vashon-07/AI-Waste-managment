"""
AI Waste Microservice - FastAPI Service
Module: ai_service/app.py

Provides high-performance Vision Transformer (watersplash/waste-classification)
REST API endpoints for real-time waste image classification.
"""

import os
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .classifier import classifier_instance


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager:
    Loads the Hugging Face ViT model once when the service starts up
    and keeps it warm in memory for all incoming requests.
    """
    print("[*] FastAPI Service starting: Loading ViT model into memory...")
    classifier_instance.load_model()
    print("[OK] ViT Model loaded and ready for inference.")
    yield
    print("[*] FastAPI Service shutting down...")


app = FastAPI(
    title="AI Waste Classification Microservice",
    description="Pretrained Vision Transformer (watersplash/waste-classification) API for AI WasteWatch",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for cross-origin requests from frontend / Vercel
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PredictionItem(BaseModel):
    label: str
    score: float


class PredictResponse(BaseModel):
    success: bool
    raw_label: str
    waste_type: str
    confidence_score: float
    confidence_percent: float
    top_predictions: List[PredictionItem]
    severity: Optional[str] = None
    priority_score: Optional[float] = None
    model_name: str
    is_ready: bool


class Base64PredictRequest(BaseModel):
    image_base64: str


@app.get("/")
def root():
    return {
        "service": "AI Waste Classification Microservice",
        "model": classifier_instance.model_name,
        "status": "online",
        "docs_url": "/docs"
    }


@app.get("/health")
def health_check():
    """
    Health check endpoint returning whether the ViT model is loaded and ready in memory.
    """
    is_ready = classifier_instance.is_ready()
    return {
        "status": "healthy" if is_ready else "loading",
        "model_name": classifier_instance.model_name,
        "is_ready": is_ready
    }


@app.post("/predict", response_model=PredictResponse)
async def predict_image(
    file: Optional[UploadFile] = File(None),
    image_base64: Optional[str] = Form(None)
):
    """
    Classify an uploaded waste image using the in-memory Hugging Face ViT model.
    Accepts multipart/form-data with either a file upload or base64 string.
    """
    if not classifier_instance.is_ready():
        raise HTTPException(
            status_code=503,
            detail="Vision Transformer model is still loading. Please try again in a few moments."
        )

    try:
        # 1. Read binary image from file upload
        if file is not None:
            image_bytes = await file.read()
            if not image_bytes:
                raise HTTPException(status_code=400, detail="Empty file provided.")
            result = classifier_instance.predict(image_bytes)
            return result

        # 2. Read base64 image data
        if image_base64:
            result = classifier_instance.predict(image_base64)
            return result

        raise HTTPException(
            status_code=400,
            detail="Please provide an image file (multipart 'file') or 'image_base64' string."
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")


@app.post("/predict-json", response_model=PredictResponse)
async def predict_image_json(payload: Base64PredictRequest):
    """
    Classify a waste image from a JSON payload containing base64 data.
    """
    if not classifier_instance.is_ready():
        raise HTTPException(
            status_code=503,
            detail="Vision Transformer model is still loading. Please try again in a few moments."
        )

    try:
        result = classifier_instance.predict(payload.image_base64)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Inference error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("ai_service.app:app", host="0.0.0.0", port=8000, reload=False)
