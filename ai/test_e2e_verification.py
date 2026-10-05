import os
import sys
import json
import io
import sqlite3
import tempfile
import shutil

# Ensure workspace root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import app as app_module
import cloud_db
from app import app
from ai.classifier import get_classifier
from ai.predict import predict_waste

def main():
    # ------------------------------------------------------------------
    # Use a throwaway temp database so we never touch wastewatch.db
    # ------------------------------------------------------------------
    tmp_dir = tempfile.mkdtemp(prefix="wastewatch_test_")
    tmp_db  = os.path.join(tmp_dir, "wastewatch_test.db")
    original_db_path = getattr(app_module, "DB_PATH", None)
    original_cloud_db_path = cloud_db.LOCAL_DB_PATH
    if original_db_path:
        app_module.DB_PATH = tmp_db
    cloud_db.LOCAL_DB_PATH = tmp_db
    cloud_db.init_cloud_db()
    app_module.init_db()   # create schema in temp DB

    try:
        _run_tests(tmp_db)
    finally:
        if original_db_path:
            app_module.DB_PATH = original_db_path  # restore
        cloud_db.LOCAL_DB_PATH = original_cloud_db_path
        shutil.rmtree(tmp_dir, ignore_errors=True)
        print("\n[TEST] Temp database cleaned up.")


def _run_tests(tmp_db: str):
    # Ensure ViT model pipeline is loaded
    classifier = get_classifier()
    classifier._load_pipeline_sync()

    image_path = os.path.abspath(r'ai/test/sample_plastic_bottle.jpg')
    assert os.path.exists(image_path), f'Image not found at {image_path}'

    print('==================================================================')
    print('        FINAL END-TO-END VISION TRANSFORMER (ViT) VERIFICATION   ')
    print('==================================================================')

    # Step 1 & 2: Direct Model Inference
    print('\n>>> [STEP 1 & 2] Running ViT Inference via predict_waste()...')
    direct_res = predict_waste(image_path)
    print('Direct Inference Result:')
    print(json.dumps(direct_res, indent=2))

    # Step 3, 4, 5, 6, 7: Confirm Values
    raw_label = direct_res['raw_label']
    confidence_score = direct_res['confidence_score']
    waste_type = direct_res['waste_type']
    severity = direct_res['severity']
    priority_score = direct_res['priority_score']
    is_fallback = direct_res.get('is_fallback', False)

    print('\nKey Metric Assertions:')
    print(f' - raw_label:          {raw_label} (Expected: "plastic")')
    print(f' - confidence_score:   {confidence_score:.4f} ({confidence_score*100:.2f}%)')
    print(f' - waste_type:         {waste_type}')
    print(f' - severity:           {severity}')
    print(f' - priority_score:     {priority_score}')
    print(f' - is_fallback:        {is_fallback}')

    # Step 8: Flask API Endpoint (/api/classify)
    print('\n>>> [STEP 8] Testing API Endpoint POST /api/classify...')
    client = app.test_client()
    with open(image_path, 'rb') as f:
        api_response = client.post('/api/classify', data={'image': (io.BytesIO(f.read()), 'plastic_bottle.jpg')})

    print(f'API HTTP Status Code: {api_response.status_code}')
    api_data = api_response.get_json()
    print('Final API JSON Response:')
    print(json.dumps(api_data, indent=2))

    # Step 9: Report Submission (/submit-report)
    print('\n>>> [STEP 9] Submitting Citizen Report via POST /submit-report...')
    with open(image_path, 'rb') as f:
        submit_response = client.post('/submit-report', data={
            'reporter_name': 'Aarav Sharma',
            'reporter_phone': '9876543210',
            'description': 'Discarded plastic bottles accumulating on roadside curb',
            'address': 'MG Road, Ward 4, Bengaluru',
            'latitude': '12.9716',
            'longitude': '77.5946',
            '_image_provided': '1',
            'image': (io.BytesIO(f.read()), 'plastic_bottle.jpg')
        })
    print(f'Submit Report HTTP Status Code: {submit_response.status_code}')

    # Step 10: Verify SQLite Database Record
    print('\n>>> [STEP 10] Verifying SQLite Database Record in temp test DB...')
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT * FROM reports ORDER BY id DESC LIMIT 1')
    db_record = dict(cur.fetchone())
    conn.close()

    # Mask long base64 string for display
    display_db_record = dict(db_record)
    if 'image_path' in display_db_record and len(str(display_db_record['image_path'])) > 60:
        display_db_record['image_path'] = display_db_record['image_path'][:45] + '... [base64 image data]'

    print('Persisted SQLite Record:')
    print(json.dumps(display_db_record, indent=2))

    # Step 11: Verify Citizen Reporting Page Output
    print('\n>>> [STEP 11] Verifying Citizen Reporting Page UI Result...')
    html_output = submit_response.get_data(as_text=True)
    has_success = 'Report submitted successfully' in html_output
    has_waste_type = db_record['waste_type'] in html_output

    print(f' - Success message rendered in HTML: {has_success}')
    print(f' - Identified waste type ({db_record["waste_type"]}) present in HTML: {has_waste_type}')

    # Final Verification Checklist
    print('\n==================================================================')
    print('                     VERIFICATION CHECKLIST                      ')
    print('==================================================================')
    checks = [
        ('raw_label is actual ViT model label ("plastic")', raw_label == 'plastic'),
        ('confidence_score is actual ViT probability (> 0.90)', confidence_score > 0.90),
        ('waste_type is normalized application category', waste_type == 'Plastic Waste'),
        ('severity is application heuristic logic', severity in ['Low', 'Medium', 'High', 'Critical']),
        ('priority_score is calculated numeric score', isinstance(priority_score, (int, float)) and priority_score > 0),
        ('raw_label is persisted in SQLite', db_record.get('raw_label') == 'plastic'),
        ('top_predictions contains multiple actual ViT model classes', len(api_data.get('top_predictions', [])) >= 3),
        ('no fallback classification was used', is_fallback is False and api_data.get('is_ready') is True),
        ('API endpoint status is 200 OK', api_response.status_code == 200),
        ('Citizen report submission status is 200 OK', submit_response.status_code == 200),
    ]

    all_passed = True
    for title, passed in checks:
        status = '[PASS]' if passed else '[FAIL]'
        print(f'{status:8} : {title}')
        if not passed:
            all_passed = False

    print('==================================================================')
    print(f'FINAL STATUS: {"ALL CHECKS PASSED SUCCESSFULLY" if all_passed else "VERIFICATION FAILED"}')
    print('==================================================================')

if __name__ == '__main__':
    main()
