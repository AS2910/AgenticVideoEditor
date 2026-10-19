"""Folders and Help: the agent's view of the project around its video, and the help articles."""
from dataclasses import replace

from app.agent.context import SYSTEM, opening
from app.agent.tools import BY_NAME, MAX_STRICT, MAX_UNIONS, strict_count, union_count

PROJECT = {
    "project_id": "f1", "name": "Spring sale", "brief": "Price first.",
    "voices": [{"voice_id": "SHARED1", "name": "Priya", "kind": "recorded", "description": "warm", "consent_granted_at": "2026-10-19T16:09:46.615Z"}],
    "videos": [{"filename": "sister.mp4", "duration": 12.0, "state": "shipped",
                "shipped": [{"text": "Get 30% off.", "voice": "Priya's voice"}]},
               {"filename": "draft.mp4", "duration": 8.0, "state": "new", "shipped": []}],
    "files": [{"name": "brief.txt", "text": "Always say the price first. The sale ends Sunday."},
              {"name": "deck.pdf", "text": ""}],
}


def _in_project(world, project=PROJECT, suggested=None):
    def suggest(video_id, addition, why):
        suggested.append((video_id, addition, why))
        return f"s{len(suggested)}"
    return replace(world.wb, project=lambda video_id: project, suggest=suggest if suggested is not None else None)


def test_the_new_tools_are_free_and_plain():
    for name in ("list_project_videos", "read_project_files", "suggest_brief", "search_help"):
        tool = BY_NAME[name]
        assert tool.guard.value == "free" and tool.definition()["strict"] is False
    assert strict_count() <= MAX_STRICT and union_count() <= MAX_UNIONS


def test_list_voices_puts_the_projects_voices_first(world):
    out = BY_NAME["list_voices"].run(_in_project(world), world.turn(), {})
    lines = out.text.splitlines()
    assert lines[1] == "- SHARED1 · Priya · in this project · warm · consent given"
    assert out.step == "Looked through 3 voices"
    # A take may speak in it.
    take = BY_NAME["synthesize_take"].run(_in_project(world), world.turn(), {"text": "Hello.", "voice_id": "SHARED1", "start": 0, "end": 2,
                                                                           "direction": None, "mix": None, "line": None, "item_id": None})
    assert "Priya's voice" in take.text
    assert "in this project" not in BY_NAME["list_voices"].run(world.wb, world.turn(), {}).text


def test_list_project_videos_reads_the_sisters(world):
    out = BY_NAME["list_project_videos"].run(_in_project(world), world.turn(), {})
    assert out.text.splitlines() == [
        "The other videos in Spring sale (read only; this turn changes only its own video):",
        "- sister.mp4 (12.0 s, shipped): shipped “Get 30% off.” in Priya's voice",
        "- draft.mp4 (8.0 s, new): nothing shipped yet"]
    assert out.step == "Read the 2 sister videos"
    assert BY_NAME["list_project_videos"].run(world.wb, world.turn(), {}).text.startswith("This video is in no project")


def test_read_project_files_returns_passages_with_the_file_name(world):
    wb = _in_project(world)
    out = BY_NAME["read_project_files"].run(wb, world.turn(), {"query": "price"})
    assert out.text.splitlines()[1].startswith("- brief.txt · Always say the price first.")
    assert out.step == "Searched the reference files for “price”: 1 found"
    none = BY_NAME["read_project_files"].run(wb, world.turn(), {"query": "zebra"})
    assert none.text.startswith("Nothing in the reference files mentions “zebra”") and "No text could be read from deck.pdf" in none.text
    assert BY_NAME["read_project_files"].run(wb, world.turn(), {"query": ""}).text.startswith("The reference files: brief.txt, deck.pdf.")
    assert BY_NAME["read_project_files"].run(world.wb, world.turn(), {"query": "x"}).text.startswith("This video is in no project")


def test_suggest_brief_records_a_suggestion_and_changes_nothing_else(world):
    suggested = []
    out = BY_NAME["suggest_brief"].run(_in_project(world, suggested=suggested), world.turn(), {"addition": "End on the date.", "why": "Both do."})
    assert suggested == [("p1", "End on the date.", "Both do.")]
    assert "only when the user accepts" in out.text and out.step == "Suggested for the brief: “End on the date.”"
    assert BY_NAME["suggest_brief"].run(world.wb, world.turn(), {"addition": "x", "why": ""}).text.startswith("This video is in no project")
    assert BY_NAME["suggest_brief"].run(_in_project(world, suggested=[]), world.turn(), {"addition": " ", "why": ""}).text == "Say what the brief should add."


def test_search_help_answers_from_the_articles_and_carries_them_on_the_step(world):
    hits = [{"slug": "ship-a-line", "section": "Editing", "title": "Ship a line", "summary": "Add it.", "body": "word " * 300, "tour": "ship"},
            {"slug": "undo", "section": "Editing", "title": "Undo", "summary": "", "body": "Take it out.", "tour": None}]
    wb = replace(world.wb, help_search=lambda q: hits)
    out = BY_NAME["search_help"].run(wb, world.turn(), {"query": "ship"})
    assert out.step == "Looked in Help: Ship a line" and "- ship-a-line · Editing / Ship a line · Add it. · shows the user: ship" in out.text
    assert out.data == {"help": [{"slug": "ship-a-line", "title": "Ship a line", "section": "Editing", "tour": "ship"},
                                 {"slug": "undo", "title": "Undo", "section": "Editing", "tour": None}]}
    assert "…" in out.text   # the body is an excerpt
    empty = BY_NAME["search_help"].run(world.wb, world.turn(), {"query": "teleport"})
    assert empty.text.startswith("Help has no article about “teleport”") and empty.data is None


def test_the_loop_puts_a_steps_data_on_the_narration(world):
    from app.agent.loop import Agent
    from tests.agent.conftest import ScriptedClient, reply, text, use
    wb = replace(world.wb, help_search=lambda q: [{"slug": "a", "section": "S", "title": "T", "summary": "", "body": "b", "tour": None}])
    seen = []
    Agent(ScriptedClient([reply(use("search_help", query="how"), stop="tool_use"), reply(text("From Help, T."))])).run(
        wb, world.turn(), [], "how do I?", on_step=lambda step, cost, tool, data: seen.append((tool, data)))
    assert seen == [("search_help", {"help": [{"slug": "a", "title": "T", "section": "S", "tour": None}]})]


def test_the_opening_view_and_the_prompt_rules():
    head = opening(None, duration=7.5, filename="beach.mp4", speakers=[], lines=0, autonomy="draft",
                   spent_usd=0.0, ceiling_usd=2.0, turn_usd=0.5, project=PROJECT)
    assert head.splitlines()[:5] == [
        "Brief · Spring sale: Price first.", "Shared voices in this project: Priya.",
        "Sister videos in this project: sister.mp4 (12.0 s), draft.mp4 (8.0 s).",
        "Reference files: brief.txt, deck.pdf (read_project_files searches them).",
        "The clip: beach.mp4, 7.5 s, no speech, 0 lines."]
    assert opening(None, duration=7.5, filename="beach.mp4", speakers=[], lines=0, autonomy="draft",
                   spent_usd=0.0, ceiling_usd=2.0, turn_usd=0.5).startswith("The clip:")
    assert "A turn changes only its own video" in SYSTEM and "never edit, ship or" in SYSTEM
    assert "call search_help, answer from what it returns and name the article you used" in SYSTEM.replace("\n", " ")
    assert "Never guess at a feature" in SYSTEM and "under the usual gate" in SYSTEM
