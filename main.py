import tkinter as tk
from tkinter import ttk
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("CAN-to-USART Controller")
        self.geometry("1000x800")

        # Main frame
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # --- Controls Frame ---
        controls_frame = ttk.LabelFrame(main_frame, text="Controls", padding="10")
        controls_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        self.buttons = {}
        button_texts = [
            "Handshake", "SCA Enable", "SCA Disable", "Pos. S-curve",
            "Set Max Velocity", "Start Recording", "Stop Recording",
            "Goto HIGH", "Goto LOW"
        ]

        for i, text in enumerate(button_texts):
            btn_name = text.replace(" ", "_").lower()
            button = ttk.Button(controls_frame, text=text, command=lambda t=text: self.on_button_click(t))
            button.pack(fill=tk.X, pady=5)
            self.buttons[btn_name] = button

        # --- Oscilloscope Frame ---
        scope_frame = ttk.LabelFrame(main_frame, text="Oscilloscope", padding="10")
        scope_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

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

        self.initialize_button_states()

    def initialize_button_states(self):
        """Initializes all buttons to their default states."""
        for name, button in self.buttons.items():
            if name != "handshake":
                button.config(state=tk.DISABLED)

    def on_button_click(self, button_name):
        """Placeholder for button click events."""
        print(f"{button_name} clicked!")

if __name__ == "__main__":
    app = App()
    app.mainloop()
