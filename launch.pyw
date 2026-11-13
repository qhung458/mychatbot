"""Open the local chatbot from the Windows desktop shortcut."""
import json
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser


ROOT = Path(__file__).resolve().parent
URL = 'http://127.0.0.1:8000/'


def server_running():
    try:
        with urlopen(URL + 'api/config', timeout=1) as response:
            config = json.load(response)
    except (URLError, TimeoutError, ValueError):
        return False
    return 'budget_policy' in config and 'model' in config


def ensure_server():
    if server_running():
        return
    log_dir = ROOT / 'data'
    log_dir.mkdir(exist_ok=True)
    with (log_dir / 'launcher.log').open('ab') as log:
        process = subprocess.Popen(
            [str(Path(sys.executable).with_name('python.exe')), '-m', 'uvicorn',
             'app.main:app', '--host', '127.0.0.1', '--port', '8000'],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if server_running():
            return
        if process.poll() is not None:
            break
        time.sleep(0.3)
    raise RuntimeError(f'Không mở được chatbot. Xem nhật ký tại {log_dir / "launcher.log"}.')


if __name__ == '__main__':
    try:
        ensure_server()
        if not webbrowser.open(URL):
            raise RuntimeError(f'Anh mở địa chỉ này trong trình duyệt: {URL}')
    except (OSError, RuntimeError) as error:
        from tkinter import messagebox

        messagebox.showerror('OLP Chatbot', str(error))
