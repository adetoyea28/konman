import re


_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)(\b(?:api[_-]?key|access[_-]?token|secret[_-]?key|client[_-]?secret|password)\b\s*[:=]\s*['\"]?)[^\s,;\"']+"),
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)
_SECRET_FIELD = re.compile(r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|credential)")


def redact_text(text: str, custom_patterns=()) -> tuple[str, int]:
    count = 0
    patterns = [*_PATTERNS, *(re.compile(pattern) for pattern in custom_patterns)]
    for pattern in patterns:
        text, matches = pattern.subn(lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]", text)
        count += matches
    return text, count


def redact_value(value, custom_patterns=()) -> tuple[object, int]:
    if isinstance(value, dict):
        result = {}
        count = 0
        for key, item in value.items():
            if _SECRET_FIELD.search(str(key)) and item not in (None, ""):
                result[key] = "[REDACTED]"
                count += 1
            else:
                result[key], item_count = redact_value(item, custom_patterns)
                count += item_count
        return result, count
    if isinstance(value, list):
        result = []
        count = 0
        for item in value:
            redacted, item_count = redact_value(item, custom_patterns)
            result.append(redacted)
            count += item_count
        return result, count
    if isinstance(value, str):
        return redact_text(value, custom_patterns)
    return value, 0