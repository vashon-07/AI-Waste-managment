"""
AI Waste Microservice - FastAPI Service
Module: ai_service/app.py

Provides high-performance Vision Transformer (watersplash/waste-classification)
REST API endpoints for real-time waste image classification.
"""

import os
import binascii
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, File, UploadFile, HTTPException, Form, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import UnidentifiedImageError

try:
    from .classifier import classifier_instance
except ImportError:
    from classifier import classifier_instance

# 1. Configuration Constants & Environment Variables
MAX_FILE_SIZE = int(os.getenv("MAX_FILE_SIZE_BYTES", 10 * 1024 * 1024))  # 10 MB limit
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/bmp",
    "application/octet-stream"  # Used when clients don't set explicit image mime
}

# 2. CORS configuration (Production Vercel domain, local dev, and Vercel preview deployments)
DEFAULT_ALLOWED_ORIGINS = [
    "https://ai-waste-managment.vercel.app",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

env_origins = os.getenv("ALLOWED_ORIGINS", "")
if env_origins:
    extra_origins = [orig.strip() for orig in env_origins.split(",") if orig.strip()]
    allowed_origins = list(set(DEFAULT_ALLOWED_ORIGINS + extra_origins))
else:
    allowed_origins = DEFAULT_ALLOWED_ORIGINS

# Regex to safely match any Vercel preview / branch deployment (e.g. https://ai-waste-managment-git-main-xxx.vercel.app)
VERCEL_PREVIEW_REGEX = r"^https://[a-zA-Z0-9_\-]+\.vercel\.app$"


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

# CORS Middleware: Exact origins for production & local dev, regex for preview deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=VERCEL_PREVIEW_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
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
def health_check(response: Response):
    """
    Health check endpoint:
    Returns HTTP 200 when the ViT model is loaded and ready in memory.
    Returns HTTP 503 while the model weights are initializing.
    """
    is_ready = classifier_instance.is_ready()
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "loading",
            "model_name": classifier_instance.model_name,
            "is_ready": False,
            "message": "Vision Transformer model is still loading into memory."
        }

    return {
        "status": "healthy",
        "model_name": classifier_instance.model_name,
        "is_ready": True
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
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vision Transformer model is still loading. Please try again in a few moments."
        )

    try:
        # 1. Process Multipart File Upload
        if file is not None:
            # Check content-type if provided
            if file.content_type and file.content_type.lower() not in ALLOWED_MIME_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported file type '{file.content_type}'. Please upload a valid image (JPEG, PNG, WebP)."
                )

            image_bytes = await file.read()

            # Empty file check
            if not image_bytes:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Empty file uploaded. Please select a valid image."
                )

            # 10 MB Size limit check
            if len(image_bytes) > MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"File too large ({len(image_bytes)/(1024*1024):.1f} MB). Maximum allowed size is {MAX_FILE_SIZE/(1024*1024):.0f} MB."
                )

            # Run inference
            result = classifier_instance.predict(image_bytes)
            return result

        # 2. Process Base64 Form Field
        if image_base64:
            if len(image_base64) > MAX_FILE_SIZE * 1.4:  # Account for base64 encoding overhead
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail="Base64 payload exceeds the 10 MB limit."
                )

            result = classifier_instance.predict(image_base64)
            return result

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide an image file ('file' multipart) or 'image_base64' string."
        )

    except HTTPException:
        raise
    except (UnidentifiedImageError, ValueError, IOError, binascii.Error) as img_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or corrupt image format: {str(img_err)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inference error: {str(e)}"
        )


@app.post("/predict-json", response_model=PredictResponse)
async def predict_image_json(payload: Base64PredictRequest):
    """
    Classify a waste image from a JSON payload containing base64 data.
    """
    if not classifier_instance.is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vision Transformer model is still loading. Please try again in a few moments."
        )

    try:
        if len(payload.image_base64) > MAX_FILE_SIZE * 1.4:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Base64 payload exceeds the 10 MB limit."
            )

        result = classifier_instance.predict(payload.image_base64)
        return result
    except HTTPException:
        raise
    except (UnidentifiedImageError, ValueError, IOError, binascii.Error) as img_err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or corrupt image format: {str(img_err)}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Inference error: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("ai_service.app:app", host="0.0.0.0", port=port, reload=False)
