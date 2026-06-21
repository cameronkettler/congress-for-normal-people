import re

SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"}
TITLES = ("Rep.", "Sen.", "Representative", "Senator")


def display_person_name(value: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""

    prefix = ""
    for title in TITLES:
        if text.casefold().startswith(title.casefold() + " "):
            prefix = title
            text = text[len(title) :].strip()
            break

    bracket = ""
    bracket_match = re.search(r"\s*(\[[^\]]+\])\s*$", text)
    if bracket_match:
        bracket = bracket_match.group(1)
        text = text[: bracket_match.start()].strip()

    if "," in text:
        last, rest = [part.strip() for part in text.split(",", 1)]
        rest_parts = rest.split()
        suffixes = [part for part in rest_parts if part.casefold() in SUFFIXES]
        given = [part for part in rest_parts if part.casefold() not in SUFFIXES]
        pieces = given + [last] + suffixes
        text = " ".join(part for part in pieces if part)

    parts = [part for part in (prefix, text, bracket) if part]
    return " ".join(parts)


def normalized_person_key(value: str) -> str:
    display = display_person_name(value)
    display = re.sub(r"\[[^\]]+\]", " ", display)
    display = re.sub(r"\b(rep|sen|representative|senator)\b\.?", " ", display, flags=re.IGNORECASE)
    display = re.sub(r"[^a-zA-Z\s]", " ", display)
    return " ".join(
        sorted(
            part
            for part in display.casefold().split()
            if part and part not in {suffix.replace(".", "") for suffix in SUFFIXES}
        )
    )
