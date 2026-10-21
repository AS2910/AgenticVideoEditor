"""Launch item 2: every route checks the caller owns what it names.

Sign-in is on. Ann makes one of everything she cheaply can (a video, a
project with the video in it, a rule, a preset, a share link, a template, a
voice, a review link, a binned video, a data export). Then Bo, signed in
with every flag Ann has, calls every route with Ann's ids. Each call must
answer 404, exactly as if the thing did not exist: no 200, no 403 that
admits it is there, and nothing changed.

The test is parametrised over the app's own route table, so a route added
later without an ownership check fails here until it has one, or until it
is listed in PUBLIC with the reason it is open by design.
"""
from __future__ import annotations

import re
from dataclasses import replace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import app.api.main as main
from app import auth
from app.api.main import app, flags, jobs, repo
from app.flags import KNOWN

H = {"X-Requested-With": "voltage"}
ANN, BO = "google:ann", "google:bo"

# Routes that are open by design, each with why. Keys are "METHOD path".
PUBLIC = {
    # Capability links: holding the token is the permission (signed, revocable, expiring).
    "GET /share/{token}": "a share link is its own permission",
    "GET /share/{token}/files/{file_id}": "a share link is its own permission",
    "POST /share/{token}/comments": "a review link is its own permission",
    "POST /share/{token}/approve": "a review link is its own permission",
    "POST /share/{token}/changes": "a review link is its own permission",
    "GET /share/{token}/zip": "a share link is its own permission",
    "GET /invites/{token}": "an invite link is its own permission",
    "POST /invites/{token}/accept": "an invite link is its own permission",
    "GET /media/{token}/{name}": "a signed media URL is its own permission",
}


def _all_routes() -> list[APIRoute]:
    found = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            found.append(route)
        elif hasattr(route, "original_router"):
            found.extend(r for r in route.original_router.routes if isinstance(r, APIRoute))
    return found


def _cases():
    seen = set()
    for route in _all_routes():
        if route.deprecated or "{" not in route.path:
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            key = f"{method} {route.path}"
            if key in seen or key in PUBLIC:
                continue
            seen.add(key)
            yield pytest.param(method, route, id=key)


def _client(sub: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set(auth.SESSION_COOKIE, auth.sign(
        {"sub": sub, "email": f"{sub}@example.com", "name": sub, "picture": None}, "s3cret"))
    return client


@pytest.fixture(scope="module")
def world(tmp_path_factory, sample_video):
    """Ann's things, made once for the module (the routes Bo calls never change them)."""
    mp = pytest.MonkeyPatch()
    mp.setattr(main, "settings", replace(main.settings, auth_mode="google", session_secret="s3cret"))
    repo.reset()
    jobs.reset()
    for who in (ANN, BO):
        for flag in KNOWN:
            if not flag.startswith("launch."):
                flags.set(flag, who, True)
    ann = _client("ann")
    ids: dict[str, str] = {}

    def made(resp, *keys):
        assert resp.status_code in (200, 201), resp.text
        body = resp.json()
        for key in keys:
            body = body[key]
        return body

    with open(sample_video, "rb") as handle:
        video = made(ann.post("/videos", files={"file": ("ad.mp4", handle, "video/mp4")},
                              data={"consent": "true"}, headers=H))
    ids["video"] = video["video_id"] if "video_id" in video else video["project_id"]
    with open(sample_video, "rb") as handle:
        spare = made(ann.post("/videos", files={"file": ("b.mp4", handle, "video/mp4")},
                              data={"consent": "true"}, headers=H))
    ids["spare"] = spare.get("video_id") or spare["project_id"]
    ids["folder"] = made(ann.post("/projects", json={"name": "Ann's"}, headers=H), "project_id")
    made(ann.patch(f"/videos/{ids['video']}", json={"project_id": ids["folder"]}, headers=H))
    rule = ann.post(f"/projects/{ids['folder']}/rules", json={"kind": "banned", "data": {"word": "cheap"}}, headers=H)
    if rule.status_code in (200, 201):
        ids["rule"] = str(rule.json()["rule_id"])
    share = ann.post(f"/projects/{ids['folder']}/shares", json={"scope": "project", "days": 7}, headers=H)
    if share.status_code in (200, 201):
        body = share.json()
        ids["share"] = str(body.get("share_id") or body.get("id") or body.get("share", {}).get("id"))
    template = ann.post(f"/projects/{ids['folder']}/template", json={"name": "T"}, headers=H)
    if template.status_code in (200, 201):
        body = template.json()
        ids["template"] = str(body.get("template_id") or body.get("id") or body.get("template", {}).get("id"))
    ann.delete(f"/videos/{ids['spare']}", headers=H)
    export = ann.post("/me/data-export", headers=H)
    if export.status_code in (200, 201, 202):
        ids["data_job"] = export.json()["request"]["job_id"]
    ids["job"] = next((j.job_id for j in jobs.all() if j.project_id == ids["video"]), "") or ids.get("data_job", "")
    assert {"rule", "share", "template", "data_job", "job"} <= {k for k, v in ids.items() if v}, ids
    yield ids
    mp.undo()
    for who in (ANN, BO):
        for flag in KNOWN:
            flags.clear(flag, who)


def _fill(path: str, ids: dict[str, str], route: APIRoute | None = None) -> str:
    ints = {p.alias for p in (route.dependant.path_params if route else []) if p.field_info.annotation is int}
    video_paths = path.startswith(("/videos/", "/projects/{project_id}/batches/{batch_id}/videos/"))
    values = {
        "project_id": ids["video"] if path.startswith("/videos/") else ids["folder"],
        "video_id": ids["video"],
        "rule_id": ids.get("rule", "1"),
        "share_id": ids.get("share", "1"),
        "template_id": ids.get("template", "t1"),
        "job_id": ids.get("data_job") if path.startswith("/me/data-export") else (ids.get("job") or "j1"),
        "item_id": ids["spare"] if path.startswith("/bin/") or path.startswith("/pins/") else "i1",
        "kind": "video" if path.startswith(("/bin/", "/pins/")) else "x",
        "index": "0", "sha256": "0" * 64, "label": "A", "member": ANN, "invite_id": "1",
        "invoice_id": "1", "mark": "m", "attempt_id": "a1",
    }
    del video_paths

    def sub(match: re.Match) -> str:
        name = match.group(1)
        if name in ints:
            return "1"
        return str(values.get(name) or "x1")
    return re.sub(r"{(\w+)(?::\w+)?}", sub, path)


def _example(schema: dict, defs: dict):
    if "$ref" in schema:
        return _example(defs[schema["$ref"].split("/")[-1]], defs)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [s for s in schema[key] if s.get("type") != "null"]
            return _example(options[0], defs) if options else None
    if "enum" in schema:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    if "default" in schema:
        return schema["default"]
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        props = schema.get("properties", {})
        return {k: _example(props[k], defs) for k in schema.get("required", [])}
    return {"string": "x", "integer": 1, "number": 1.0, "boolean": True, "array": []}.get(kind, "x")


def _params(route: APIRoute, ids: dict[str, str]) -> dict:
    """Required query parameters, with Ann's ids where they name a video or project."""
    out = {}
    for p in route.dependant.query_params:
        if not p.field_info.is_required():
            continue
        if p.alias in ("video", "video_id"):
            out[p.alias] = ids["video"]
        elif p.alias in ("project", "project_id"):
            out[p.alias] = ids["folder"]
        else:
            from pydantic import TypeAdapter
            schema = TypeAdapter(p.field_info.annotation).json_schema()
            out[p.alias] = _example(schema, schema.get("$defs", {}))
    return out


def _request_kwargs(route: APIRoute) -> dict:
    files = [p for p in route.dependant.body_params if "UploadFile" in repr(p.field_info.annotation) or
             getattr(p.field_info, "media_type", "") == "multipart/form-data" and "File" in type(p.field_info).__name__]
    if files:
        return {"files": {p.alias: ("a.wav", b"RIFF0000WAVE", "audio/wav") for p in files},
                "data": {p.alias: "x" for p in route.dependant.body_params if p not in files}}
    if route.body_field is None:
        return {}
    from pydantic import TypeAdapter
    schema = TypeAdapter(route.body_field.field_info.annotation).json_schema()
    body = _example(schema, schema.get("$defs", {}))
    if len(route.dependant.body_params) == 1 and not route.dependant.body_params[0].field_info.embed:
        return {"json": body}
    return {"json": {route.dependant.body_params[0].alias: body}} if len(route.dependant.body_params) == 1 else {"json": body}


@pytest.mark.parametrize("method,route", list(_cases()))
def test_a_second_user_gets_404(world, method, route):
    bo = _client("bo")
    path = _fill(route.path, world, route)
    # Bo's own signed media token rides along, so media routes judge ownership, not the missing token.
    params = {**_params(route, world), "mt": main.mint_media_token(BO)["token"]}
    resp = bo.request(method, path, headers=H, params=params, **_request_kwargs(route))
    assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}: {resp.text[:300]}"


def test_every_public_route_is_still_a_route():
    keys = {f"{m} {r.path}" for r in _all_routes() for m in r.methods}
    assert set(PUBLIC) - keys <= {"GET /media/{token}/{name}"}


def test_ids_in_the_query_or_body_are_checked_too(world):
    bo = _client("bo")
    assert bo.get(f"/spend?video={world['video']}").status_code == 404
    assert bo.get(f"/spend?project={world['folder']}").status_code == 404
    mine = bo.post("/projects", json={"name": "Bo's"}, headers=H).json()["project_id"]
    # A batch only ever takes the project's own live videos (Ann's is filtered out, never planned).
    assert bo.post(f"/projects/{mine}/batches", json={"goal": "x", "video_ids": [world["video"]]}, headers=H).status_code >= 400
    assert bo.post("/voices/mine/from-speaker", json={"video_id": world["video"], "label": "A", "name": "x", "consent": True},
                   headers=H).status_code == 404
    assert bo.post("/voices/mine/keep", json={"voice_id": "v", "video_id": world["video"], "name": "x"},
                   headers=H).status_code in (404, 422)
    assert repo.get(world["video"]).owner == ANN
