# AI Blind Assistant (Raspberry Pi, YOLOv8, and Sensor-Fusion)

An advanced, proactive navigation assistant for visually impaired individuals. This system fuses real-time computer vision (YOLOv8) and physical distance measurements (HC-SR04 Ultrasonic Sensor) to provide spoken, spatial guidance and obstacle avoidance.

---

## 🌟 Key Features

* **Proactive Spatial Guidance**: Calculates real-time directional feedback ("go left", "go right", "go back") by combining camera bounding box locations with ultrasonic distance readings.
* **Dual-Announcer Audio System**: 
  1. *Immediate Alerts*: Instantly calls out new items entering the frame (e.g., "I see bottle", "I see cup").
  2. *Periodic Scene Summaries*: Reads out a full list of all visible items every 8 seconds (e.g., "In front of you: chair, person, cup").
* **High-Sensitivity Obstacle Tracking**: Detects small items (down to 0.5% of the camera frame) to navigate safely around objects on the floor or tables.
* **Resilient Self-Healing Camera Loop**: If the camera wire gets loose, the app falls back to sensor-only mode, displays a "CAMERA DISCONNECTED" screen, and automatically resumes YOLO/OCR once the camera is reconnected.
* **OCR Text Reading**: Dynamically reads text visible in the frame (utilizing Tesseract OCR with high-confidence thresholds).
* **Hardware Validation Tool**: Includes a CLI diagnostic script to check the speaker, camera, and ultrasonic sensor step-by-step.

---

## 🔌 Hardware Integration & Wiring

### ⚠️ Critical Voltage Divider Warning (Echo Pin)
The HC-SR04 ultrasonic sensor operates at **5V**, outputting a 5V signal on its `ECHO` pin. However, the Raspberry Pi's GPIO pins are strictly **3.3V tolerant**. Connecting `ECHO` directly to the Pi can permanently damage your GPIO controller!
You **MUST** use a simple voltage divider (two resistors) to step down the `ECHO` signal to 3.3V.

#### Recommended Resistors:
* **R1**: $1\text{ k}\Omega$ (between HC-SR04 ECHO and Pi GPIO 24)
* **R2**: $2\text{ k}\Omega$ (between Pi GPIO 24 and GND)

### 📌 Wiring Pinout
| Component | HC-SR04 Pin | Resistors / Connections | Raspberry Pi Pin |
|---|---|---|---|
| **Power** | VCC | Direct | **5V Power** (Physical Pin 2 or 4) |
| **Trigger** | TRIG | Direct | **GPIO 23** (Physical Pin 16) |
| **Echo** | ECHO | Through R1 ($1\text{ k}\Omega$) | **GPIO 24** (Physical Pin 18) |
| **Ground** | GND | Direct (And connect R2 from GPIO 24) | **GND** (Physical Pin 6 or 14) |

### 🔊 Speaker Integration Options
* **Option A: USB Speakers / USB Sound Dongle** (Recommended for Pi 4 & Pi 5)
  * Simply plug into any USB port. Requires no GPIO wiring (Plug-and-Play).
* **Option B: 3.5mm Analog Audio Jack** (Available on Pi 4 and earlier)
  * Plug standard headphones or powered speakers directly into the Pi's audio jack.
* **Option C: I2S Audio Amplifier (e.g., MAX98357A)**
  * **LRCK** $\rightarrow$ **GPIO 19** (Pin 35)
  * **BCLK** $\rightarrow$ **GPIO 18** (Pin 12)
  * **DIN** $\rightarrow$ **GPIO 21** (Pin 40)
  * **VIN** $\rightarrow$ **5V** (Pin 2 or 4), **GND** $\rightarrow$ **GND** (Pin 6 or 14)

---

## 🛠️ Installation & Setup (Raspberry Pi OS)

### 1. Install System Dependencies
Open a terminal on your Raspberry Pi and run:
```bash
sudo apt update
sudo apt install -y python3-pip python3-opencv espeak tesseract-ocr alsa-utils
```

### 2. Clone and Install Python Dependencies
```bash
git clone https://github.com/veereshmv88/Mini_project.git
cd Mini_project
pip install -r requirements.txt
```

---

## 🚀 Running & Verification

### Step 1: Run Hardware Diagnostics
Verify that your camera, speaker, and ultrasonic sensor are working properly:
```bash
python diagnose_hardware.py
```
*It will list your sound cards, try to play a test audio file ("Front Center"), measure distance readings, and capture a test photo (`test_capture.jpg`).*

### Step 2: Configure Audio Routing (If you hear no sound)
If your speaker is plugged in but silent, route the audio output:
* **For 3.5mm Headphone Jack**: `sudo amixer cset numid=3 1`
* **For HDMI Speakers**: `sudo amixer cset numid=3 2`
* Alternatively, run `sudo raspi-config` and navigate to **System Options** -> **Audio** to choose your default soundcard.

### Step 3: Run the Main Assistant
Launch the main software loop:
```bash
python app.py
```
*To exit the app, press `q` on the preview window or press `Ctrl + C` in the terminal.*
