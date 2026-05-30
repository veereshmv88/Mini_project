# test_setup.py
import sys
print("Python version:", sys.version)

# Test OpenCV
try:
    import cv2
    print("[OK] OpenCV version:", cv2.__version__)
except Exception as e:
    print("[ERROR] OpenCV error:", e)

# Test pyttsx3
try:
    import pyttsx3
    print("[OK] pyttsx3 imported successfully")
except Exception as e:
    print("[ERROR] pyttsx3 error:", e)

# Test pytesseract
try:
    import pytesseract
    # Set path for Windows
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    version = pytesseract.get_tesseract_version()
    print("[OK] Tesseract version:", version)
except Exception as e:
    print("[ERROR] Tesseract error:", e)
    print("   Make sure Tesseract OCR is installed!")

# Test YOLO OpenCV DNN loading
try:
    from app import YOLOOpenCVDNN, download_model_if_needed
    print("[OK] YOLOOpenCVDNN class imported from app.py successfully")
    
    # Try checking/downloading yolov8n.onnx for test verification
    print("[INFO] Checking for yolov8n.onnx model...")
    onnx_path = download_model_if_needed("yolov8n.pt")
    
    # Instantiate the model
    print(f"[INFO] Initializing YOLOOpenCVDNN model with {onnx_path}...")
    model = YOLOOpenCVDNN(onnx_path)
    print("[OK] YOLOOpenCVDNN model initialized successfully!")
except Exception as e:
    print("[ERROR] YOLO OpenCV DNN test failed:", e)