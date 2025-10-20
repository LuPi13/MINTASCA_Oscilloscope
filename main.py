import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import threading
import queue
import serial
import time
import os
import csv
from datetime import datetime

class DataLogger:
    def __init__(self):
        self.file = None
        self.writer = None
        self.is_logging = False
        # Ensure logs directory exists
        os.makedirs("logs", exist_ok=True)

    def start(self):
        if self.is_logging:
            self.stop()
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filepath = os.path.join("logs", f"{timestamp}.csv")
        
        self.file = open(filepath, 'w', newline='')
        self.writer = csv.writer(self.file)
        # Write header
        self.writer.writerow(["timestamp_ms", "voltage_mV", "current_mA", "pwm_duty_permille", "pwm_pin_state", "hyst_pin_state"])
        self.is_logging = True
        print(f"Logging started to {filepath}")

    def write_row(self, data_row):
        if self.writer and self.is_logging:
            self.writer.writerow([datetime.now().timestamp() * 1000] + data_row)

    def stop(self):
        if self.file:
            self.file.close()
            self.file = None
            self.writer = None
        self.is_logging = False
        print("Logging stopped.")


class SerialManager(threading.Thread):
    def __init__(self, command_queue, data_queue):
        super().__init__()
        self.command_queue = command_queue
        self.data_queue = data_queue
        self.serial_port = None
        self.stop_event = threading.Event()
        self.recording = False
        self.last_sent_time = 0
        self.recording_interval = 0.001 # 1ms

    def run(self):
        try:
            # 하드코딩된 포트 정보 사용
            self.serial_port = serial.Serial('COM5', 115200, timeout=1)
            self.data_queue.put(("status", "Serial port opened successfully."))
        except serial.SerialException as e:
            self.data_queue.put(("status", f"Error opening serial port: {e}"))
            return

        while not self.stop_event.is_set():
            # Check for incoming commands from the GUI
            try:
                command = self.command_queue.get_nowait()
                if command == "stop":
                    self.stop_event.set()
                    continue
                elif command.startswith("send:"):
                    self.send_command(command[5:])
                elif command == "start_recording":
                    self.recording = True
                    self.last_sent_time = time.time()
                elif command == "stop_recording":
                    self.recording = False

            except queue.Empty:
                pass

            # Handle periodic sending if recording is active
            if self.recording:
                current_time = time.time()
                if (current_time - self.last_sent_time) >= self.recording_interval:
                    self.send_command("101 1 1\n")
                    self.last_sent_time = current_time

            # Read data from serial port
            if self.serial_port.in_waiting > 0:
                try:
                    line = self.serial_port.readline().decode('utf-8').strip()
                    if line:
                        self.data_queue.put(("serial", line))
                except UnicodeDecodeError:
                    pass
            
            # A small sleep to prevent the loop from consuming 100% CPU
            time.sleep(0.0001)

        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.data_queue.put(("status", "Serial port closed."))

    def send_command(self, command):
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.write(command.encode('utf-8'))
            # To avoid flooding the console, we don't print the periodic message
            if "100 1 1" not in command:
                print(f"Sent: {command.strip()}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CAN-to-USART Controller")
        self.geometry("1920x1080")

        self.command_queue = queue.Queue()
        self.data_queue = queue.Queue()
        self.last_command_sent = None
        self.logger = DataLogger()

        # Graphing data lists
        self.timestamps = []
        self.voltages = []
        self.currents = []
        self.duties = []
        self.pwm_pins = []
        self.hyst_pins = []

        # Main frame
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # Configure grid layout for the main_frame to make it responsive
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)  # Controls column
        main_frame.grid_columnconfigure(1, weight=4)  # Scope column (4x the width change)

        # --- Controls Frame ---
        controls_frame = ttk.LabelFrame(main_frame, text="Controls", padding="10")
        controls_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        # --- Oscilloscope Frame ---
        scope_frame = ttk.LabelFrame(main_frame, text="Oscilloscope", padding="10")
        scope_frame.grid(row=0, column=1, sticky="nsew")

        # Matplotlib Figure
        self.fig, self.axs = plt.subplots(4, 1, sharex=True, figsize=(8, 6))
        self.fig.tight_layout(pad=3.0)

        self.axs[0].set_title("Voltage (mV)")
        self.axs[1].set_title("Current (mA)")
        self.axs[2].set_title("PWM Duty (permille)")
        self.axs[3].set_title("Pin States")
        
        self.axs[3].set_yticks([0, 1])
        self.axs[3].set_yticklabels(['LOW', 'HIGH'])

        self.canvas = FigureCanvasTkAgg(self.fig, master=scope_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas.draw()

        self.buttons = {}
        self.button_map = {
            "Handshake": {"cmd": "D4 1 00\n"},
            "SCA Enable": {"cmd": "D4 2 2A 01\n"},
            "SCA Disable": {"cmd": "D4 2 2A 00\n"},
            "Pos. S-curve mode": {"cmd": "D4 2 07 06\n"},
            "Set Velocity": {"cmd": "D4 5 1F 02 88 88 88\n"},
            "Start Recording": {"cmd": "start_recording"},
            "Stop Recording": {"cmd": "stop_recording"},
            "Goto HIGH": {"cmd": "D4 5 0A 64 00 00 00\n"},
            "Goto LOW": {"cmd": "D4 5 0A 00 00 00 00\n"}
        }
        
        button_texts = list(self.button_map.keys())
        
        # Configure a style for the buttons to increase font size
        style = ttk.Style(self)
        style.configure('TButton', font=('Helvetica', 16, 'bold'))

        # Configure grid layout for the controls_frame to make buttons resize vertically
        for i in range(len(button_texts)):
            controls_frame.grid_rowconfigure(i, weight=1)
        controls_frame.grid_columnconfigure(0, weight=1)

        for i, text in enumerate(button_texts):
            btn_name = text.replace(" ", "_").lower()
            button = ttk.Button(controls_frame, text=text, command=lambda t=text: self.on_button_click(t))
            button.grid(row=i, column=0, sticky="nsew", pady=5)
            self.buttons[btn_name] = button

        self.initialize_button_states()
        self.start_serial_thread()
        self.process_serial_data()

        self.after_id = None
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def initialize_button_states(self):
        """Initializes all buttons to their default states."""
        for name, button in self.buttons.items():
            if name != "handshake":
                button.config(state=tk.DISABLED)

    def process_serial_data(self):
        """Checks the data queue for new data from the serial thread and processes it."""
        try:
            message_type, data = self.data_queue.get_nowait()
            if message_type == "status":
                print(f"Status: {data}")
            elif message_type == "serial":
                # Printing is now handled in handle_serial_response to show the trimmed message
                self.handle_serial_response(data)
        except queue.Empty:
            pass
        finally:
            self.after_id = self.after(100, self.process_serial_data)

    def handle_serial_response(self, response):
        """Parses serial responses and updates button states accordingly."""
        
        # Find the start of the actual message, which should be "ID:"
        try:
            # Make the search case-insensitive to handle "ID:" or "id:"
            start_index = response.upper().index("ID:")
            # Slice the string to get only the relevant part
            actual_message = response[start_index:]
            print(f"Received: {actual_message}") # Print the trimmed message
        except ValueError:
            # "ID:" not found, this is likely an echo or debug message we can ignore
            print(f"Ignored non-standard message: {response}")
            return

        # Normalize the actual message for easier comparison
        normalized_response = ''.join(actual_message.split()).upper()

        # Handle ID:0x100 for logging and graphing
        if "ID:0X100" in normalized_response:
            parsed_data = self.parse_id_100_data(actual_message)
            if parsed_data:
                self.logger.write_row(parsed_data)
                self.update_graph(parsed_data)
            return # Stop further processing for this message

        # Handshake: "ID: 0XD4, DLC: 2, Data: 00 01"
        if "ID:0XD4" in normalized_response and "DLC:2" in normalized_response and "DATA:0001" in normalized_response:
            self.buttons["sca_enable"].config(state=tk.NORMAL)
            print("Response OK: Handshake successful.")

        # SCA Enable or Disable: both respond with "ID: 0XD4, DLC: 2, Data: 2A 01"
        elif "ID:0XD4" in normalized_response and "DLC:2" in normalized_response and "DATA:2A01" in normalized_response:
            if self.last_command_sent == "SCA Enable":
                self.buttons["sca_enable"].config(state=tk.DISABLED)
                self.buttons["sca_disable"].config(state=tk.NORMAL)
                self.buttons["pos._s-curve"].config(state=tk.NORMAL)
                print("Response OK: SCA Enabled.")
            elif self.last_command_sent == "SCA Disable":
                # Per object.md, disable action should disable almost all buttons
                self.buttons["sca_enable"].config(state=tk.NORMAL)
                self.buttons["sca_disable"].config(state=tk.DISABLED)
                self.buttons["pos._s-curve"].config(state=tk.DISABLED)
                self.buttons["set_max_velocity"].config(state=tk.DISABLED)
                self.buttons["start_recording"].config(state=tk.DISABLED)
                self.buttons["stop_recording"].config(state=tk.DISABLED)
                self.buttons["goto_high"].config(state=tk.DISABLED)
                self.buttons["goto_low"].config(state=tk.DISABLED)
                print("Response OK: SCA Disabled.")

        # Pos. S-curve: "ID: 0XD4, DLC: 2, Data: 07 06" -> Actual response is 0701
        elif "ID:0XD4" in normalized_response and "DLC:2" in normalized_response and "DATA:0701" in normalized_response:
            self.buttons["set_max_velocity"].config(state=tk.NORMAL)
            print("Response OK: Pos. S-curve set.")

        # Set Max Velocity: "ID: 0XD4, DLC: 2, Data: 1F 01"
        elif "ID:0XD4" in normalized_response and "DLC:2" in normalized_response and "DATA:1F01" in normalized_response:
            self.buttons["start_recording"].config(state=tk.NORMAL)
            self.buttons["goto_high"].config(state=tk.NORMAL)
            self.buttons["goto_low"].config(state=tk.NORMAL)
            print("Response OK: Max velocity set.")

    def on_button_click(self, button_name):
        """Handles button click events by sending commands to the serial thread."""
        print(f"{button_name} clicked!")
        self.last_command_sent = button_name # Store the last sent command
        
        action = self.button_map.get(button_name)
        if not action:
            return

        command = action["cmd"]
        if command == "start_recording":
            self.clear_graph()
            self.logger.start()
            self.command_queue.put(command)
            self.buttons["start_recording"].config(state=tk.DISABLED)
            self.buttons["stop_recording"].config(state=tk.NORMAL)
        elif command == "stop_recording":
            self.logger.stop()
            self.command_queue.put(command)
            self.buttons["start_recording"].config(state=tk.NORMAL)
            self.buttons["stop_recording"].config(state=tk.DISABLED)
        else:
            self.command_queue.put(f"send:{command}")

    def start_serial_thread(self):
        self.serial_thread = SerialManager(self.command_queue, self.data_queue)
        self.serial_thread.daemon = True
        self.serial_thread.start()

    def on_closing(self):
        """Handles window closing event."""
        print("Closing application... sending stop command to serial thread.")
        if self.after_id:
            self.after_cancel(self.after_id)
        self.command_queue.put("stop")
        self.serial_thread.join(timeout=2)
        print("Serial thread closed. Exiting.")
        self.destroy()

    def parse_id_100_data(self, message):
        """Parses the data string for ID 0x100."""
        try:
            parts = message.split('Data:')
            if len(parts) < 2:
                return None
            
            hex_values = parts[1].strip().split()
            if len(hex_values) < 8:
                return None

            voltage = int(hex_values[0] + hex_values[1], 16)
            current = int(hex_values[2] + hex_values[3], 16)
            duty = int(hex_values[4] + hex_values[5], 16)
            pin_states = int(hex_values[6], 16)
            
            pwm_pin = (pin_states >> 1) & 1
            hyst_pin = pin_states & 1
            
            return [voltage, current, duty, pwm_pin, hyst_pin]
        except (ValueError, IndexError):
            return None

    def update_graph(self, parsed_data):
        """Appends new data and redraws the graph."""
        voltage, current, duty, pwm_pin, hyst_pin = parsed_data

        self.timestamps.append(datetime.now())
        self.voltages.append(voltage)
        self.currents.append(current)
        self.duties.append(duty)
        self.pwm_pins.append(pwm_pin)
        self.hyst_pins.append(hyst_pin)

        # Keep the data lists from growing indefinitely
        max_points = 100
        if len(self.timestamps) > max_points:
            self.timestamps.pop(0)
            self.voltages.pop(0)
            self.currents.pop(0)
            self.duties.pop(0)
            self.pwm_pins.pop(0)
            self.hyst_pins.pop(0)

        # Redraw plots
        self.axs[0].clear()
        self.axs[0].plot(self.timestamps, self.voltages, color='r')
        self.axs[0].set_title("Voltage (mV)")

        self.axs[1].clear()
        self.axs[1].plot(self.timestamps, self.currents, color='g')
        self.axs[1].set_title("Current (mA)")

        self.axs[2].clear()
        self.axs[2].plot(self.timestamps, self.duties, color='b')
        self.axs[2].set_title("PWM Duty (permille)")

        self.axs[3].clear()
        self.axs[3].step(self.timestamps, self.pwm_pins, where='post', label='PWM Pin')
        self.axs[3].step(self.timestamps, self.hyst_pins, where='post', label='Hyst Pin')
        self.axs[3].set_title("Pin States")
        self.axs[3].set_yticks([0, 1])
        self.axs[3].set_yticklabels(['LOW', 'HIGH'])
        self.axs[3].legend()

        self.fig.autofmt_xdate()
        self.fig.tight_layout(pad=3.0)
        self.canvas.draw()

    def clear_graph(self):
        """Clears all data from the graph while preserving titles."""
        self.timestamps.clear()
        self.voltages.clear()
        self.currents.clear()
        self.duties.clear()
        self.pwm_pins.clear()
        self.hyst_pins.clear()
        for ax in self.axs:
            # ax.clear() removes everything, including title and labels.
            # Instead, we remove only the lines (the plotted data).
            for line in ax.lines:
                line.remove()
        self.canvas.draw()



if __name__ == "__main__":
    app = App()
    app.mainloop()
