"""Chat orchestration: history + system prompt + streaming model client."""

import threading
from typing import Iterator, Optional, Protocol

from ..storage.history import HistoryStore

DEFAULT_SYSTEM_PROMPT = (
    "You are Zana, a concise, friendly voice assistant running locally on the "
    "user's Windows PC. Keep answers short and conversational unless asked for detail. "
    "You cannot open or launch apps, websites or files yourself; that is handled separately, "
    "so never say you are opening or starting something."
)


SPOKEN_HINT = (
    " The reply will be read aloud: answer in at most two short sentences, "
    "plain text only, no lists, markdown or emoji."
)


class ChatClient(Protocol):
    def stream_chat(
        self, messages: list[dict], cancel: Optional[threading.Event] = None
    ) -> Iterator[str]: ...


class Assistant:
    def __init__(
        self,
        client: ChatClient,
        store: HistoryStore,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        history_limit: int = 20,
    ):
        self.client = client
        self.store = store
        self.system_prompt = system_prompt
        self.history_limit = history_limit
        self.conversation_id: Optional[int] = None

    def new_conversation(self) -> None:
        self.conversation_id = None

    def record_exchange(self, user_text: str, reply: str) -> None:
        """Save a turn that was answered without the model (e.g. opening an app)."""
        if self.conversation_id is None:
            title = user_text.strip().replace("\n", " ")[:48] or "New chat"
            self.conversation_id = self.store.create_conversation(title)
        self.store.add_message(self.conversation_id, "user", user_text)
        self.store.add_message(self.conversation_id, "assistant", reply)

    def reply_stream(
        self, user_text: str, cancel: Optional[threading.Event] = None, spoken: bool = False
    ) -> Iterator[str]:
        """Save the user message, stream the reply, save it once complete.

        A reply that errors or is cancelled is not saved, so history never
        contains half-finished assistant turns.
        """
        if self.conversation_id is None:
            title = user_text.strip().replace("\n", " ")[:48] or "New chat"
            self.conversation_id = self.store.create_conversation(title)
        cid = self.conversation_id
        self.store.add_message(cid, "user", user_text)

        history = self.store.get_messages(cid, limit=self.history_limit)
        system = self.system_prompt + (SPOKEN_HINT if spoken else "")
        messages = [{"role": "system", "content": system}] + [
            {"role": m["role"], "content": m["content"]} for m in history
        ]

        parts: list[str] = []
        for chunk in self.client.stream_chat(messages, cancel):
            parts.append(chunk)
            yield chunk
        if cancel is not None and cancel.is_set():
            return
        reply = "".join(parts).strip()
        if reply:
            self.store.add_message(cid, "assistant", reply)
