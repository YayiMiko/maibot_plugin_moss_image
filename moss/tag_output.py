"""Minimal visual-tag output validation for image reverse prompting only."""

import re


def clean_tag_output(text: str, *, exclude: tuple[str, ...] = ()) -> str:
    """Normalize format without interpreting commas inside quotes or weights.

    Args:
        text: A successful model completion intended to contain image tags.
        exclude: Exact prefix-owned terms omitted from generated content only.

    Returns:
        Comma-separated tags in their original order, without exact duplicates.

    Raises:
        ValueError: The completion is empty, structured JSON or non-tag prose.
    """
    text = text.strip()
    fence = re.fullmatch(r"```(?:text|tags)?\s*\n(.*?)\n```", text, re.S | re.I)
    if fence:
        text = fence[1].strip()
    text = re.sub(r"(?i)^(?:positive prompt|tags)\s*:\s*", "", text)
    if (
        not text
        or text.startswith(("{", "["))
        or "```" in text
        or "\x00" in text
        or not re.search(r"[a-zA-Z]", text)
    ):
        raise ValueError("Expected visual tags, not JSON or an empty completion")
    parts, current, depth, quote, escaped = [], [], 0, "", False
    for character in text:
        if quote:
            current.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
        elif character in {'"', "“", "「", "『"}:
            quote = {'"': '"', "“": "”", "「": "」", "『": "』"}[character]
            current.append(character)
        elif character in "([{":
            depth += 1
            current.append(character)
        elif character in ")]}":
            depth -= 1
            if depth < 0:
                raise ValueError("Unbalanced tag syntax")
            current.append(character)
        elif character in ",，\n\r" and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(character)
    if quote or depth:
        raise ValueError("Unbalanced tag syntax")
    parts.append("".join(current).strip())
    seen = {term.strip().casefold() for term in exclude if term.strip()}
    unique = []
    for part in parts:
        if part and part.casefold() not in seen:
            unique.append(part)
            seen.add(part.casefold())
    if not unique or (len(unique) == 1 and re.search(r"[.!?]\s*$", unique[0])):
        raise ValueError("Expected tags rather than a prose sentence")
    return ", ".join(unique)
