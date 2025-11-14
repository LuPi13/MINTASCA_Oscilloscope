# MINTASCA_Oscilloscope

**참고:** 이 PC 애플리케이션은 아래의 CAN 모터 제어 펌웨어와 함께 사용하도록 제작되었습니다.

- **펌웨어 저장소:** [LuPi13/MINTASCA_CAN_motor_control](https://github.com/LuPi13/MINTASCA_CAN_motor_control)

---

이 프로그램은 `pyserial`과 `tkinter`를 사용하여 CAN-to-USART 장치를 제어하고 모니터링하기 위한 PC용 GUI 애플리케이션입니다.

## 주요 기능

- **GUI 인터페이스**: 그래픽 사용자 인터페이스를 통해 장치에 명령을 보내고 데이터를 시각화합니다.
- **시리얼 통신**: 지정된 COM 포트를 통해 타겟 장치와 통신합니다.
- **실시간 그래프**: `matplotlib`을 사용하여 특정 데이터(`ID: 0x100`)를 실시간으로 표시합니다.
- **데이터 로깅**: 수신된 `ID: 0x100` 데이터를 `logs` 디렉터리 내의 `.csv` 파일로 기록합니다.

## 주요 설정 변경 방법

대부분의 핵심 설정은 `main.py` 파일의 `App` 클래스 내에 집중되어 있어 쉽게 수정할 수 있습니다.

### 1. 시리얼 포트 설정 변경

COM 포트, 통신 속도(Baud rate) 등 시리얼 설정을 변경하려면 `SerialManager` 클래스 내부의 아래 코드를 수정하십시오.

```python
# main.py -> class SerialManager -> run() 메서드 내부
self.serial_port = serial.Serial('COM5', 921600, timeout=1)
```

### 2. 버튼 이름 및 전송 명령어 변경

버튼에 표시되는 이름이나 해당 버튼이 전송하는 시리얼 명령어를 변경하려면, `App` 클래스의 `__init__` 메서드 내에 있는 `self.button_map` 딕셔너리를 수정하십시오.

- **버튼 이름을 변경하려면**: 딕셔너리의 **키(key)**를 수정합니다.
- **전송 명령어를 변경하려면**: `"cmd"` 필드의 **값(value)**을 수정합니다.

```python
# main.py -> class App -> __init__() 메서드 내부
self.button_map = {
    # 키 (버튼 이름)           값 (전송할 명령어)
    "Handshake":        {"cmd": "D4 1 00\n"},
    "SCA Enable":       {"cmd": "D4 2 2A 01\n"},
    # ... 등등
}
```

### 3. 장치 응답 처리 로직 변경

장치로부터 특정 응답을 받았을 때 프로그램의 동작(예: 버튼 활성화/비활성화)을 변경하려면, `App` 클래스의 `handle_serial_response` 메서드를 수정하십시오.

```python
# main.py -> class App -> handle_serial_response() 메서드 내부

# 예시: Handshake 응답을 처리하는 로직
if "ID:0XD4" in normalized_response and "DLC:2" in normalized_response and "DATA:0001" in normalized_response:
    self.buttons["sca_enable"].config(state=tk.NORMAL)
    print("응답 확인: Handshake 성공. SCA Enable 활성화됨.")
```

### 4. 데이터 파싱 로직 변경 (ID: 0x100)

`ID: 0x100` 데이터의 파싱 방법을 변경하려면, `App` 클래스의 `parse_id_100_data` 메서드를 수정하십시오. 이 메서드는 수신된 raw hex 데이터를 전압, 전류 등 의미 있는 값으로 변환하는 역할을 합니다.

```python
# main.py -> class App -> parse_id_100_data() 메서드 내부
def parse_id_100_data(self, message):
    # ... 파싱 로직 ...
    voltage = int(hex_values[0] + hex_values[1], 16)
    # ...
```