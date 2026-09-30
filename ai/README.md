# AI WasteWatch - Computer Vision Module

This directory contains the computer vision subsystem for the **AI WasteWatch** platform. It provides automated object detection, waste material classification, severity estimation, and priority scoring for municipal waste management.

---

## 1. System Architecture & Training Pipeline

Because the local development machine operates on an Intel CPU with integrated graphics, model training is decoupled from local web application hosting:

```
+-----------------------------------------------------------------------------------------+
|                                    WORKFLOW PIPELINE                                    |
+-----------------------------------------------------------------------------------------+
|                                                                                         |
|  [ Kaggle Cloud Platform ]                                                              |
|   ├── Environment: NVIDIA T4 GPU                                                        |
|   ├── Dataset: Waste Detection 2.0 (19 fine-grained classes)                             |
|   ├── Remapping: 19 source classes -> 7 unified WasteWatch categories                   |
|   ├── Architecture: YOLOv8s (Transfer Learning from pre-trained weights)                |
|   └── Artifact: Exported best model checkpoint (waste_best.pt)                          |
|                                     │                                                   |
|                                     ▼ (Download weights)                                |
|  [ Local WasteWatch System ]                                                            |
|   ├── Destination: ai/models/waste_best.pt                                              |
|   ├── Execution: Lightweight Intel CPU inference (via ai/predict.py)                    |
|   └── Web App: Flask backend (app.py) processes user reports and saves predictions      |
|                                                                                         |
+-----------------------------------------------------------------------------------------+
```

1. **Training (Kaggle Cloud GPU):**
   - Fine-tuned on Google Kaggle using an **NVIDIA T4 GPU** for rapid convergence (~15–20 minutes).
   - Base model: **`YOLOv8s`** (transfer learning from pre-trained weights).
   - Dataset: **Waste Detection 2.0** with class remapping.
2. **Model Placement (`ai/models/`):**
   - The trained checkpoint (`waste_best.pt`) is downloaded from Kaggle and placed directly into `ai/models/`.
3. **Local Inference (Flask Web App):**
   - The local Flask application loads `ai/models/waste_best.pt` via `ai/predict.py`.
   - Executes fast local CPU inference (<100 ms) when a citizen submits an image on `/submit-report`.

---

## 2. Dataset & Class Taxonomy Mapping

The primary training dataset is **Waste Detection 2.0**, containing 19 fine-grained classes. During data preprocessing on Kaggle, these 19 source classes are mapped to **7 standardized WasteWatch categories (IDs 0 to 6)**:

| Class ID | Target WasteWatch Category | Source Dataset Classes Mapped | Description / Examples |
| :---: | :--- | :--- | :--- |
| **0** | **Plastic** | `Plastics`, `Plastic Bag`, `Bottle`, `Styrofoam`, `Spoon`, `Phone Case` | PET bottles, grocery bags, polystyrene foam, plastic cutlery, rigid containers |
| **1** | **Paper/Cardboard** | `Paper`, `Carton` | Cardboard boxes, paper packaging, cartons, newspapers, documents |
| **2** | **Glass** | `Glass`, `Glass Bottle` | Glass beverage bottles, jars, glass fragments |
| **3** | **Metal** | `Metal`, `Can` | Aluminum drink cans, food tins, scrap metal pieces, bottle caps |
| **4** | **Organic** | `Organic Waste`, `Wooden Waste` | Food scraps, fruit peels, biological waste, timber scraps |
| **5** | **Hazardous** | `E-Waste`, `Electric Cable` | Electronic devices, wires, circuit boards, cables |
| **6** | **Other** | `Trash`, `Trash-Brush`, `Yoga Mat` | Non-recyclable mixed debris, synthetic composite waste |

---

## 3. Directory Structure

```text
ai/
├── dataset/            # Local dataset samples and YAML configurations (.gitkeep)
├── models/             # Target folder for trained weights (e.g., waste_best.pt) (.gitkeep)
├── train/              # Training logs, checkpoints, and run metrics (.gitkeep)
├── test/               # Evaluation metrics, confusion matrices, and benchmark logs (.gitkeep)
├── predictions/        # Output visual prediction images with annotated bounding boxes (.gitkeep)
├── train.py            # Local training pipeline and Kaggle export runner
├── test.py             # Model evaluation and benchmark validation script
├── predict.py          # Production inference and feature extraction module (called by Flask)
└── README.md           # Architecture, Kaggle training instructions, and class taxonomy
```

---

## 4. Output Schema

The inference engine in [`ai/predict.py`](predict.py) produces structured outputs consumed directly by the Flask application and stored in `wastewatch.db`:

| Field | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| **`waste_type`** | `str` | Primary detected category (from 7 WasteWatch classes) | `"Plastic"`, `"Hazardous"`, `"Organic"` |
| **`confidence_score`** | `float` | Detection confidence level | `0.94` (94%) |
| **`detected_objects`** | `list[dict]` | Detected bounding boxes, labels, and individual confidences | `[{"label": "Plastic", "box": [120, 80, 310, 450]}]` |
| **`severity`** | `str` | Urgency tier based on density, hazard, and volume | `"Low"`, `"Medium"`, `"High"`, `"Critical"` |
| **`priority_score`** | `float` | Computed dispatch score (0 - 100) for municipal routing | `84.5` |
| **`annotated_image_path`** | `str` | Path to the saved image containing rendered bounding boxes | `"ai/predictions/pred_waste.jpg"` |

---

## 5. End-to-End Operational Workflow

1. **Kaggle Training**:
   - Open a Kaggle notebook with GPU accelerator enabled (**NVIDIA T4**).
   - Ingest Waste Detection 2.0 dataset.
   - Run label remapping to map the 19 source classes to the 7 WasteWatch classes (0 to 6).
   - Fine-tune `yolov8s.pt` using transfer learning for 30–50 epochs.
2. **Model Deployment**:
   - Download the resulting `best.pt` from the Kaggle output directory.
   - Rename and place it at: `ai/models/waste_best.pt`.
3. **Local Serving**:
   - Run Flask locally (`python app.py`).
   - When a citizen uploads an image via the web UI (`/submit-report`), `predict_waste()` runs inference using `ai/models/waste_best.pt` on the local CPU.
   - The detected `waste_type`, `severity`, and `priority_score` are recorded into the database and displayed to the user.
