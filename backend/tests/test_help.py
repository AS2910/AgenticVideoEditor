"""The help articles: one folder of Markdown, read by the Help page and by Voltage's search_help."""
from fastapi.testclient import TestClient

from app import help as help_
from app.api.main import app


def test_every_article_has_its_front_matter_and_a_section():
    arts = help_.articles()
    assert len(arts) >= 39
    sections = {a.section for a in arts}
    assert {"Getting started", "Directing Voltage", "Editing lines", "Voices", "Listening and quality", "Fitting a line",
            "Exporting", "Money and limits", "Account and privacy", "Troubleshooting"} <= sections
    for a in arts:
        assert a.slug and a.title and a.summary and a.body, a.slug
        assert a.order > 0
    # Slugs are unique: the Help page and the tool address an article by slug.
    assert len({a.slug for a in arts}) == len(arts)


def test_search_finds_the_article_by_its_words_and_names_the_tour():
    hits = help_.search("how do I keep a voice for other projects")
    assert hits and hits[0]["title"] in ("Saving and reusing your voices", "Check with me or Just do it")
    assert any(h["slug"] == "saving-and-reusing-your-voices" and h["tour"] == "save-voice" for h in hits)
    assert [h["title"] for h in help_.search("keyboard shortcuts")][0] == "Keyboard shortcuts"
    assert help_.search("") == []
    assert help_.search("xyzzy qwfp") == []


def test_the_articles_route_lists_them_and_search_answers():
    client = TestClient(app)
    r = client.get("/help")
    assert r.status_code == 200
    body = r.json()["articles"]
    assert body[0]["slug"] == "what-voltage-does"
    assert {"slug", "section", "title", "summary", "body", "order", "tour"} <= set(body[0])
    found = client.get("/help/search", params={"q": "a line won't fit"}).json()["articles"]
    assert found and found[0]["slug"] in ("a-line-wont-fit", "why-a-line-runs-long")
