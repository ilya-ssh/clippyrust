import sys
import threading
from system_info import background_system_info_updater
from ide import RustTUIIDE
if __name__ == "__main__":
    threading.Thread(target=background_system_info_updater, daemon=True).start()
    start_path = "./" if len(sys.argv) < 2 else sys.argv[1]
    ide = RustTUIIDE(start_path)
    ide.run()
