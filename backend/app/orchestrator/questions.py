"""Questions the editor asks instead of refusing an edit (Phase 8).

A person cannot drag a selection to the exact length of a line that has not
been spoken yet, and on a clip without speech there is no telling whether a
new line should replace the sound there or sit on top of it. Each function
returns the options that apply, as the job result the chat renders.
"""
from __future__ import annotations

from app.media.ffmpeg import MAX_TEMPO, MIN_TEMPO
from app.orchestrator.intent import EditContext

MIX_LABELS = {
    "replace": "Replace the sound in the selection",
    "layer": "Layer the line over the original sound",
    "concatenate": "Add it after the selection — the video holds its last frame while the line plays",
}


def _question(text: str, question: str, mix: str | None, options: list[dict]) -> dict:
    return {"type": "question", "question": question, "text": text, "mix": mix, "options": options}


def mix_question(text: str, context: EditContext) -> dict:
    return _question(
        text,
        "There's no speech in that selection. How should the new line meet the sound that's there?",
        None,
        [{"label": label, "mix": mix, "fit": None, "warning": None} for mix, label in MIX_LABELS.items()],
    )


def _tempo_warning(tempo: float) -> str | None:
    if tempo < MIN_TEMPO:
        return "That's well outside natural speech — it will sound dragged."
    if tempo > MAX_TEMPO:
        return "That's well outside natural speech — it will sound rushed."
    return None


def fit_question(
    text: str, mix: str, natural: float, target: float, start: float, duration: float,
) -> dict:
    tempo = natural / target
    options = []
    if natural < target:
        rest = target - natural
        after = ("the original sound carries on" if mix == "layer"
                 else f"{rest:.2f}s of silence")
        question = (f"The line is {natural:.2f}s but the selection is {target:.2f}s. "
                    "How should it fill the selection?")
        options.append({
            "label": f"Start at the selection's start: the {natural:.2f}s line, then {after}",
            "fit": "start", "mix": None, "warning": None,
        })
        options.append({
            "label": f"Slow it down to fill the {target:.2f}s selection ({tempo:.2f}× speed)",
            "fit": "stretch", "mix": None, "warning": _tempo_warning(tempo),
        })
    else:
        question = (f"The line is {natural:.2f}s but the selection is only {target:.2f}s. "
                    "How should it fit?")
        options.append({
            "label": f"Speed it up to fit the {target:.2f}s selection ({tempo:.2f}× speed)",
            "fit": "stretch", "mix": None, "warning": _tempo_warning(tempo),
        })
        if start + natural <= duration:
            options.append({
                "label": f"Let it run {natural - target:.2f}s past the end of the selection",
                "fit": "start", "mix": None, "warning": None,
            })
    return _question(text, question, mix, options)
