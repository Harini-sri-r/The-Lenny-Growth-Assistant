"""Fast, local session-title generation that never adds model latency."""
import re


PLACEHOLDER_TITLES = {"new chat", "new conversation", "untitled", "session 1"}
_GREETINGS = {
    "hi", "hello", "hey", "hiya", "good morning", "good afternoon", "good evening",
    "hi there", "hello there", "hey there", "thanks", "thank you", "ok", "okay", "got it",
}
_STOP_WORDS = {
    "a", "an", "and", "are", "can", "could", "for", "how", "i", "in", "is", "it",
    "me", "my", "of", "on", "please", "should", "the", "to", "we", "what", "with",
    "would", "you", "your",
}
_GERUNDS = {
    "build": "Building", "create": "Creating", "design": "Designing", "find": "Finding",
    "grow": "Growing", "improve": "Improving", "increase": "Increasing", "launch": "Launching",
    "measure": "Measuring", "reduce": "Reducing", "start": "Starting", "understand": "Understanding",
    "validate": "Validating", "write": "Writing", "draft": "Drafting",
}


def is_default_session_title(title: str) -> bool:
    return title.strip().casefold() in PLACEHOLDER_TITLES


def _safe_message(message: str) -> str:
    value = re.sub(r"```.*?```|`[^`]*`", " ", message, flags=re.DOTALL)
    value = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", value)
    value = re.sub(r"(?i)\bemail\s*[:=]?\s*[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|https?://\S+|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", " ", value)
    value = re.sub(r"(?i)\b(?:phone|mobile)\s*[:=]?\s*\+?\d[\d ()-]{7,}\d|(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)", " ", value)
    value = re.sub(r"(?i)\b(?:password|passcode|api[_ -]?key|access[_ -]?token|secret|ssn|credit card)\s*(?:is|:|=)?\s*[^\s,;]+", " ", value)
    value = re.sub(r"[\"“”‘’]", " ", value)
    value = re.sub(r"[#*_>`]", " ", value)
    return re.sub(r"\s+", " ", value).strip(" .?!,:;-")


def _title_case(value: str) -> str:
    words = value.split()
    small = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"}
    def cap_word(word: str, is_first: bool) -> str:
        parts = word.split("-")
        return "-".join(part if not is_first and part.casefold() in small else part[:1].upper() + part[1:] for part in parts)
    return " ".join(cap_word(word, index == 0) for index, word in enumerate(words))


def _fit_title(value: str) -> str:
    words = value.split()[:7]
    title = " ".join(words)
    if len(title) > 50:
        title = title[:50].rsplit(" ", 1)[0]
    return title.rstrip(" .,:;-?!")


def _action_title(action: str, topic: str) -> str:
    verb = _GERUNDS.get(action.casefold(), "Understanding")
    topic = re.sub(r"^(?:my|our|the)\s+", "", topic, flags=re.IGNORECASE)
    topic = re.sub(r"\b(?:please|for me|with examples?)\b", " ", topic, flags=re.IGNORECASE)
    topic = re.sub(r"\s+", " ", topic).strip(" .?!,:;-")
    if action.casefold() == "validate" and re.match(r"(?i)startup idea\b", topic):
        topic = "a " + topic
    return _fit_title(_title_case(f"{verb} {topic}"))


def generate_session_title(message: str) -> str | None:
    """Return a concise title for a meaningful first user message, or None for greetings."""
    source = _safe_message(message)
    if not source or source.casefold() in _GREETINGS:
        return None
    source = re.sub(r"^(?:hi|hello|hey|hiya|thanks|thank you|okay|ok)(?: there)?[,.! ]+", "", source, flags=re.IGNORECASE).strip()
    if not source:
        return None
    source = re.sub(r"\s+", " ", source).strip()
    lower = source.casefold()

    match = re.match(r"what did lenny say about\s+(.+)", source, re.IGNORECASE)
    if match:
        return _fit_title(_title_case(f"Lenny’s Lessons on {match.group(1)}"))

    match = re.match(r"help me (?:write|draft|create)\s+(.+)", source, re.IGNORECASE)
    if match:
        target = re.sub(r"(?i)^(?:an?\s+)?ship\s*30\s+", "", match.group(1)).strip()
        essay = re.match(r"(?i)^(?:an?\s+)?essay\s+(?:about|on)\s+(.+)", target)
        if essay:
            return _fit_title(_title_case(f"Writing an Essay on {essay.group(1)}"))
        return _action_title("write", target)

    match = re.match(r"(?:what are )?(?:the )?(?:best ways|ways) to\s+([a-z]+)\s+(.+)", source, re.IGNORECASE)
    if match:
        return _action_title(match.group(1), match.group(2))

    match = re.match(r"how (?:can|do|should) (?:i|we|you)\s+([a-z]+)\s+(.+)", source, re.IGNORECASE)
    if match:
        return _action_title(match.group(1), match.group(2))

    match = re.match(r"how to\s+([a-z]+)\s+(.+)", source, re.IGNORECASE)
    if match:
        return _action_title(match.group(1), match.group(2))

    match = re.match(r"explain\s+(.+)", source, re.IGNORECASE)
    if match:
        topic = re.sub(r"(?i)\s+with examples?\b", "", match.group(1)).strip()
        topic = re.sub(r"(?i)\s+and\s+(?:many|several|lots of|more|additional)\b.*$", "", topic).strip()
        return _fit_title(_title_case(f"Understanding {topic}"))

    for prefix in ("what are ", "what is ", "why do ", "why does ", "tell me about ", "ask about ", "discuss "):
        if lower.startswith(prefix):
            source = source[len(prefix):]
            break

    words = [word for word in re.findall(r"[\w'-]+", source) if word.casefold() not in _STOP_WORDS]
    if not words:
        return None
    topic = " ".join(words[:5])
    # Avoid preserving numeric identifiers even if formatted unusually.
    topic = re.sub(r"\b\w*\d\w*\b", "", topic).strip()
    return _fit_title(_title_case(topic)) if topic else None
