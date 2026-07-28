import subprocess
import time
import sys
import webview
import atexit

PROJECT_ROOT = "/home/kiros-li/Documents/GitHub/AiTrader"

backend_process = None

def start_backend():
    global backend_process
    backend_process = subprocess.Popen(
        ["bash", "scripts/run_gui.sh"],
        cwd=PROJECT_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

def stop_backend():
    if backend_process:
        backend_process.terminate()
        try:
            backend_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            backend_process.kill()

atexit.register(stop_backend)

if __name__ == "__main__":
    start_backend()
    time.sleep(6)

    window = webview.create_window(
        "AiTrader",
        "http://localhost:5173",
        width=1600,
        height=1000
    )
    webview.start()
    stop_backend()
