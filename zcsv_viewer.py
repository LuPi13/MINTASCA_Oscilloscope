import matplotlib.pyplot as plt
from matplotlib.widgets import Cursor
import matplotlib.dates as mdates
import csv
from datetime import datetime

def load_csv_data(filepath):
    """CSV 파일에서 데이터를 읽어옴"""
    timestamps = []
    voltages = []
    currents = []
    gpio_pins = []
    
    with open(filepath, 'r') as file:
        reader = csv.DictReader(file)
        for row in reader:
            # timestamp_ms를 datetime 객체로 변환
            timestamp_ms = float(row['timestamp_ms'])
            timestamps.append(datetime.fromtimestamp(timestamp_ms / 1000))
            
            voltages.append(int(row['voltage_mV']))
            currents.append(int(row['current_mA']))
            gpio_pins.append(int(row['gpio_pin_state']))
    
    return timestamps, voltages, currents, gpio_pins

def plot_data(filepath):
    """CSV 데이터를 main.py와 동일한 형태의 그래프로 시각화"""
    print(f"Loading data from {filepath}...")
    timestamps, voltages, currents, gpio_pins = load_csv_data(filepath)
    print(f"Loaded {len(timestamps)} data points.")
    
    # Create figure with 3 subplots (height_ratios: 전압=3, 전류=3, GPIO=1)
    fig, axs = plt.subplots(3, 1, sharex=True, figsize=(12, 10),
                            gridspec_kw={'height_ratios': [3, 3, 1]})
    fig.tight_layout(pad=3.0)
    
    # Voltage plot (크게)
    axs[0].plot(timestamps, voltages, color='r', linewidth=0.5)
    axs[0].set_ylabel("Voltage (mV)", fontsize=12)
    axs[0].set_ylim(30000, 50000)
    axs[0].grid(True, alpha=0.3)
    
    # Current plot (크게)
    axs[1].plot(timestamps, currents, color='g', linewidth=0.5)
    axs[1].set_ylabel("Current (mA)", fontsize=12)
    axs[1].grid(True, alpha=0.3)
    
    # GPIO Pin State plot (작게)
    axs[2].step(timestamps, gpio_pins, where='post', color='b', linewidth=0.8)
    axs[2].set_ylabel("GPIO Pin", fontsize=12)
    axs[2].set_yticks([0, 1])
    axs[2].set_yticklabels(['LOW', 'HIGH'])
    axs[2].grid(True, alpha=0.3)
    
    # Format x-axis - 소숫점 없는 깔끔한 시간 포맷
    axs[2].set_xlabel("Time")
    
    # 시간 포맷 설정: 분:초 형식 (소숫점 제거)
    date_formatter = mdates.DateFormatter('%H:%M:%S')
    axs[2].xaxis.set_major_formatter(date_formatter)
    
    fig.autofmt_xdate()
    
    plt.suptitle(f"Data from {filepath}", fontsize=14, fontweight='bold', y=0.995)
    plt.tight_layout()
    
    # 마우스 휠 줌 기능 추가
    def zoom_factory(ax, base_scale=1.5):
        def zoom(event):
            if event.inaxes != ax:
                return
            cur_xlim = ax.get_xlim()
            cur_ylim = ax.get_ylim()
            xdata = event.xdata
            ydata = event.ydata
            
            if event.button == 'up':
                scale_factor = 1 / base_scale
            elif event.button == 'down':
                scale_factor = base_scale
            else:
                return
            
            new_width = (cur_xlim[1] - cur_xlim[0]) * scale_factor
            new_height = (cur_ylim[1] - cur_ylim[0]) * scale_factor
            
            relx = (cur_xlim[1] - xdata) / (cur_xlim[1] - cur_xlim[0])
            rely = (cur_ylim[1] - ydata) / (cur_ylim[1] - cur_ylim[0])
            
            ax.set_xlim([xdata - new_width * (1 - relx), xdata + new_width * relx])
            ax.set_ylim([ydata - new_height * (1 - rely), ydata + new_height * rely])
            fig.canvas.draw_idle()
        
        fig.canvas.mpl_connect('scroll_event', zoom)
        return zoom
    
    # 모든 서브플롯에 휠 줌 기능 추가
    for ax in axs:
        zoom_factory(ax)
    
    plt.show()

if __name__ == "__main__":
    # CSV 파일 경로 지정 (최신 로그)
    csv_filepath = "logs/2025-11-19_17-34-39.csv"
    
    try:
        plot_data(csv_filepath)
    except FileNotFoundError:
        print(f"Error: File '{csv_filepath}' not found!")
        print("Please check the file path and try again.")
    except Exception as e:
        print(f"Error occurred: {e}")
