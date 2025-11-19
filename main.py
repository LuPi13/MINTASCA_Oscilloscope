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
        
        self.file = open(filepath, 'w', newline='', buffering=1)  # Line buffering
        self.writer = csv.writer(self.file)
        # Write header
        self.writer.writerow(["timestamp_ms", "voltage_mV", "current_mA", "gpio_pin_state"])
        self.is_logging = True
        print(f"Logging started to {filepath}")

    def write_row(self, data_row):
        """data_row는 [timestamp_ms, voltage, current, gpio_pin] 형태로 받음"""
        if self.writer and self.is_logging:
            self.writer.writerow(data_row)

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
        self.send_count = 0  # 전송 카운터
        self.buffer_warning_count = 0  # 버퍼 경고 카운터

    def run(self):
        try:
            # Non-blocking 모드: timeout=0, write_timeout=0
            # rtscts와 xonxoff를 명시적으로 비활성화
            self.serial_port = serial.Serial(
                port='COM5',
                baudrate=1500000,
                timeout=0,  # Non-blocking read
                write_timeout=0,  # Non-blocking write
                rtscts=False,  # 하드웨어 플로우 컨트롤 비활성화
                xonxoff=False  # 소프트웨어 플로우 컨트롤 비활성화
            )
            self.data_queue.put(("status", "Serial port opened successfully (non-blocking mode)."))
        except serial.SerialException as e:
            self.data_queue.put(("status", f"Error opening serial port: {e}"))
            return

        read_buffer = ""  # 읽기 버퍼 (부분 라인 저장용)        
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
                    self.last_sent_time = time.perf_counter()  # 고정밀 타이머 사용
                    self.send_count = 0
                    self.buffer_warning_count = 0
                    
                    # 시작 전에 버퍼 완전히 클리어 (이전 측정의 잔여 데이터 제거)
                    if self.serial_port and self.serial_port.is_open:
                        try:
                            # 입출력 버퍼 모두 클리어
                            flushed_in = self.serial_port.in_waiting
                            flushed_out = self.serial_port.out_waiting
                            self.serial_port.reset_input_buffer()
                            self.serial_port.reset_output_buffer()
                            read_buffer = ""  # 읽기 버퍼도 초기화
                            if flushed_in > 0 or flushed_out > 0:
                                self.data_queue.put(("status", f"Cleared buffers before start: RX={flushed_in}, TX={flushed_out}"))
                        except (OSError, serial.SerialException) as e:
                            self.data_queue.put(("status", f"Buffer clear error: {e}"))
                    
                    self.data_queue.put(("status", "Recording started with high-precision timer."))
                elif command == "stop_recording":
                    self.recording = False
                    self.data_queue.put(("status", f"Recording stopped. Total commands sent: {self.send_count}, Buffer warnings: {self.buffer_warning_count}"))
                    
                    # 수신 버퍼에 남아있는 데이터 클리어 (잔여 응답 제거)
                    if self.serial_port and self.serial_port.is_open:
                        try:
                            time.sleep(0.05)  # 마지막 응답들이 도착할 시간 대기
                            flushed = self.serial_port.in_waiting
                            if flushed > 0:
                                self.serial_port.reset_input_buffer()
                                self.data_queue.put(("status", f"Cleared {flushed} bytes from RX buffer"))
                                read_buffer = ""  # 읽기 버퍼 초기화
                        except (OSError, serial.SerialException) as e:
                            pass
            except queue.Empty:
                pass

            # Main logic diverges based on recording state for performance
            if self.recording:
                # 고정밀 타이머로 정확한 1ms 간격 유지
                current_time = time.perf_counter()
                if (current_time - self.last_sent_time) >= self.recording_interval:
                    # Write buffer 상태 체크
                    try:
                        if self.serial_port.out_waiting > 1024:  # 버퍼가 1KB 이상 차있으면 경고
                            self.buffer_warning_count += 1
                            if self.buffer_warning_count % 100 == 1:  # 100번마다 한 번씩만 출력
                                self.data_queue.put(("status", f"Warning: TX buffer is filling up ({self.serial_port.out_waiting} bytes)"))
                    except (OSError, AttributeError):
                        pass  # out_waiting이 지원되지 않는 경우 무시
                    
                    # 명령 전송
                    success = self.send_command_nonblocking("101 1 01\n")
                    if success:
                        self.send_count += 1
                    
                    # 다음 전송 시간 계산
                    self.last_sent_time += self.recording_interval
                    # drift 방지: 너무 뒤쳐진 경우 현재 시간으로 재설정
                    if self.last_sent_time < current_time - 0.1:  # 100ms 이상 뒤쳐진 경우
                        self.last_sent_time = current_time
            # recording이 아닐 때도 짧은 sleep만 사용 (항상 빠르게 읽기)
            # time.sleep 제거 - 항상 빠르게 루프 돌면서 데이터 읽기

            # Always try to read incoming data to keep the serial buffer clear
            # 항상 빠르게 읽어서 버퍼가 가득 차는 것을 방지
            if self.serial_port:
                try:
                    # Non-blocking read: 가능한 만큼만 읽음
                    available = self.serial_port.in_waiting
                    if available > 0:
                        # 버퍼가 너무 많이 쌓인 경우 경고
                        if available > 2048:
                            self.data_queue.put(("status", f"Warning: RX buffer has {available} bytes waiting!"))
                        
                        chunk = self.serial_port.read(available)
                        if chunk:
                            try:
                                read_buffer += chunk.decode('utf-8')
                                # 완성된 라인들을 처리
                                while '\n' in read_buffer:
                                    line, read_buffer = read_buffer.split('\n', 1)
                                    line = line.strip()
                                    if line:
                                        # 데이터 수신 시점의 타임스탬프를 즉시 기록
                                        timestamp_ms = time.time() * 1000
                                        self.data_queue.put(("serial", line, timestamp_ms))
                            except UnicodeDecodeError:
                                read_buffer = ""  # 디코딩 실패 시 버퍼 초기화
                except (OSError, serial.SerialException) as e:
                    # Non-blocking 모드에서 발생할 수 있는 예외 처리
                    pass
            
            # recording이 아닐 때만 짧은 sleep (CPU 사용률 절감)
            if not self.recording:
                time.sleep(0.0001)  # 0.1ms sleep (거의 안 자지만 CPU는 조금 쉼)

        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
        self.data_queue.put(("status", "Serial port closed."))

    def send_command_nonblocking(self, command):
        """Non-blocking 방식으로 명령을 전송하고 성공 여부를 반환"""
        if self.serial_port and self.serial_port.is_open:
            try:
                encoded = command.encode('utf-8')
                bytes_written = self.serial_port.write(encoded)
                
                # 부분 전송 체크
                if bytes_written < len(encoded):
                    self.data_queue.put(("status", f"Warning: Partial write ({bytes_written}/{len(encoded)} bytes)"))
                    return False
                return True
            except serial.SerialTimeoutException:
                # write_timeout=0이므로 즉시 반환, 버퍼가 가득 찬 경우
                self.buffer_warning_count += 1
                return False
            except (OSError, serial.SerialException) as e:
                self.data_queue.put(("status", f"Write error: {e}"))
                return False
        return False

    def send_command(self, command):
        """일반 명령 전송 (recording이 아닌 경우)"""
        if self.serial_port and self.serial_port.is_open:
            try:
                encoded = command.encode('utf-8')
                bytes_written = self.serial_port.write(encoded)
                print(f"Sent: {command.strip()} ({bytes_written} bytes)")
                
                if bytes_written < len(encoded):
                    print(f"Warning: Partial write ({bytes_written}/{len(encoded)} bytes)")
            except serial.SerialTimeoutException:
                print("Warning: Write timeout (buffer full)")
            except (OSError, serial.SerialException) as e:
                print(f"Write error: {e}")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CAN-to-USART Controller")
        self.geometry("1920x1080")

        # 큐 크기 제한 제거 (무제한으로 변경)
        self.command_queue = queue.Queue()
        self.data_queue = queue.Queue(maxsize=0)  # maxsize=0은 무제한
        self.last_command_sent = None
        self.logger = DataLogger()
        
        # 통계 정보
        self.total_received = 0
        self.last_queue_size_report = 0
        
        # 상태 변수들 먼저 초기화
        self.after_id = None
        self.is_recording = False  # 이것을 process_serial_data() 호출 전에 초기화!

        # Graphing data lists
        self.timestamps = []
        self.voltages = []
        self.currents = []
        self.gpio_pins = []

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

        # Matplotlib Figure - 3개 서브플롯 (전압, 전류, GPIO 핀)
        # height_ratios: 전압과 전류는 크게(3), GPIO 핀은 작게(1)
        self.fig, self.axs = plt.subplots(3, 1, sharex=True, figsize=(8, 6), 
                                          gridspec_kw={'height_ratios': [3, 3, 1]})
        self.fig.tight_layout(pad=3.0)

        self.axs[0].set_title("Voltage (mV)")
        self.axs[1].set_title("Current (mA)")
        self.axs[2].set_title("GPIO Pin State")
        
        self.axs[2].set_yticks([0, 1])
        self.axs[2].set_yticklabels(['LOW', 'HIGH'])

        self.canvas = FigureCanvasTkAgg(self.fig, master=scope_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas.draw()

        self.buttons = {}
        self.button_map = {
            "Handshake": {"cmd": "D4 1 00\n"},
            "SCA Enable": {"cmd": "D4 2 2A 01\n"},
            "SCA Disable": {"cmd": "D4 2 2A 00\n"},
            "Pos. S-curve": {"cmd": "D4 2 07 06\n"},
            "Set max Velocity": {"cmd": "D4 5 1F 02 88 88 88\n"},
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

        # 입력창과 Send 버튼 추가
        # 버튼 개수만큼 행이 사용되었으므로, 그 다음 행부터 시작
        next_row = len(button_texts)
        
        # 입력창 레이블
        input_label = ttk.Label(controls_frame, text="Custom Command:", font=('Helvetica', 12))
        input_label.grid(row=next_row, column=0, sticky="w", padx=10, pady=(20, 5))
        
        # 입력창 (Entry)
        self.custom_input = ttk.Entry(controls_frame, font=('Helvetica', 14))
        self.custom_input.grid(row=next_row+1, column=0, sticky="ew", padx=10, pady=5)
        
        # Send 버튼
        send_button = ttk.Button(controls_frame, text="Send", command=self.on_send_custom_command)
        send_button.grid(row=next_row+2, column=0, sticky="ew", padx=10, pady=5)
        
        # Enter 키로도 전송 가능하도록
        self.custom_input.bind('<Return>', lambda event: self.on_send_custom_command())

        self.initialize_button_states()
        self.start_serial_thread()
        self.process_serial_data()

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def initialize_button_states(self):
        """Initializes all buttons to their default states."""
        for name, button in self.buttons.items():
            if name not in ["handshake", "start_recording"]:
                button.config(state=tk.DISABLED)
        self.buttons["stop_recording"].config(state=tk.DISABLED)


    def process_serial_data(self):
        """Checks the data queue for new data from the serial thread and processes it."""
        processed_count = 0
        try:
            # 큐에 있는 모든 데이터를 한 번에 처리 (무제한)
            while True:
                message = self.data_queue.get_nowait()
                message_type = message[0]
                
                if message_type == "status":
                    print(f"Status: {message[1]}")
                elif message_type == "serial":
                    # message = ("serial", line, timestamp_ms)
                    line = message[1]
                    timestamp_ms = message[2] if len(message) > 2 else None
                    self.handle_serial_response(line, timestamp_ms)
                    processed_count += 1
                    self.total_received += 1
        except queue.Empty:
            pass
        finally:
            # 큐 크기 모니터링 (1000개마다 보고)
            if self.is_recording and self.total_received % 1000 == 0 and self.total_received > self.last_queue_size_report:
                queue_size = self.data_queue.qsize()
                print(f"Total received: {self.total_received}, Queue size: {queue_size}, Processed this cycle: {processed_count}")
                self.last_queue_size_report = self.total_received
            
            # 큐 처리 주기를 2ms로 단축 (5ms -> 2ms)
            self.after_id = self.after(2, self.process_serial_data)

    def handle_serial_response(self, response, timestamp_ms=None):
        """Parses serial responses and updates button states accordingly."""
        
        try:
            start_index = response.upper().index("ID:")
            actual_message = response[start_index:]
        except ValueError:
            print(f"Ignored non-standard message: {response}")
            return

        # Handle ID:0x100 for logging and graphing
        if "ID:0X100" in ''.join(actual_message.split()).upper():
            parsed_data = self.parse_id_100_data(actual_message)
            if parsed_data:
                # timestamp_ms가 없으면 현재 시간 사용 (하위 호환성)
                if timestamp_ms is None:
                    timestamp_ms = time.time() * 1000
                
                # [timestamp_ms, voltage, current, gpio_pin] 형태로 저장
                log_data = [timestamp_ms] + parsed_data
                self.logger.write_row(log_data)
                self.append_graph_data(parsed_data) # Just append data, don't draw
            return

        # For other messages, print and process
        print(f"Received: {actual_message}")
        normalized_response = ''.join(actual_message.split()).upper()

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
                self.initialize_button_states()
                self.buttons["handshake"].config(state=tk.NORMAL)
                self.buttons["sca_enable"].config(state=tk.NORMAL)
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
        # print(f"{button_name} clicked!")
        self.last_command_sent = button_name
        
        action = self.button_map.get(button_name)
        if not action:
            return

        command = action["cmd"]
        if command == "start_recording":
            self.is_recording = True
            self.total_received = 0
            self.last_queue_size_report = 0
            
            # 데이터 큐 클리어 (이전 측정의 잔여 데이터 제거)
            cleared_count = 0
            try:
                while True:
                    self.data_queue.get_nowait()
                    cleared_count += 1
            except queue.Empty:
                pass
            if cleared_count > 0:
                print(f"Cleared {cleared_count} messages from data queue before starting")
            
            self.clear_graph_data()
            self.clear_canvas()
            self.logger.start()
            self.command_queue.put(command)
            self.buttons["start_recording"].config(state=tk.DISABLED)
            self.buttons["stop_recording"].config(state=tk.NORMAL)
            # 실시간 그래프 업데이트 제거 - recording 중에는 그래프 안 그림!
            # self.periodic_graph_update() # 주석 처리
            print("Recording started - graph will be drawn when stopped")
        elif command == "stop_recording":
            self.is_recording = False
            
            # 즉시 recording 중지 명령 전송
            self.command_queue.put(command)
            
            # 버튼 상태 즉시 업데이트
            self.buttons["start_recording"].config(state=tk.NORMAL)
            self.buttons["stop_recording"].config(state=tk.DISABLED)
            
            print(f"Recording stopped. Total data points: {len(self.timestamps)}")
            print("Waiting for data queue to flush...")
            
            # logger는 나중에 중지 (큐에 남은 데이터가 모두 처리된 후)
            # 500ms 후에 logger 중지 및 그래프 그리기
            self.after(500, self._finish_recording)
        else:
            self.command_queue.put(f"send:{command}")
    
    def on_send_custom_command(self):
        """입력창의 문자열을 읽어서 UART로 전송"""
        command_text = self.custom_input.get().strip()
        
        if not command_text:
            print("No command entered")
            return
        
        # '\n'을 붙여서 전송
        command_with_newline = command_text + '\n'
        
        print(f"Sending custom command: {command_text}")
        self.command_queue.put(f"send:{command_with_newline}")
        
        # 입력창 비우기 (선택사항)
        # self.custom_input.delete(0, tk.END)
    
    def _finish_recording(self):
        """Recording 종료 후속 처리 - 큐가 비워진 후 호출"""
        # 큐 크기 확인
        queue_size = self.data_queue.qsize()
        print(f"Queue size: {queue_size}, Graph data points: {len(self.timestamps)}")
        
        # logger 중지
        self.logger.stop()
        
        # 그래프 그리기
        print("Drawing graph... please wait")
        self.draw_full_graph()
    
    def _finish_stop_recording(self):
        """Stop recording 후속 처리 - 더 이상 사용 안 함"""
        pass

    def start_serial_thread(self):
        self.serial_thread = SerialManager(self.command_queue, self.data_queue)
        self.serial_thread.daemon = True
        self.serial_thread.start()

    def on_closing(self):
        """Handles window closing event."""
        print("Closing application... sending stop command to serial thread.")
        if self.after_id:
            self.after_cancel(self.after_id)
        # graph_update_timer_id는 더 이상 사용 안 함
        self.command_queue.put("stop")
        self.serial_thread.join(timeout=2)
        print("Serial thread closed. Exiting.")
        self.destroy()

    def parse_id_100_data(self, message):
        """Parses the data string for ID 0x100.
        New format: DLC: 5, Data: [0-1](V_mV) [2-3](I_mA) [4](pin state: 0 or 1)
        """
        try:
            parts = message.split('Data:')
            if len(parts) < 2:
                return None
            
            hex_values = parts[1].strip().split()
            if len(hex_values) < 5:
                return None

            # [0-1]: Voltage in mV (16-bit unsigned)
            voltage = int(hex_values[0] + hex_values[1], 16)
            
            # [2-3]: Current in mA (16-bit signed, two's complement)
            unsigned_current = int(hex_values[2] + hex_values[3], 16)
            if unsigned_current > 32767:  # 2**15 - 1
                current = unsigned_current - 65536  # 2**16
            else:
                current = unsigned_current

            # [4]: GPIO pin state (0 or 1)
            gpio_pin = int(hex_values[4], 16)
            
            # Return: [voltage, current, gpio_pin]
            return [voltage, current, gpio_pin]
        except (ValueError, IndexError):
            return None

    def append_graph_data(self, parsed_data):
        """Just appends new data to the data lists.
        parsed_data: [voltage, current, gpio_pin]
        """
        voltage, current, gpio_pin = parsed_data
        self.timestamps.append(datetime.now())
        self.voltages.append(voltage)
        self.currents.append(current)
        self.gpio_pins.append(gpio_pin)

    def draw_full_graph(self):
        """Redraws the graph with all the data collected during the recording session."""
        if not self.timestamps:
            print("No data to draw.")
            return
        
        print(f"Drawing full graph with {len(self.timestamps)} data points...")
        
        # 데이터가 많으면 샘플링해서 그리기 (성능 향상)
        max_points = 10000  # 5000에서 10000으로 증가
        if len(self.timestamps) > max_points:
            # 균등 샘플링
            step = len(self.timestamps) // max_points
            timestamps = self.timestamps[::step]
            voltages = self.voltages[::step]
            currents = self.currents[::step]
            gpio_pins = self.gpio_pins[::step]
            print(f"Sampled down to {len(timestamps)} points for display")
        else:
            timestamps = self.timestamps
            voltages = self.voltages
            currents = self.currents
            gpio_pins = self.gpio_pins
        
        # 그래프 그리기
        self.redraw_plots(timestamps, voltages, currents, gpio_pins)
        
        # 최종 레이아웃 조정 (한 번만)
        self.fig.autofmt_xdate()
        self.fig.tight_layout(pad=2.0)
        self.canvas.draw()
        
        print("Graph drawing completed.")

    def redraw_plots(self, timestamps, voltages, currents, gpio_pins):
        """Helper function to perform the actual plotting."""
        if not timestamps:
            return

        # 전압 그래프 (크게)
        self.axs[0].clear()
        self.axs[0].plot(timestamps, voltages, color='r', linewidth=0.5)
        self.axs[0].set_ylabel("Voltage (mV)")
        self.axs[0].grid(True, alpha=0.3)

        # 전류 그래프 (크게)
        self.axs[1].clear()
        self.axs[1].plot(timestamps, currents, color='g', linewidth=0.5)
        self.axs[1].set_ylabel("Current (mA)")
        self.axs[1].grid(True, alpha=0.3)

        # GPIO 핀 상태 그래프 (작게)
        self.axs[2].clear()
        self.axs[2].step(timestamps, gpio_pins, where='post', color='b', linewidth=0.8)
        self.axs[2].set_ylabel("GPIO Pin")
        self.axs[2].set_yticks([0, 1])
        self.axs[2].set_yticklabels(['LOW', 'HIGH'])
        self.axs[2].grid(True, alpha=0.3)

    def clear_graph_data(self):
        """Clears all data lists."""
        self.timestamps.clear()
        self.voltages.clear()
        self.currents.clear()
        self.gpio_pins.clear()

    def clear_canvas(self):
        """Clears the graph canvas."""
        for ax in self.axs:
            ax.clear() # Clear everything
            # Restore titles and labels
        self.axs[0].set_title("Voltage (mV)")
        self.axs[1].set_title("Current (mA)")
        self.axs[2].set_title("GPIO Pin State")
        self.axs[2].set_yticks([0, 1])
        self.axs[2].set_yticklabels(['LOW', 'HIGH'])
        self.canvas.draw()



if __name__ == "__main__":
    app = App()
    app.mainloop()
