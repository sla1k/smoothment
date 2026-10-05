from smoothment.config import OwnerSettings


def _tokens(text: str) -> set[str]:
    tokens = []
    current = ""
    for char in text:
        if char.isalnum():
            current += char
        elif current:
            tokens.append(current)
            current = ""
    if current:
        tokens.append(current)
    return {token.casefold() for token in tokens}


class OwnerMatcher:
    """Decides whether a name or phone on a statement belongs to the account owner."""

    def __init__(self, settings: OwnerSettings) -> None:
        self._name_tokens = [_tokens(name) for name in settings.names]
        self._phones = settings.phones

    def is_owner(self, text: str | None) -> bool:
        if not text:
            return False
        text_tokens = _tokens(text)
        if not text_tokens:
            return False
        return any(name_tokens and name_tokens <= text_tokens for name_tokens in self._name_tokens)

    def mentions_phone(self, text: str | None) -> bool:
        if not text:
            return False
        digits = "".join(char for char in text if char.isdigit())
        return any(phone in digits for phone in self._phones)
