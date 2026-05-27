#!/usr/bin/env python3
"""
Hardware Diagnostics Tool for AI Blind Assistant
Tests Camera, HC-SR04 Ultrasonic Sensor, and Audio/TTS systems.
"""

import sys
import time
import platform

# Attempt to reconfigure stdout for UTF-8 to handle any printing quirks,
# but also use standard ASCII markers to ensure 100% compatibility.
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

print("=" * 50)
print("  Raspberry Pi Hardware Diagnostics Tool")
print("=" * 50)
print(f"OS: {platform.system()} {platform.release()}")
print(f"Python version: {sys.version}")

# ---------------------------------------------------------
# 1. Test Text-to-Speech (TTS) & Speaker Routing
# ---------------------------------------------------------
print("\n--- 1. Testing Audio/TTS (pyttsx3) ---")
try:
    import pyttsx3
    print("[OK] pyttsx3 imported successfully.")
    engine = pyttsx3.init()
    print("[INFO] Speaking test message: 'Testing audio system'...")
    engine.say("Testing audio system")
    engine.runAndWait()
    print("[OK] TTS completed.")
except Exception as e:
    print(f"[ERROR] TTS Error: {e}")
    print("👉 Check your audio output device or make sure pyttsx3/espeak is configured correctly.")

# Direct Linux audio output diagnostic checks
if platform.system() == 'Linux':
    print("\n[INFO] Running Linux Audio diagnostic checks...")
    import subprocess
    try:
        # Check sound card list
        cards = subprocess.check_output("aplay -l", shell=True, stderr=subprocess.STDOUT).decode('utf-8', errors='ignore')
        print("[INFO] Available Sound Cards / Output Devices:\n" + cards)
    except Exception as e:
        print("[WARN] Could not fetch sound card list with aplay.")
        
    try:
        # Try playing a default system sound to verify physical speaker connection
        print("[INFO] Attempting to play ALSA test sound...")
        # standard path on Pi OS
        test_sound = "/usr/share/sounds/alsa/Front_Center.wav"
        subprocess.Popen(["aplay", test_sound], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[OK] aplay command triggered. (You should hear 'Front Center')")
    except Exception:
        print("[WARN] aplay test sound skipped (requires alsa-utils).")

# ---------------------------------------------------------
# 2. Test GPIO and Ultrasonic Sensor (HC-SR04)
# ---------------------------------------------------------
print("\n--- 2. Testing Ultrasonic Sensor (HC-SR04) ---")

# Try to import RPi.GPIO
GPIO_is_mock = False
try:
    import RPi.GPIO as GPIO
    print("[OK] RPi.GPIO imported successfully.")
except ImportError:
    print("[WARN] RPi.GPIO module not found. Using MockGPIO for simulated testing.")
    class MockGPIO:
        BCM = 11
        OUT = 0
        IN = 1
        def setmode(self, mode): pass
        def setup(self, pin, mode): pass
        def output(self, pin, val): pass
        def input(self, pin):
            # Return a changing pulse value to simulate distance
            return int(time.time() * 10) % 2
        def cleanup(self): pass
    GPIO = MockGPIO()
    GPIO_is_mock = True

TRIG = 23
ECHO = 24

try:
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(TRIG, GPIO.OUT)
    GPIO.setup(ECHO, GPIO.IN)
    
    print(f"Configuration: TRIG pin (GPIO {TRIG}), ECHO pin (GPIO {ECHO})")
    print("Taking 10 test measurements...")
    
    for i in range(1, 11):
        # Trigger pulse
        GPIO.output(TRIG, True)
        time.sleep(0.00001) # 10 microseconds
        GPIO.output(TRIG, False)
        
        pulse_start = time.time()
        pulse_end = time.time()
        timeout = 0.05  # 50 ms timeout
        
        # Capture start time of echo pulse
        start_wait = time.time()
        while GPIO.input(ECHO) == 0:
            pulse_start = time.time()
            if pulse_start - start_wait > timeout:
                break
                
        # Capture end time of echo pulse
        start_wait = time.time()
        while GPIO.input(ECHO) == 1:
            pulse_end = time.time()
            if pulse_end - start_wait > timeout:
                break
                
        duration = pulse_end - pulse_start
        distance = duration * 17150
        
        if duration <= 0 or distance > 1000 or (GPIO_is_mock and i % 2 == 0):
            # In mock or if actual timeout/fault occurred
            if GPIO_is_mock:
                distance_str = f"~{20 + i * 5:.1f} cm (Mocked)"
            else:
                distance_str = "TIMEOUT (Check echo wiring / voltage divider)"
        else:
            distance_str = f"{distance:.2f} cm"
            
        print(f"  Measurement #{i}: {distance_str}")
        time.sleep(0.5)
        
    print("[OK] Ultrasonic testing finished.")
except Exception as e:
    print(f"[ERROR] Ultrasonic Sensor Error: {e}")
finally:
    try:
        GPIO.cleanup()
    except Exception:
        pass

# ---------------------------------------------------------
# 3. Test Camera
# ---------------------------------------------------------
print("\n--- 3. Testing Camera (OpenCV) ---")
try:
    import cv2
    print(f"[OK] OpenCV version: {cv2.__version__}")
    
    print("📷 Attempting to open video capture (index 0)...")
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("[ERROR] Could not open video device index 0.")
        print("👉 If using Pi Camera module, ensure it is enabled in raspi-config.")
        print("👉 If multiple cameras exist, try changing index in diagnose_hardware.py (e.g. cv2.VideoCapture(1))")
    else:
        # Allow camera to warm up
        time.sleep(1)
        ret, frame = cap.read()
        if ret:
            h, w, c = frame.shape
            print(f"[OK] Frame captured successfully! Resolution: {w}x{h} ({c} channels)")
            
            output_file = "test_capture.jpg"
            cv2.imwrite(output_file, frame)
            print(f"[INFO] Saved captured frame to: {output_file}")
        else:
            print("[ERROR] Opened camera but failed to read a frame.")
            
        cap.release()
except Exception as e:
    print(f"[ERROR] Camera Error: {e}")

print("\n" + "=" * 50)
print("Diagnostics execution complete.")
print("=" * 50)
