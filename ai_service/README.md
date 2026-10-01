---
title: AI Waste Classifier
emoji: ♻️
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
---

# AI Waste Classifier Microservice

Pretrained Vision Transformer (`watersplash/waste-classification`) REST API microservice for real-time municipal waste image classification.

## API Endpoints

### 1. Health Check
`GET /health`
* **Response `200 OK`**: Model ready in memory.
* **Response `503 Service Unavailable`**: Model initializing.

```bash
curl -X GET "https://abhi42488-ai-waste-classifier.hf.space/health"
```

### 2. Predict Waste Category
`POST /predict`
* **Accepts**: `multipart/form-data` with `file` (image binary) or `image_base64` (string).
* **Max Payload**: 10 MB.
* **Returns**: JSON containing `raw_label`, `waste_type`, `confidence_score`, `severity`, `priority_score`, and `top_predictions`.

```bash
curl -X POST "https://abhi42488-ai-waste-classifier.hf.space/predict" \
     -F "file=@sample_plastic_bottle.jpg"
```

### 3. Interactive Documentation
* Swagger UI: `/docs`
* OpenAPI JSON: `/openapi.json`
