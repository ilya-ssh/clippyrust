import subprocess
import json
import time
import requests
from rich.console import Console
from config import MODEL_PATH, LLAMA_SERVER_HOST, LLAMA_SERVER_PORT, LLAMA_MODE, LLAMA_VPN_BASE_URL, LLAMA_LOCAL_URL

console = Console()

LLAMA_SERVER_URL = (
    LLAMA_VPN_BASE_URL.rstrip("/")
    if LLAMA_MODE.lower() == "vpn"
    else LLAMA_LOCAL_URL.rstrip("/")
)

MAX_RETRIES = 3
BACKOFF_FACTOR = 2

def classify_question(question: str) -> str:
    url = f"{LLAMA_SERVER_URL}/v1/completions"
    classification_prompt = (
    "Classify the user request into ONE of four labels:\n"
    "'analysis'  : code reviews, error checking, detailed analysis\n"
    "'edit'      : requests that want you to change *existing* code\n"
    "'scaffold'  : \"create a new project / folder / file\" style requests\n"
    "'crate_search': for questions that ask to search for Rust crates / libraries\n"
    "'general'   : anything else\n\n"
    "Examples:\n"
    "Q: Can you refactor my foo() to use iterators?\nA: edit\n"
    "Q: Where is the logic bug in my main.rs?\nA: analysis\n"
    "Q: Any game-engine crates in Rust?\nA: crate_search\n"
    "Q: Make me a Rust CLI app called calc that adds two numbers\nA: scaffold\n"
    "Q: How do traits work?\nA: general\n\n"
    f"Q: {question}\nA:"
    )
    payload = {"model": "llama","prompt": classification_prompt,"max_tokens": 4,"temperature": 0.2,"stream": False}
    headers = {"Content-Type": "application/json"}
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=30)
        if response.status_code == 200:
            data = response.json()
            classification = data.get("choices", [{}])[0].get("text", "").strip().lower()
            alias_map = {
                "crate" : "create_search",
                "crate search":  "crate_search",
                "crate-search":  "crate_search",
                "cratesearch":   "crate_search",
            }
            classification = alias_map.get(classification, classification)
            if classification not in {"analysis", "edit", "general","scaffold","crate_search"}:
                classification = "general"
            return classification
        else:
            return "general"
    except Exception as e:
        return "general"
def is_server_running():
    try:
        response = requests.get(f"{LLAMA_SERVER_URL}/health", timeout=2)
        return (response.status_code == 200)
    except requests.exceptions.RequestException:
        return False
def stream_response(prompt, callback_handler=None, retries=MAX_RETRIES, backoff_factor=BACKOFF_FACTOR, max_tokens=9000):
    url = f"{LLAMA_SERVER_URL}/v1/completions"
    payload = {
        "model": "llama",
        "prompt": prompt,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "top_p": 0.95,
        "top_k": 40,
        "stream": True
    }
    headers = {"Content-Type": "application/json"}
    generated_text = ""
    for attempt in range(1, retries + 1):
        try:
            with requests.post(url, headers=headers, data=json.dumps(payload), stream=True, timeout=60) as response:
                if response.status_code == 200:
                    for line in response.iter_lines(decode_unicode=True):
                        if not line:
                            continue
                        if line.startswith("data:"):
                            data_str = line[5:].strip()
                            if data_str == "[DONE]":
                                return generated_text
                            try:
                                data = json.loads(data_str.encode('latin1').decode('utf-8'))
                                choices = data.get("choices", [])
                                if choices:
                                    content = choices[0].get("text", "")
                                    if content:
                                        if callback_handler:
                                            callback_handler.on_llm_new_token(content)
                                        generated_text += content
                            except json.JSONDecodeError:
                                continue
                    return generated_text
                else:
                    if 500 <= response.status_code < 600:
                        time.sleep(backoff_factor)
                    else:
                        break
        except requests.exceptions.Timeout:
            time.sleep(backoff_factor)
        except requests.exceptions.ConnectionError as e:
            time.sleep(backoff_factor)
        except Exception as e:
            break
    return generated_text
