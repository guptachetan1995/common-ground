from __future__ import annotations


class Refusal(Exception):
    """A named refusal. `code` is the outcome name; `detail` is text this app wrote, never text from Qloo."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail
