import face_recognition
import cv2
import numpy as np
import os
import mysql.connector
import serial
import time
import tkinter as tk
from tkinter import Frame, Label, Button
import uuid

# --- Konfigurasi Serial ---
SERIAL_PORT = "COM5"
BAUD_RATE = 115200

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    time.sleep(2)
    print(f"Connected to Arduino on {SERIAL_PORT}")
except Exception as e:
    print(f"Failed to connect to Arduino: {e}")
    ser = None

# --- Direktori data ---
KNOWN_FACES_DIR = "known_faces"
LOG_CAPTURE_DIR = "log_capture"
os.makedirs(LOG_CAPTURE_DIR, exist_ok=True)

# --- Load wajah dikenal ---
known_face_encodings = []
known_face_names = []
for filename in os.listdir(KNOWN_FACES_DIR):
    if filename.lower().endswith((".jpg", ".png")):
        image_path = os.path.join(KNOWN_FACES_DIR, filename)
        image = face_recognition.load_image_file(image_path)
        encodings = face_recognition.face_encodings(image)
        if encodings:
            known_face_encodings.append(encodings[0])
            known_face_names.append(os.path.splitext(filename)[0])

# --- Helper ---
def send_command(cmd):
    if not ser:
        return
    try:
        ser.write((cmd + "\n").encode())
        print(f"[SERIAL] Sent: {cmd}")
    except Exception as e:
        print(f"[ERROR] Failed to send command: {e}")

def save_capture(frame):
    filename = f"{uuid.uuid4().hex}.jpg"
    filepath = os.path.join(LOG_CAPTURE_DIR, filename)
    cv2.imwrite(filepath, frame)
    return filename

def save_log(name, capture_filename):
    try:
        db = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="smartdoorlock"
        )
        cursor = db.cursor()
        cursor.execute("INSERT INTO logs (name, log_capture) VALUES (%s, %s)", (name, capture_filename))
        db.commit()
        cursor.close()
        db.close()
        print(f"[INFO] Log tersimpan: {name}, file: {capture_filename}")
    except Exception as e:
        print(f"[ERROR] Database error: {e}")



# --- GUI dengan Frame ---
class SmartDoorlockApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Smart Doorlock - 2FA")
        self.geometry("500x300")

        self.current_frame = None
        self.show_frame(StartPage)

        # Loop cek serial
        self.after(200, self.listen_serial)

    def show_frame(self, frame_class, message=None):
        """Ganti frame"""
        if self.current_frame is not None:
            self.current_frame.destroy()

        self.current_frame = frame_class(self, message)
        self.current_frame.pack(fill="both", expand=True)

    def listen_serial(self):
        if ser and ser.in_waiting > 0:
            line = ser.readline().decode().strip()
            print("Arduino:", line)

            if isinstance(self.current_frame, WaitFingerprintPage) and line == "FINGER_OK":
                self.show_frame(FacePage)
            # Jika fingerprint gagal → balik ke StartPage
            elif isinstance(self.current_frame, WaitFingerprintPage) and line == "FINGER_FAIL":
                self.show_frame(StartPage, message="Fingerprint gagal, silakan coba lagi.")

        self.after(200, self.listen_serial)

# --- Frame Halaman ---
class StartPage(Frame):
    def __init__(self, master, message=None):
        super().__init__(master)
        Label(self, text="Smart Doorlock", font=("Arial", 16)).pack(pady=20)
        if message:
            Label(self, text=message, fg="blue").pack(pady=5)
        Button(self, text="Start", command=lambda: master.show_frame(WaitFingerprintPage)).pack(pady=20)

class WaitFingerprintPage(Frame):
    def __init__(self, master, message=None):
        super().__init__(master)
        Label(self, text="Silakan scan Fingerprint...", font=("Arial", 14)).pack(pady=40)
        Label(self, text="Menunggu data dari Arduino...", fg="gray").pack()

class FacePage(Frame):
    def __init__(self, master, message=None):
        super().__init__(master)
        Label(self, text="Face Recognition", font=("Arial", 16)).pack(pady=20)
        Label(self, text="Silakan scan wajah Anda", fg="gray").pack()

        self.master = master
        self.after(500, self.run_face_recognition)

    def run_face_recognition(self):
        video_capture = cv2.VideoCapture(0)
        face_verified = False
        start_time = time.time()

        while True:
            ret, frame = video_capture.read()
            if not ret:
                continue

            rgb_frame = frame[:, :, ::-1]
            face_locations = face_recognition.face_locations(rgb_frame)
            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

            for face_encoding in face_encodings:
                matches = face_recognition.compare_faces(known_face_encodings, face_encoding)
                name = "Pengguna Tidak Dikenal"

                face_distances = face_recognition.face_distance(known_face_encodings, face_encoding)
                best_match_index = np.argmin(face_distances)
                if matches[best_match_index]:
                    name = known_face_names[best_match_index]

                capture_filename = save_capture(frame)
                save_log(name, capture_filename)

                if name != "Pengguna Tidak Dikenal":
                    send_command("FACE_OK")
                    face_verified = True
                    video_capture.release()
                    cv2.destroyAllWindows()
                    self.master.show_frame(StartPage, message=f"Akses diterima: {name}")
                    return
                else:
                    send_command("FACE_FAIL")
                    video_capture.release()
                    cv2.destroyAllWindows()
                    self.master.show_frame(StartPage, message="Face recognition gagal - Pengguna Tidak Dikenal")
                    return

            cv2.imshow("Face Recognition", frame)

            if face_verified:
                break

            if (time.time() - start_time) > 10:
                send_command("FACE_FAIL")
                video_capture.release()
                cv2.destroyAllWindows()
                self.master.show_frame(StartPage, message="Waktu habis! Face recognition gagal.")
                return

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        if not face_verified:
            send_command("FACE_FAIL")
            self.master.show_frame(StartPage, message="Face recognition gagal.")
        video_capture.release()
        cv2.destroyAllWindows()

# --- Jalankan App ---
if __name__ == "__main__":
    app = SmartDoorlockApp()
    app.mainloop()
