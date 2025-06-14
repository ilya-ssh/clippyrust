import os
import time
import random
import psutil
import GPUtil
from rich.text import Text
from rich.color import Color
system_info = {"cpu": "", "ram": "", "vram": "", "directory": ""}

session_random_message = None

def get_session_random_message():
    global session_random_message
    if session_random_message is None:
        messages = ["Let's get rusty!","Debugging is fun!","Rustaceans unite!","Embrace the compiler errors!","Optimizing your code..."]
        session_random_message = random.choice(messages)
    return session_random_message

def background_system_info_updater():
    while True:
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_freq = psutil.cpu_freq().current if psutil.cpu_freq() else 0
        system_info["cpu"] = f"CPU: {cpu_freq:.1f}MHz | {cpu_count} cores | {cpu_percent}% usage"
        ram = psutil.virtual_memory()
        total_ram = ram.total / (1024 ** 3)
        used_ram = ram.used / (1024 ** 3)
        ram_percent = ram.percent
        system_info["ram"] = f"RAM: {used_ram:.2f}GB / {total_ram:.2f}GB ({ram_percent}%)"
        try:
            gpus = GPUtil.getGPUs()
            if not gpus:
                system_info["vram"] = "VRAM: No GPU detected"
            else:
                gpu_info = []
                for gpu in gpus:
                    gpu_info.append(f"{gpu.name}: {gpu.memoryUsed}MB / {gpu.memoryTotal}MB ({gpu.memoryUtil * 100:.1f}%)")
                system_info["vram"] = "VRAM: " + ", ".join(gpu_info)
        except Exception as e:
            system_info["vram"] = f"VRAM: Error retrieving VRAM info ({e})"
        system_info["directory"] = f"Directory: {os.getcwd()}"
        time.sleep(1)

def make_neofetch_text(CLIPPY_ASCII, LLM_NAME, CLIPPY_VERSION):
    def generate_gradient(start_color: str, end_color: str, steps: int):
        start = Color.parse(start_color).triplet
        end = Color.parse(end_color).triplet
        gradient = []
        for step in range(steps):
            interpolated = tuple(
                int(start[i] + (end[i] - start[i]) * (step / (steps - 1)))
                for i in range(3)
            )
            gradient.append(f"rgb({interpolated[0]},{interpolated[1]},{interpolated[2]})")
        return gradient

    gradient_colors = generate_gradient("#8A2BE2", "#00FF00", 78)
    art_lines = CLIPPY_ASCII.strip("\n").splitlines()
    max_art_width = max(len(line) for line in art_lines)
    gradient_block_width = 32
    gradient_block_height = 10
    cpu_info = system_info["cpu"]
    ram_info = system_info["ram"]
    vram_info = system_info["vram"]
    current_directory = system_info["directory"]
    random_message = get_session_random_message()
    info_lines = [cpu_info, ram_info, vram_info, current_directory, random_message]
    info_start_index = gradient_block_height
    text_obj = Text()
    for i, line in enumerate(art_lines):
        text_obj.append(line.ljust(max_art_width))
        if i < gradient_block_height:
            text_obj.append("  ")
            row_color_offset = (i * 4) % len(gradient_colors)
            for j in range(gradient_block_width):
                color = gradient_colors[(row_color_offset + j) % len(gradient_colors)]
                text_obj.append("██", color)
        if i == info_start_index:
            text_obj.append("  ")
            text_obj.append("Clippy IDE v", "cyan")
            text_obj.append(CLIPPY_VERSION, "cyan")
        elif i == info_start_index + 1:
            text_obj.append("  ")
            text_obj.append("Using LLM: ", "green")
            text_obj.append(LLM_NAME, "green")
        elif i == info_start_index + 2:
            text_obj.append("  ")
            text_obj.append(cpu_info, "magenta")
        elif i == info_start_index + 3:
            text_obj.append("  ")
            text_obj.append(ram_info, "magenta")
        elif i == info_start_index + 4:
            text_obj.append("  ")
            text_obj.append(vram_info, "magenta")
        elif i == info_start_index + 5:
            text_obj.append("  ")
            text_obj.append(current_directory, "magenta")
        elif i == info_start_index + 6:
            text_obj.append("  ")
            text_obj.append(random_message, "magenta")
        text_obj.append("\n")
    total_info_lines = len(info_lines)
    for idx in range(gradient_block_height, gradient_block_height + total_info_lines):
        if idx < len(art_lines):
            continue
        if idx - gradient_block_height >= len(info_lines):
            break
        info = info_lines[idx - gradient_block_height]
        text_obj.append(" " * max_art_width)
        text_obj.append(f"  {info}\n", style="bold magenta")
    return text_obj
