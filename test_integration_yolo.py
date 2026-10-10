# test_integration_yolo.py
"""
AI WasteWatch - Comprehensive Integration & Verification Test Suite

Verifies:
1. Model loading from ai/models/best.pt with 7 classes
2. Structured YOLO detections on actual test image
3. Multi-category representation & mixed waste flag
4. Severity engine calculates valid priority scores (0 - 100) & severity tiers
5. Empty detections handled gracefully without crash
6. Invalid images / inference failures return explicit errors
7. Flask app import and configuration
8. /submit-report route stores YOLO predictions & priority info
9. Existing database records preservation
10. Dashboard template rendering with priority matrix
"""

import os
import sys
import io
import json
import sqlite3
import tempfile
import shutil
from pathlib import Path
from PIL import Image

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 1. Imports
from ai.predict import predict_waste, MODEL_PATH, CLASS_NAMES, get_model
from ai.severity import calculate_severity, deduplicate_detections
import app as app_module
from app import app
import cloud_db


def run_all_tests():
    print("=" * 70)
    print("      AI WASTEWATCH - FULL YOLO INTEGRATION TEST SUITE")
    print("=" * 70)

    results = []

    # -------------------------------------------------------------------
    # TEST 1: Model loads from ai/models/best.pt
    # -------------------------------------------------------------------
    print("\n[TEST 1] Verifying YOLO model weights loading from ai/models/best.pt...")
    try:
        assert MODEL_PATH.exists(), f"Model file not found at {MODEL_PATH}"
        model = get_model()
        assert model is not None, "Model failed to load"
        names = model.names
        assert len(names) == 7, f"Expected 7 classes, got {len(names)}: {names}"
        for cid, cname in CLASS_NAMES.items():
            assert names[cid] == cname, f"Class ID {cid} mismatch: {names[cid]} != {cname}"
        print(f"  [PASS] Model loaded successfully: {names}")
        results.append(("1. Model loads from ai/models/best.pt with 7 classes", True))
    except Exception as e:
        print(f"  [FAIL] {e}")
        results.append(("1. Model loads from ai/models/best.pt with 7 classes", False))

    # -------------------------------------------------------------------
    # TEST 2: Actual test image produces structured YOLO detections
    # -------------------------------------------------------------------
    print("\n[TEST 2] Running prediction on actual test image (test_waste.jpg)...")
    test_img = PROJECT_ROOT / "test_waste.jpg"
    try:
        assert test_img.exists(), f"Test image not found at {test_img}"
        pred = predict_waste(str(test_img), confidence=0.25)
        assert pred["success"] is True, f"Prediction reported failure: {pred.get('error')}"
        assert pred["object_count"] > 0, "No objects detected in test_waste.jpg"
        assert len(pred["detections"]) == pred["object_count"]

        # Validate detection schema
        first_det = pred["detections"][0]
        for key in ("class_id", "waste_type", "confidence", "box"):
            assert key in first_det, f"Missing key '{key}' in detection: {first_det}"
        for b_key in ("x1", "y1", "x2", "y2"):
            assert b_key in first_det["box"], f"Missing box coordinate '{b_key}'"

        print(f"  [PASS] Detected {pred['object_count']} objects.")
        print(f"         Sample detection: {first_det}")
        results.append(("2. Test image produces structured YOLO detections", True))
    except Exception as e:
        print(f"  [FAIL] {e}")
        results.append(("2. Test image produces structured YOLO detections", False))

    # -------------------------------------------------------------------
    # TEST 3: Multiple categories represented correctly
    # -------------------------------------------------------------------
    print("\n[TEST 3] Verifying multi-category waste representation...")
    try:
        categories = pred["categories"]
        is_mixed = pred["is_mixed"]
        print(f"  Detected Categories: {categories}")
        print(f"  Is Mixed: {is_mixed}")
        assert len(categories) > 1, f"Expected multiple categories, got: {categories}"
        assert is_mixed is True, "is_mixed should be True for multi-category waste"
        assert "Plastic" in categories or "Paper/Cardboard" in categories or "Glass" in categories
        print("  [PASS] Multiple categories and mixed waste flag verified.")
        results.append(("3. Multiple categories represented correctly", True))
    except Exception as e:
        print(f"  [FAIL] {e}")
        results.append(("3. Multiple categories represented correctly", False))

    # -------------------------------------------------------------------
    # TEST 4: Severity engine produces valid score (0-100) and severity
    # -------------------------------------------------------------------
    print("\n[TEST 4] Verifying severity calculation and priority scoring...")
    try:
        severity = pred["severity"]
        score = pred["priority_score"]
        reason = pred["reason"]

        assert severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL"), f"Unexpected severity tier: {severity}"
        assert isinstance(score, (int, float)) and 0 <= score <= 100, f"Score out of bounds (0-100): {score}"
        assert isinstance(reason, str) and len(reason) > 5, f"Missing or empty reason: {reason}"

        print(f"  Severity:       {severity}")
        print(f"  Priority Score: {score}/100")
        print(f"  Reason:         {reason}")
        print("  [PASS] Valid priority score and understandable severity reason generated.")
        results.append(("4. Severity engine produces valid score (0-100) and reason", True))
    except Exception as e:
        print(f"  [FAIL] {e}")
        results.append(("4. Severity engine produces valid score (0-100) and reason", False))

    # -------------------------------------------------------------------
    # TEST 5: Empty detections do not crash
    # -------------------------------------------------------------------
    print("\n[TEST 5] Testing empty detections handling...")
    try:
        # Test severity engine directly on empty list
        empty_sev = calculate_severity([])
        assert empty_sev["severity"] in ("LOW", "NONE"), f"Expected LOW/NONE on empty: {empty_sev}"
        assert empty_sev["priority_score"] == 0, f"Expected 0 priority score, got {empty_sev['priority_score']}"
        assert empty_sev["status"] == "no_detection"

        # Test predict_waste with a synthetic solid white image
        blank_img = Image.new("RGB", (200, 200), color=(255, 255, 255))
        buf = io.BytesIO()
        blank_img.save(buf, format="JPEG")
        buf_bytes = buf.getvalue()

        blank_pred = predict_waste(buf_bytes, confidence=0.85)
        assert blank_pred["success"] is True
        assert blank_pred["object_count"] == 0
        assert blank_pred["severity"] in ("LOW", "NONE")
        assert blank_pred["priority_score"] == 0
        print(f"  [PASS] Empty detections handled cleanly: {blank_pred['reason']}")
        results.append(("5. Empty detections handled safely without crashing", True))
    except Exception as e:
        print(f"  [FAIL] {e}")
        results.append(("5. Empty detections handled safely without crashing", False))

    # -------------------------------------------------------------------
    # TEST 6: Invalid images and inference failures return explicit errors
    # -------------------------------------------------------------------
    print("\n[TEST 6] Testing invalid image and inference failure handling...")
    try:
        # Corrupted bytes
        corrupt_res = predict_waste(b"not an image file")
        assert corrupt_res["success"] is False, "Expected success=False on corrupted bytes"
        assert corrupt_res["error"] is not None, "Expected explicit error message"
        assert corrupt_res["severity"] is None, "Inference failure must NOT fabricate a severity tier"

        # Non-existent file path
        missing_res = predict_waste("non_existent_image_12345.jpg")
        assert missing_res["success"] is False
        assert missing_res["error"] is not None

        print(f"  [PASS] Explicit error returned on invalid input: {corrupt_res['error']}")
        results.append(("6. Invalid images and inference failures return explicit errors", True))
    except Exception as e:
        print(f"  [FAIL] {e}")
        results.append(("6. Invalid images and inference failures return explicit errors", False))

    # -------------------------------------------------------------------
    # TEST 7: Flask can import AI modules using project Python environment
    # -------------------------------------------------------------------
    print("\n[TEST 7] Verifying Flask import and application configuration...")
    try:
        assert app is not None
        assert "UPLOAD_FOLDER" in app.config
        assert callable(app_module.predict_waste)
        print("  [PASS] Flask app successfully imports AI predict_waste.")
        results.append(("7. Flask application imports AI modules cleanly", True))
    except Exception as e:
        print(f"  [FAIL] {e}")
        results.append(("7. Flask application imports AI modules cleanly", False))

    # -------------------------------------------------------------------
    # TEST 8: /submit-report route stores YOLO predictions & priority info
    # -------------------------------------------------------------------
    print("\n[TEST 8] Verifying /submit-report route with YOLO inference in isolated DB...")
    tmp_dir = tempfile.mkdtemp(prefix="wastewatch_test_")
    tmp_db = os.path.join(tmp_dir, "test.db")
    orig_db = app_module.DB_PATH
    orig_local_db = cloud_db.LOCAL_DB_PATH

    try:
        app_module.DB_PATH = tmp_db
        cloud_db.LOCAL_DB_PATH = tmp_db
        app_module.init_db()

        client = app.test_client()

        with open(test_img, "rb") as f:
            img_data = f.read()

        response = client.post(
            "/submit-report",
            data={
                "reporter_name": "Kavita Rao",
                "reporter_phone": "9123456789",
                "description": "Scattered garbage near school junction",
                "address": "Beach Road, Visakhapatnam",
                "latitude": "17.7215",
                "longitude": "83.3150",
                "_image_provided": "1",
                "image": (io.BytesIO(img_data), "waste_sample.jpg")
            },
            content_type="multipart/form-data"
        )

        assert response.status_code == 200, f"Expected 200 OK, got {response.status_code}"
        html = response.get_data(as_text=True)
        assert "Report submitted successfully" in html, "Success message missing in response"

        # Verify saved record in test SQLite DB
        conn = sqlite3.connect(tmp_db)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM reports WHERE reporter_name = 'Kavita Rao' ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()

        assert row is not None, "Report was not inserted into database"
        assert row["waste_type"] is not None and "Waste" in row["waste_type"]
        assert row["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
        assert row["priority_score"] > 0
        assert row["reason"] is not None and len(row["reason"]) > 3

        print(f"  Inserted Record: Waste Type = {row['waste_type']}, Severity = {row['severity']}, Priority Score = {row['priority_score']}%, Reason = {row['reason']}")
        print("  [PASS] /submit-report saved full YOLO detection & priority matrix.")
        results.append(("8. /submit-report stores correct YOLO results and reason in database", True))
    except Exception as e:
        print(f"  [FAIL] {e}")
        results.append(("8. /submit-report stores correct YOLO results and reason in database", False))
    finally:
        app_module.DB_PATH = orig_db
        cloud_db.LOCAL_DB_PATH = orig_local_db
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # -------------------------------------------------------------------
    # TEST 9: Existing database records remain intact
    # -------------------------------------------------------------------
    print("\n[TEST 9] Verifying real wastewatch.db records remain intact...")
    real_db_path = PROJECT_ROOT / "wastewatch.db"
    try:
        assert real_db_path.exists(), f"Real database not found at {real_db_path}"
        conn = sqlite3.connect(str(real_db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM reports")
        total_reports = cur.fetchone()[0]
        cur.execute("PRAGMA table_info(reports)")
        col_names = [c[1] for c in cur.fetchall()]
        conn.close()

        assert total_reports > 0, "No records found in wastewatch.db"
        assert "reason" in col_names, "Column 'reason' not present in schema"
        print(f"  Real database contains {total_reports} reports. Columns: {col_names}")
        print("  [PASS] Existing records and schema integrity intact.")
        results.append(("9. Existing database records and schema remain intact", True))
    except Exception as e:
        print(f"  [FAIL] {e}")
        results.append(("9. Existing database records and schema remain intact", False))

    # -------------------------------------------------------------------
    # TEST 10: Frontend and Dashboard functionality renders properly
    # -------------------------------------------------------------------
    print("\n[TEST 10] Verifying Officer & Citizen Dashboard rendering...")
    try:
        client = app.test_client()

        # Set officer session
        with client.session_transaction() as sess:
            sess["officer_name"] = "Chief Officer Rajesh Sharma"
            sess["officer_ward"] = "Ward 1 - Central Zone"

        dash_res = client.get("/officer-dashboard")
        assert dash_res.status_code == 200, f"Officer dashboard returned {dash_res.status_code}"
        dash_html = dash_res.get_data(as_text=True)
        assert "Municipal Waste Hotspot Map" in dash_html
        assert "AI WasteWatch" in dash_html
        assert "Priority" in dash_html

        # Test API classify endpoint with real test image
        with open(test_img, "rb") as f:
            api_res = client.post("/api/classify", data={"image": (io.BytesIO(f.read()), "test.jpg")})
        assert api_res.status_code == 200, f"/api/classify returned {api_res.status_code}"
        api_json = api_res.get_json()
        assert api_json["success"] is True
        assert "detections" in api_json
        assert "priority_score" in api_json

        print("  [PASS] Officer dashboard and /api/classify endpoint verified successfully.")
        results.append(("10. Frontend dashboards and /api/classify work properly", True))
    except Exception as e:
        print(f"  [FAIL] {e}")
        results.append(("10. Frontend dashboards and /api/classify work properly", False))

    # -------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("                     TEST SUITE SUMMARY")
    print("=" * 70)
    all_passed = True
    for name, passed in results:
        status_str = "PASS" if passed else "FAIL"
        print(f"  [{status_str:4}] {name}")
        if not passed:
            all_passed = False

    print("=" * 70)
    if all_passed:
        print("  RESULT: ALL 10 TESTS PASSED SUCCESSFULLY! (10/10)")
    else:
        print("  RESULT: SOME TESTS FAILED. PLEASE REVIEW.")
    print("=" * 70)

    return all_passed


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
