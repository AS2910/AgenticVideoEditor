import re
from app.domain.models import Selection, EditPlan

# Matches the trailing '... to "NEW TEXT"' part of a change instruction.
_REPLACEMENT_RE = re.compile(r'to\s+"([^"]+)"\s*$', re.IGNORECASE)


def extract_new_text(prompt: str) -> str:
    """Pull the intended new spoken text out of a natural-language prompt.

    Recognises the common 'change "X" to "Y"' shape; otherwise treats the whole
    prompt as the literal new text. Real intent parsing replaces this later.
    """
    match = _REPLACEMENT_RE.search(prompt.strip())
    if match:
        return match.group(1)
    return prompt.strip()


def build_edit_plan(prompt: str, selection: Selection, voice_profile_id: str) -> EditPlan:
    return EditPlan(
        selection=selection,
        new_text=extract_new_text(prompt),
        voice_profile_id=voice_profile_id,
    )
