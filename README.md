![Python]
![Arduino]
![IoT]
![MIT License]

# Portable Stress Monitoring System 🚀

A smart healthcare and IoT-based embedded system designed to monitor physiological indicators related to stress in real time.

This project uses Raspberry Pi Pico, Arduino-compatible firmware, MAX30102 sensor, OLED display, and cloud/dashboard integration to collect, process, and visualize biometric data such as heart rate and blood oxygen (SpO₂).

---

## 📌 Overview

Stress has become one of the major health challenges in modern life. The goal of this project is to develop an affordable, portable, and real-time monitoring system capable of tracking physiological signals that may indicate stress levels.

The system collects biometric data using sensors, processes the readings through embedded hardware, and displays or transmits the data to dashboards for monitoring and analysis.

---

## ✨ Features

✅ Real-time Heart Rate Monitoring  
✅ SpO₂ (Blood Oxygen) Monitoring  
✅ OLED Live Display  
✅ Cross-Platform Firmware Support  
✅ IoT Dashboard Integration  
✅ Server-side Data Processing  
✅ Portable and Low-Cost Design  
✅ Embedded + Cloud Architecture  

---

## 🛠 Hardware Components

- Raspberry Pi Pico
- MAX30102 Pulse Oximeter Sensor
- OLED Display
- Arduino-compatible Board
- Breadboard
- Jumper Wires
- Power Supply

---

## 💻 Software & Technologies

- MicroPython
- Arduino C/C++
- Python
- MQTT Protocol
- I2C Communication
- IoT Dashboard Integration

---

## 📂 Project Structure

```bash
portable-stress-monitor/
│
├── firmware/
│   ├── pico_micropython/
│   └── arduino/
│
├── server/
│
├── dashboard/
│   ├── prototype-v1/
│   ├── prototype-v2/
│   └── final-dashboard/
│
├── docs/
│
├── screenshots/
│
├── media/
│
├── README.md
├── LICENSE
├── .gitignore
└── requirements.txt
```

---

## ⚙ Working Principle

### 1. Data Acquisition
The MAX30102 sensor collects pulse and oxygen saturation data.

### 2. Embedded Processing
Raspberry Pi Pico / Arduino processes the raw sensor values.

### 3. Communication
Data is transmitted using I2C and IoT communication protocols.

### 4. Visualization
Live readings are displayed on OLED screens and dashboards.

### 5. Analysis
Collected data can be monitored for stress-related physiological trends.

---

## 🧠 Challenges Faced

- Sensor calibration
- Signal noise filtering
- Stable I2C communication
- Real-time data synchronization
- Embedded debugging
- Dashboard integration

---

## 🚀 Future Improvements

- AI-based stress prediction
- Mobile application integration
- Cloud database logging
- Battery optimization
- Wearable implementation

---

## 📚 Learning Outcomes

This project helped in understanding:

- Embedded systems
- Sensor interfacing
- Microcontroller programming
- IoT communication
- Real-time data visualization
- Hardware debugging

---

## 🤝 Contributions

Contributions, suggestions, and feedback are welcome.

---

## 👨‍💻 Author

Nikunj Joshi
B.Tech Student | Embedded Systems | IoT | Problem Solver

LinkedIn: https://www.linkedin.com/in/nikunj-joshi-83390235a/

---

## ⭐ Support

If you found this project useful, consider starring the repository.
