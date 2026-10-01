"""
AI Waste Microservice - Production Suite Tests
Tests the 5 production requirements:
1. /health status codes (503 while loading, 200 when ready)
2. Valid plastic image prediction
3. Invalid PDF file rejection (HTTP 400)
4. Corrupt image rejection (HTTP 400)
5. Oversized image rejection (HTTP 413)
"""

import os
import sys
import io
import json
from fastapi.testclient import TestClient

# Ensure workspace root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ai_service.app import app
from ai_service.classifier import classifier_instance

def run_tests():
    print("==================================================================")
    print("      STANDALONE AI SERVICE PRODUCTION READINESS TEST SUITE       ")
    print("==================================================================")

    # --- TEST 1: /health while model is not ready ---
    print("\n>>> [TEST 1] Testing /health before model is loaded...")
    classifier_instance._is_ready = False
    classifier_instance._pipeline = None
    client = TestClient(app)
    health_loading = client.get("/health")
    print(f"Health status (loading): {health_loading.status_code}")
    print(f"Health response: {health_loading.json()}")
    assert health_loading.status_code == 503, f"Expected 503, got {health_loading.status_code}"
    print(" -> [PASS] Health check returns 503 when model is not ready.")

    # Now load model
    print("\n>>> Loading ViT model into memory...")
    classifier_instance.load_model()
    assert classifier_instance.is_ready(), "Model failed to load"

    # --- TEST 2: /health when model is loaded ---
    print("\n>>> [TEST 2] Testing /health when model is loaded...")
    health_ready = client.get("/health")
    print(f"Health status (ready): {health_ready.status_code}")
    print(f"Health response: {health_ready.json()}")
    assert health_ready.status_code == 200, f"Expected 200, got {health_ready.status_code}"
    assert health_ready.json()["is_ready"] is True
    print(" -> [PASS] Health check returns 200 when model is ready.")

    # --- TEST 3: Valid plastic bottle image ---
    print("\n>>> [TEST 3] Testing /predict with valid plastic bottle image...")
    plastic_path = os.path.join(BASE_DIR, "ai", "test", "sample_plastic_bottle.jpg")
    with open(plastic_path, "rb") as f:
        valid_res = client.post(
            "/predict",
            files={"file": ("plastic_bottle.jpg", f.read(), "image/jpeg")}
        )
    print(f"Predict status (valid): {valid_res.status_code}")
    valid_data = valid_res.json()
    print("Valid Prediction Output:")
    print(json.dumps(valid_data, indent=2))
    assert valid_res.status_code == 200, f"Expected 200, got {valid_res.status_code}"
    assert valid_data["success"] is True
    assert valid_data["raw_label"] == "plastic"
    assert valid_data["confidence_score"] > 0.90
    print(" -> [PASS] Valid plastic image classified with high confidence.")

    # --- TEST 4: Invalid PDF file ---
    print("\n>>> [TEST 4] Testing /predict with invalid PDF file...")
    fake_pdf_content = b"%PDF-1.4 Fake PDF content that is not an image"
    pdf_res = client.post(
        "/predict",
        files={"file": ("report.pdf", fake_pdf_content, "application/pdf")}
    )
    print(f"Predict status (PDF): {pdf_res.status_code}")
    print(f"PDF Response: {pdf_res.json()}")
    assert pdf_res.status_code == 400, f"Expected 400, got {pdf_res.status_code}"
    print(" -> [PASS] Invalid PDF file rejected with HTTP 400.")

    # --- TEST 5: Corrupt image file ---
    print("\n>>> [TEST 5] Testing /predict with corrupt image data...")
    corrupt_bytes = b"\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01CORRUPT_BYTES_TRUNCATED"
    corrupt_res = client.post(
        "/predict",
        files={"file": ("corrupt.jpg", corrupt_bytes, "image/jpeg")}
    )
    print(f"Predict status (Corrupt): {corrupt_res.status_code}")
    print(f"Corrupt Response: {corrupt_res.json()}")
    assert corrupt_res.status_code == 400, f"Expected 400, got {corrupt_res.status_code}"
    print(" -> [PASS] Corrupted image rejected with HTTP 400.")

    # --- TEST 6: Oversized image (> 10 MB) ---
    print("\n>>> [TEST 6] Testing /predict with oversized payload (> 10 MB)...")
    large_payload = b"0" * (11 * 1024 * 1024)  # 11 MB
    oversized_res = client.post(
        "/predict",
        files={"file": ("huge_photo.jpg", large_payload, "image/jpeg")}
    )
    print(f"Predict status (Oversized): {oversized_res.status_code}")
    print(f"Oversized Response: {oversized_res.json()}")
    assert oversized_res.status_code == 413, f"Expected 413, got {oversized_res.status_code}"
    print(" -> [PASS] Oversized image (>10MB) rejected with HTTP 413.")

    print("\n==================================================================")
    print("          ALL PRODUCTION TEST SCENARIOS PASSED SUCCESSFULLY!      ")
    print("==================================================================")

if __name__ == "__main__":
    run_tests()
