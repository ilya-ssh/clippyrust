import logging
import re
import threading
FENCE = re.compile(r"```") 
LANG_RE = re.compile(r"[a-zA-Z0-9_-]+\n")#кодтэг

class StreamingCallbackHandler:
    def __init__(self, ide_instance):
        self.ide = ide_instance

    def on_llm_new_token(self, token: str):
        logging.debug(f"Tok: {token}")
        self.ide.token_queue.put(token)
        self.ide.chat_autoscroll = True
class StreamingEditHandler:
    def __init__(self, ide):
        self.ide   = ide
        self.first = True          
        self.tail  = ""    
        self.lock  = threading.Lock()

    def on_llm_new_token(self, token: str):
        logging.debug("TOK %s", repr(token))

        with self.lock:
            if self.first:
                self.ide.push_undo_state()
                self.ide.code_content = []      
                self.first = False
            chunk = self.tail + token
            lines = chunk.split("\n")
            if lines[:-1]:
                self.ide.code_content.extend(lines[:-1])
            #last element is possibly incomplete!!!!!!
            self.tail = lines[-1]
            if not self.ide.code_content:
                self.ide.code_content.append("")
            #the last line with current tail
            self.ide.code_content[-1] = self.tail
            #mov
            self.ide.cursor_y = len(self.ide.code_content) - 1
            self.ide.cursor_x = len(self.tail)
            self.ide.adjust_view()

    def on_llm_end(self):
        self._postprocess()
        self.ide.enqueue_run_output("[green]Edit complete.[/green]")

    def _postprocess(self):
        lines = self.ide.code_content
        if lines and lines[0].strip().lower() == "rust":
            lines.pop(0)
        while lines and lines[-1].strip().startswith("```"):
            lines.pop()
        if not lines:
            lines = [""]
        self.ide.code_content = lines
        self.ide.cursor_y = len(lines) - 1
        self.ide.cursor_x = len(lines[-1])
