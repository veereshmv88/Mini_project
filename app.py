import cv2
import pyttsx3
import pytesseract
import platform
import time
import threading
import queue
from ultralytics import YOLO
from collections import deque
import speech_recognition as sr
import os
from dotenv import load_dotenv
import google.generativeai as genai
import io
import PIL.Image

# Load environment variables
load_dotenv()

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
# Cross-Platform Text-To-Speech (TTS) Engine
# -------------------------------
class TTSEngine:
    def __init__(self):
        self.system = platform.system()
        self.windows_speaker = None
        self.linux_queue = queue.Queue()
        self.linux_speaking = False
        
        if self.system == 'Windows':
            try:
                import win32com.client
                self.windows_speaker = win32com.client.Dispatch("SAPI.SpVoice")
                print("[INFO] Native SAPI5 SpVoice initialized on Windows.")
            except Exception as e:
                print(f"[WARN] Failed to initialize win32com SAPI: {e}. Falling back to pyttsx3.")
                
        if self.windows_speaker is None:
            # Start background thread fallback (used for Linux or Windows fallback)
            self.thread = threading.Thread(target=self._worker, daemon=True)
            self.thread.start()

    def _worker(self):
        # Native espeak (subprocess) fallback on Linux for zero-hang reliability
        if self.system == 'Linux':
            import subprocess
            while True:
                msg = self.linux_queue.get()
                if msg is None:
                    break
                print(msg)
                self.linux_speaking = True
                try:
                    subprocess.run(["espeak", msg], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception:
                    pass
                self.linux_speaking = False
                self.linux_queue.task_done()
        else:
            # pyttsx3 fallback
            try:
                engine = pyttsx3.init()
            except Exception as e:
                print(f"[ERROR] Failed to initialize pyttsx3 engine: {e}")
                return
            while True:
                msg = self.linux_queue.get()
                if msg is None:
                    break
                print(msg)
                self.linux_speaking = True
                try:
                    engine.say(msg)
                    engine.runAndWait()
                except Exception as e:
                    print(f"pyttsx3 error: {e}")
                self.linux_speaking = False
                self.linux_queue.task_done()

    def speak(self, text):
        """Asynchronously plays a text-to-speech message orally."""
        if self.windows_speaker is not None:
            print(text)
            try:
                # 1 is SPF_ASYNC (asynchronous speak)
                self.windows_speaker.Speak(text, 1)
            except Exception as e:
                print(f"SAPI Speak error: {e}")
        else:
            self.linux_queue.put(text)

    def is_active(self):
        """Returns True if the engine is currently speaking or queue has items."""
        if self.windows_speaker is not None:
            try:
                # RunningState == 2 means currently speaking
                return self.windows_speaker.Status.RunningState == 2
            except Exception:
                return False
        return self.linux_speaking or not self.linux_queue.empty()

    def stop(self):
        """Stops the background fallback thread if it exists."""
        if self.windows_speaker is None:
            try:
                self.linux_queue.put(None)
            except Exception:
                pass

# Initialize the global TTS engine instance
tts_engine = TTSEngine()

def speak(text):
    tts_engine.speak(text)

def is_tts_active():
    return tts_engine.is_active()

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
# -------------------------------
# Conversational AI & state
# -------------------------------
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
gemini_enabled = False
if GEMINI_API_KEY:
    try:
        # Use gemini-1.5-flash as default model
        genai.configure(api_key=GEMINI_API_KEY)
        model_chat = genai.GenerativeModel('gemini-1.5-flash')
        gemini_enabled = True
        print("[INFO] Gemini Conversational AI enabled.")
    except Exception as e:
        print(f"[WARN] Error initializing Gemini Model: {e}. Using local fallback.")
else:
    print("[WARN] GEMINI_API_KEY not found in environment or .env file. Please create a .env file with GEMINI_API_KEY=your_key to run using full Gemini AI model integration.")

def get_conversational_response(user_input, image_data=None):
    """
    Generates a short, conversational response using Gemini API or a local rule-based fallback.
    """
    if gemini_enabled:
        try:
            prompt = (
                f"You are a friendly, concise AI voice assistant integrated into a physical blind assistance system. "
                f"The user just asked: \"{user_input}\". "
                f"Provide a friendly, helpful reply based on what you see in the current camera frame (if provided). "
                f"Keep your answer very brief (1 or 2 short sentences, maximum 25 words) as this will be read aloud via text-to-speech."
            )
            if image_data is not None:
                response = model_chat.generate_content([prompt, image_data])
            else:
                response = model_chat.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            print(f"Gemini API error: {e}")
            # Fall through to local fallback

    # Local rule-based fallback chatbot
    user_input_lower = user_input.lower()
    
    # Navigation / surroundings queries
    if any(k in user_input_lower for k in ["where", "front", "see", "look", "describe", "surroundings"]):
        if current_detected_objects:
            objs = [o['label'] for o in current_detected_objects]
            return f"I see: {', '.join(set(objs))} in front of you."
        else:
            return "The camera doesn't see any objects in front of you right now."
            
    if any(k in user_input_lower for k in ["obstacle", "clear", "safe", "navigate", "path"]):
        dist_str = f"at {last_distance} cm" if last_distance is not None else "nearby"
        if last_obstacle_alert:
            return f"There is an obstacle {dist_str}. You should turn or step back."
        else:
            return "The path in front of you is clear. Proceed with caution."
            
    if any(k in user_input_lower for k in ["distance", "far", "sensor", "reading"]):
        if last_distance is not None:
            return f"The nearest object is {last_distance} centimeters away."
        else:
            return "The distance sensor is not reading any close obstacles."

    # General chat responses
    if any(k in user_input_lower for k in ["hello", "hi", "hey"]):
        return "Hello! How can I assist you today?"
    if "how are you" in user_input_lower:
        return "I am functioning normally and ready to help you navigate!"
    if "time" in user_input_lower:
        import datetime
        now = datetime.datetime.now()
        return f"The time is {now.strftime('%I:%M %p')}."
    if "name" in user_input_lower or "who are you" in user_input_lower:
        return "I am your AI Blind Assistant, helping you with navigation and object detection."
        
    return "I heard you, but I didn't quite catch that. You can ask about what I see, obstacle distance, or say goodbye."

is_conversing = False
last_person_seen_time = 0
conversation_active_lock = threading.Lock()
latest_camera_frame = None
camera_frame_lock = threading.Lock()

def conversation_worker():
    """Handles the conversational loop with the user using speech recognition."""
    global is_conversing, last_person_seen_time
    
    print("[INFO] Starting conversation loop...")
    r = sr.Recognizer()
    
    # Calibrate microphone for ambient noise
    try:
        with sr.Microphone() as source:
            r.adjust_for_ambient_noise(source, duration=1.0)
    except Exception as e:
        print(f"[ERROR] Could not initialize microphone: {e}")
        speak("Could not access microphone. Conversational mode is disabled.")
        with conversation_active_lock:
            is_conversing = False
        return

    consecutive_silence_count = 0
    max_silence_attempts = 3

    while True:
        # Check if conversation was closed
        with conversation_active_lock:
            if not is_conversing:
                break
        
        # Standby timeout: if no person seen/heard for 30 seconds
        if time.time() - last_person_seen_time > 30.0:
            speak("Going on standby.")
            with conversation_active_lock:
                is_conversing = False
            break

        # Wait until speaker is quiet
        while is_tts_active():
            time.sleep(0.2)
        
        # Short cushion pause to prevent hearing own echo
        time.sleep(0.6)
        
        if is_tts_active():
            continue

        try:
            print("Listening for question...")
            with sr.Microphone() as source:
                audio = r.listen(source, timeout=4.0, phrase_time_limit=6.0)
            
            print("Processing speech...")
            user_speech = r.recognize_google(audio)
            print(f"User said: {user_speech}")
            
            # Reset silence and update activity time
            consecutive_silence_count = 0
            last_person_seen_time = time.time()
            
            user_speech_lower = user_speech.lower()
            exit_phrases = ["goodbye", "good bye", "stop", "exit", "thank you", "bye", "cancel"]
            if any(phrase in user_speech_lower for phrase in exit_phrases):
                speak("Goodbye! Have a safe journey.")
                with conversation_active_lock:
                    is_conversing = False
                break
            
            # Capture and convert the latest camera frame for the multimodal model
            img_to_send = None
            with camera_frame_lock:
                if latest_camera_frame is not None:
                    try:
                        _, buffer = cv2.imencode('.jpg', latest_camera_frame)
                        img_to_send = PIL.Image.open(io.BytesIO(buffer))
                    except Exception as e:
                        print(f"Error encoding camera frame: {e}")

            # Get response and speak
            response = get_conversational_response(user_speech, img_to_send)
            speak(response)
            
        except sr.WaitTimeoutError:
            # Normal timeout when user is not speaking
            continue
        except sr.UnknownValueError:
            print("Could not understand audio")
            consecutive_silence_count += 1
            if consecutive_silence_count >= max_silence_attempts:
                speak("I didn't hear anything. Returning to navigation mode.")
                with conversation_active_lock:
                    is_conversing = False
                break
        except Exception as e:
            print(f"Speech recognition error: {e}")
            time.sleep(1.0)
            
    print("[INFO] Conversation loop terminated.")

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

        # Save the raw camera frame thread-safely for the Multimodal AI
        with camera_frame_lock:
            latest_camera_frame = frame.copy() if camera_online else None

        # ---- Object Detection (throttled) ----
        # Throttle YOLO significantly during conversation to free up CPU for speech recognition
        current_yolo_throttle = 35 if is_conversing else DETECTION_EVERY_N_FRAMES
        if camera_online and (frame_count % current_yolo_throttle == 0):
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

                        if label == "person":
                            last_person_seen_time = time.time()
                            # Detect a person relatively close in frame (area_ratio > 0.02)
                            if area_ratio > 0.02:
                                with conversation_active_lock:
                                    if not is_conversing:
                                        is_conversing = True
                                        speak("Hello! I see you. How can I help you today?")
                                        threading.Thread(target=conversation_worker, daemon=True).start()

                        new_detected_list.append({
                            'label': label,
                            'position': position,
                            'area_ratio': area_ratio
                        })

                # Update the tracking list
                current_detected_objects = new_detected_list

                # 1. Immediate announcement for new objects entering the view
                if not is_conversing:
                    new_objects = detected_objects - last_spoken_objects
                    if new_objects:
                        speak("I see " + ", ".join(new_objects))
                        # Update last_spoken_objects to include them
                        last_spoken_objects.update(new_objects)
                        last_object_speak_time = current_time

                # 2. Periodic description of everything in view (full scene description)
                if not is_conversing:
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

        # Trigger conversation via distance sensor if camera is offline and distance is close
        if not camera_online and distance is not None and distance < 100:
            last_person_seen_time = time.time()
            with conversation_active_lock:
                if not is_conversing:
                    is_conversing = True
                    speak("Hello! I notice you are near. How can I help you today?")
                    threading.Thread(target=conversation_worker, daemon=True).start()

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

            # If we are conversing, suppress regular navigation instruction unless it's a critical close obstacle
            should_speak_nav = True
            if is_conversing:
                is_critical = (distance is not None and distance < 35)
                if not is_critical:
                    should_speak_nav = False

            if should_speak_nav:
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
                if not is_conversing:
                    speak("Path is clear")
                last_nav_instruction = ""
            last_obstacle_alert = False

        # ---- OCR Text Reading (throttled & filtered) ----
        # Disable OCR processing while conversing to save CPU
        if not is_conversing and camera_online and (frame_count % OCR_EVERY_N_FRAMES == 0):
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
                    if not is_conversing:
                        speak("Text reads: " + text)
                        ocr_last_text = text
            except Exception as e:
                print(f"Error running OCR: {e}")

        # ---- Show preview (optional) ----
        cv2.imshow("AI Blind Assistant", frame)

        # Yield CPU control during conversation to prioritize SpeechRecognition
        if is_conversing:
            time.sleep(0.05)

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
    tts_engine.stop()
    print("Assistant stopped.")