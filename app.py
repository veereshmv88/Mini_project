import cv2
import pyttsx3
import pytesseract
import platform
import time
import threading
import queue
from ultralytics import YOLO
from collections import deque

# -------------------------------
# Configuration Settings
# -------------------------------
# Swap model to "yolov8s.pt" (Small) or "yolov8m.pt" (Medium) for better accuracy.
# "yolov8n.pt" (Nano) is faster but less accurate.
YOLO_MODEL_NAME = "yolov8s.pt"  
YOLO_CONF_THRESHOLD = 0.20       # Lower threshold (default is 0.25) to detect more objects

# Configure pytesseract path for Windows
if platform.system() == 'Windows':
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

try:
    import RPi.GPIO as GPIO
except ImportError:
    # Mock class for testing on Windows / Non-Raspberry Pi environments
    class MockGPIO:
        BCM = 11
        OUT = 0
        IN = 1
        def setmode(self, mode): pass
        def setup(self, pin, mode): pass
        def output(self, pin, val): pass
        def input(self, pin): return 0
        def cleanup(self): pass
    GPIO = MockGPIO()

# -------------------------------
# Thread-safe Speech Queue
# -------------------------------
speech_queue = queue.Queue()

def tts_worker():
    """Continuously speaks messages from the queue without blocking the main loop."""
    engine = pyttsx3.init()
    while True:
        msg = speech_queue.get()
        if msg is None:          # Signal to stop the thread
            break
        print(msg)
        engine.say(msg)
        engine.runAndWait()
        speech_queue.task_done()

# Start the TTS thread
tts_thread = threading.Thread(target=tts_worker, daemon=True)
tts_thread.start()

def speak(text):
    """Non‑blocking speech request."""
    speech_queue.put(text)

# -------------------------------
# Ultrasonic Sensor with timeout
# -------------------------------
TRIG = 23
ECHO = 24
GPIO.setmode(GPIO.BCM)
GPIO.setup(TRIG, GPIO.OUT)
GPIO.setup(ECHO, GPIO.IN)

def get_distance(timeout=0.05):
    """
    Returns distance in cm, or None if timeout/error occurs.
    Uses a proper time‑out and exception handling to avoid hanging.
    """
    try:
        # Initialize default values to avoid UnboundLocalError
        pulse_start = time.time()
        pulse_end = time.time()

        # Send 10 µs pulse
        GPIO.output(TRIG, True)
        time.sleep(0.00001)
        GPIO.output(TRIG, False)

        # Wait for echo start
        start_wait = time.time()
        while GPIO.input(ECHO) == 0:
            pulse_start = time.time()
            if pulse_start - start_wait > timeout:
                return None

        # Wait for echo end
        start_wait = time.time()
        while GPIO.input(ECHO) == 1:
            pulse_end = time.time()
            if pulse_end - start_wait > timeout:
                return None

        distance = (pulse_end - pulse_start) * 17150
        return round(distance, 2)
    except Exception:
        # Gracefully return None on GPIO read error (e.g. unplugged wires)
        return None

# -------------------------------
# Load YOLO Model
# -------------------------------
model = YOLO(YOLO_MODEL_NAME)

# -------------------------------
# Camera Setup & Reconnection
# -------------------------------
def initialize_camera():
    """Tries to find and open a working camera index (0, 1, or 2)."""
    for index in (0, 1, 2):
        try:
            temp_cap = cv2.VideoCapture(index)
            if temp_cap.isOpened():
                ret, _ = temp_cap.read()
                if ret:
                    print(f"Camera initialized on index {index}")
                    return temp_cap
                temp_cap.release()
        except Exception:
            pass
    return None

def get_placeholder_frame(width=640, height=480):
    """Generates a sleek placeholder frame when camera is disconnected."""
    import numpy as np
    img = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.putText(img, "CAMERA DISCONNECTED", (width // 2 - 150, height // 2 - 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.putText(img, "Attempting reconnection...", (width // 2 - 140, height // 2 + 20),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    return img

cap = initialize_camera()
camera_alert_spoken = False
if cap is None:
    speak("Warning: Camera not found on startup. Starting in sensor-only mode.")
    camera_alert_spoken = True

# -------------------------------
# State variables to avoid repetitive speech
# -------------------------------
last_spoken_objects = set()      # objects spoken last time
last_obstacle_alert = False      # whether we already announced a close obstacle
last_distance = None             # track distance changes
object_speak_interval = 3.0      # seconds between full object announcements
last_object_speak_time = 0
last_full_scene_speak_time = 0   # last time we spoke the full scene description
FULL_SCENE_INTERVAL = 8.0        # repeat rate for full scene descriptions
ocr_last_text = ""               # previously spoken OCR text
current_detected_objects = []    # list of dicts: {'label', 'position', 'area_ratio'}
last_nav_time = 0
last_nav_instruction = ""        # last spoken navigation instruction
NAV_INTERVAL = 1.5               # seconds between repeating the same navigation instruction

# -------------------------------
# Cooldown thresholds
# -------------------------------
OBSTACLE_DIST_THRESH = 50        # cm
DIST_CHANGE_THRESH = 20          # cm – announce only if distance changes significantly
OCR_MIN_LENGTH = 5               # minimum characters to announce text
OCR_CONFIDENCE = 60              # (optional) Tesseract confidence filter

speak("AI Blind Assistant started")

# -------------------------------
# Main Loop
# -------------------------------
frame_count = 0
DETECTION_EVERY_N_FRAMES = 5     # run YOLO only every N frames
OCR_EVERY_N_FRAMES = 30          # run OCR only every N frames
RECONNECT_COOLDOWN = 100         # frames before checking for camera reconnection again

try:
    while True:
        frame_count += 1
        current_time = time.time()
        frame = None

        # Try to read from camera if available
        if cap is not None:
            try:
                ret, temp_frame = cap.read()
                if ret:
                    frame = temp_frame
                    camera_alert_spoken = False
                else:
                    raise Exception("Failed to read frame")
            except Exception:
                print("Camera link lost, releasing capture device.")
                cap.release()
                cap = None

        # Camera reconnection logic if offline
        if cap is None:
            if not camera_alert_spoken:
                speak("Camera connection lost")
                camera_alert_spoken = True
            
            # Periodically attempt to reconnect
            if frame_count % RECONNECT_COOLDOWN == 0:
                print("Attempting to reconnect camera...")
                cap = initialize_camera()

        # If camera is down, display a placeholder to keep UI active
        camera_online = frame is not None
        if not camera_online:
            frame = get_placeholder_frame()

        # ---- Object Detection (throttled) ----
        if camera_online and (frame_count % DETECTION_EVERY_N_FRAMES == 0):
            try:
                results = model(frame, conf=YOLO_CONF_THRESHOLD)
                detected_objects = set()
                new_detected_list = []

                for result in results:
                    for box in result.boxes:
                        cls = int(box.cls[0])
                        label = model.names[cls]
                        detected_objects.add(label)

                        # Draw bounding box (optional, for debugging)
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(frame, label, (x1, y1 - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

                        # Calculate position and area ratio
                        w_frame = frame.shape[1]
                        h_frame = frame.shape[0]
                        x_center = (x1 + x2) / 2
                        area_ratio = ((x2 - x1) * (y2 - y1)) / (w_frame * h_frame)

                        if x_center < w_frame * 0.35:
                            position = "left"
                        elif x_center > w_frame * 0.65:
                            position = "right"
                        else:
                            position = "center"

                        new_detected_list.append({
                            'label': label,
                            'position': position,
                            'area_ratio': area_ratio
                        })

                # Update the tracking list
                current_detected_objects = new_detected_list

                # 1. Immediate announcement for new objects entering the view
                new_objects = detected_objects - last_spoken_objects
                if new_objects:
                    speak("I see " + ", ".join(new_objects))
                    # Update last_spoken_objects to include them
                    last_spoken_objects.update(new_objects)
                    last_object_speak_time = current_time

                # 2. Periodic description of everything in view (full scene description)
                if detected_objects:
                    # If we haven't spoken the full list in FULL_SCENE_INTERVAL seconds, do so
                    if current_time - last_full_scene_speak_time > FULL_SCENE_INTERVAL:
                        speak("In front of you: " + ", ".join(detected_objects))
                        last_full_scene_speak_time = current_time
                        # Sync last_spoken_objects with all currently visible objects
                        last_spoken_objects = detected_objects.copy()
                else:
                    # If nothing is in view, and we recently had objects, clean up
                    last_spoken_objects = set()
            except Exception as e:
                print(f"Error running YOLO: {e}")

        # ---- Distance Measurement & Spatial Navigation ----
        distance = get_distance()
        if distance is not None:
            cv2.putText(frame, f"Distance: {distance} cm", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            last_distance = distance
        else:
            cv2.putText(frame, "Distance: out of range", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        # Evaluate obstacles from sensor and camera
        sensor_obstacle_detected = (distance is not None and distance < OBSTACLE_DIST_THRESH)
        
        # Camera obstacle: any object in front that is large/close
        # e.g., center object with area_ratio > 0.08, or side objects with area_ratio > 0.15
        camera_obstacles = [
            obj for obj in current_detected_objects 
            if (obj['position'] == 'center' and obj['area_ratio'] > 0.08) or 
               (obj['position'] != 'center' and obj['area_ratio'] > 0.15)
        ]
        camera_obstacles.sort(key=lambda x: x['area_ratio'], reverse=True)
        camera_obstacle_detected = len(camera_obstacles) > 0

        # Trigger navigation guidance if either sensor or camera detects an obstacle
        if sensor_obstacle_detected or camera_obstacle_detected:
            # Determine instruction
            # Prioritize yolo obstacles for specific naming
            yolo_obstacles = [obj for obj in current_detected_objects if obj['area_ratio'] > 0.005]
            yolo_obstacles.sort(key=lambda x: x['area_ratio'], reverse=True)

            if yolo_obstacles:
                primary_obstacle = yolo_obstacles[0]
                label = primary_obstacle['label']
                pos = primary_obstacle['position']

                if pos == "center":
                    if distance is not None and distance < 30:
                        instruction = f"{label} right ahead. Go back."
                    else:
                        left_clear = not any(obj['position'] == 'left' for obj in yolo_obstacles)
                        right_clear = not any(obj['position'] == 'right' for obj in yolo_obstacles)
                        if left_clear:
                            instruction = f"{label} in front. Go left."
                        elif right_clear:
                            instruction = f"{label} in front. Go right."
                        else:
                            instruction = f"{label} in front. Go back."
                elif pos == "left":
                    instruction = f"{label} on your left. Go right."
                else:  # right
                    instruction = f"{label} on your right. Go left."
            else:
                # Fallback if no YOLO objects are detected, but sensor triggered
                if distance is not None and distance < 30:
                    instruction = f"Obstacle close, {distance} centimeters. Go back."
                else:
                    dist_str = f"{distance} centimeters" if distance is not None else "ahead"
                    instruction = f"Obstacle {dist_str}. Go left."

            # Evaluate whether to speak
            is_new_instruction = (instruction != last_nav_instruction)
            time_elapsed = current_time - last_nav_time

            if is_new_instruction or (time_elapsed > NAV_INTERVAL):
                speak(instruction)
                last_nav_instruction = instruction
                last_nav_time = current_time
                last_obstacle_alert = True
            
            # If distance changed significantly while still close (sensor-based)
            elif (not is_new_instruction and distance is not None and last_distance is not None 
                  and abs(distance - last_distance) > DIST_CHANGE_THRESH):
                speak(f"Distance now {distance} centimeters")
        else:
            # Reset alert when path becomes clear (no sensor obstacle and no camera obstacle)
            if last_obstacle_alert:
                speak("Path is clear")
                last_nav_instruction = ""
            last_obstacle_alert = False

        # ---- OCR Text Reading (throttled & filtered) ----
        if camera_online and (frame_count % OCR_EVERY_N_FRAMES == 0):
            try:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                # Use Tesseract with confidence data if possible
                try:
                    data = pytesseract.image_to_data(gray, output_type=pytesseract.Output.DICT)
                    # Concatenate only words with high confidence
                    words = [word for word, conf in zip(data['text'], data['conf']) 
                             if conf > OCR_CONFIDENCE]
                    text = ' '.join(words).strip()
                except Exception:
                    # Fallback if confidence data not available
                    text = pytesseract.image_to_string(gray).strip()

                if len(text) > OCR_MIN_LENGTH and text != ocr_last_text:
                    speak("Text reads: " + text)
                    ocr_last_text = text
            except Exception as e:
                print(f"Error running OCR: {e}")

        # ---- Show preview (optional) ----
        cv2.imshow("AI Blind Assistant", frame)

        # Quit on 'q'
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

except KeyboardInterrupt:
    pass
finally:
    # Cleanup
    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()
    GPIO.cleanup()
    speech_queue.put(None)   # stop TTS thread
    tts_thread.join(timeout=2)
    print("Assistant stopped.")