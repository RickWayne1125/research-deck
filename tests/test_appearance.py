"""Settings → Appearance (appearance.py): the Radix theme and the background, kept in settings.json, and the uploaded
background picture in the machine-local backgrounds/ folder."""
from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient

from research_deck import appearance, config
from research_deck.app import create_app

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 32
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def as_human(client):
    assert client.get("/api/session").status_code == 200


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_defaults_are_radix_red(client):
    s = client.get("/api/settings/appearance").json()
    assert s == {"theme": "radix-red", "custom": {"accent": "red", "radius": "large", "background": "ribbons"},
                 "blur": 40, "image": None}


def test_update_validates_and_keeps_the_rest_of_settings_json(client):
    as_human(client)
    r = client.patch("/api/settings/appearance", json={"theme": "custom", "custom": {"accent": "indigo", "radius": "full"},
                                                       "blur": 70})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["theme"] == "custom" and s["custom"] == {"accent": "indigo", "radius": "full", "background": "ribbons"}
    assert s["blur"] == 70
    on_disk = json.loads(config.SETTINGS_FILE.read_text())
    assert on_disk["dag_defaults"] == {"stages": {"mode": "free"}}            # the other keys stay as they were
    assert on_disk["appearance"]["custom"] == {"accent": "indigo", "radius": "full"}
    for bad in ({"theme": "neon"}, {"custom": {"accent": "chartreuse"}}, {"custom": {"radius": 3}},
                {"custom": {"background": "video"}}, {"blur": 101}, {"blur": True}, {"custom": "red"}):
        assert client.patch("/api/settings/appearance", json=bad).status_code == 400, bad
    # null puts a key back to its default
    s = client.patch("/api/settings/appearance", json={"custom": {"accent": None}, "blur": None}).json()
    assert s["custom"]["accent"] == "red" and s["custom"]["radius"] == "full" and s["blur"] == 40
    assert client.patch("/api/settings/appearance", json={"theme": None, "custom": None}).json()["theme"] == "radix-red"


def test_the_radix_art_in_a_custom_accent(client):
    as_human(client)
    s = client.patch("/api/settings/appearance", json={"theme": "custom", "custom": {"accent": "jade", "background": "radix"}}).json()
    assert s["custom"]["background"] == "radix"


def test_picture_upload_replace_serve_and_remove(client):
    as_human(client)
    # a picture background needs a picture first
    assert client.patch("/api/settings/appearance", json={"custom": {"background": "image"}}).status_code == 400
    r = client.put("/api/settings/appearance/image", json={"name": "bg.png", "content_base64": b64(PNG)})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["theme"] == "custom" and s["custom"]["background"] == "image"
    assert s["image"].startswith("/api/settings/appearance/image?v=")
    files = list(appearance.backgrounds_dir().iterdir())
    assert [f.suffix for f in files] == [".png"]
    got = client.get(s["image"])
    assert got.status_code == 200 and got.content == PNG
    assert got.headers["content-type"] == "image/png" and got.headers["x-content-type-options"] == "nosniff"
    assert "immutable" in got.headers["cache-control"] and got.headers["content-security-policy"] == "sandbox"
    assert "no-cache" in client.get("/api/settings/appearance/image").headers["cache-control"]   # no version: revalidate

    # another picture replaces it (the type comes from its bytes, not its name)
    s2 = client.put("/api/settings/appearance/image", json={"name": "photo.png", "content_base64": b64(JPEG)}).json()
    assert s2["image"] != s["image"]
    assert [f.suffix for f in appearance.backgrounds_dir().iterdir()] == [".jpg"]
    assert client.get(s2["image"]).headers["content-type"] == "image/jpeg"
    assert client.put("/api/settings/appearance/image", json={"name": "a.webp", "content_base64": b64(WEBP)}).status_code == 200

    # removing it falls back to the ribbons
    s3 = client.delete("/api/settings/appearance/image").json()
    assert s3["image"] is None and s3["custom"]["background"] == "ribbons"
    assert list(appearance.backgrounds_dir().iterdir()) == []
    assert client.get("/api/settings/appearance/image").status_code == 404


def test_pictures_are_checked(client):
    as_human(client)
    for data, name in ((SVG, "x.svg"), (b"just text", "x.png"), (b"", "x.png")):
        r = client.put("/api/settings/appearance/image", json={"name": name, "content_base64": b64(data)})
        assert r.status_code == 400, name
    assert client.put("/api/settings/appearance/image", json={"name": "x.png", "content_base64": "not base64!"}).status_code == 400
    big = "A" * (appearance.MAX_IMAGE * 4 // 3 + 64)
    assert client.put("/api/settings/appearance/image", json={"name": "x.png", "content_base64": big}).status_code == 413
    assert not appearance.backgrounds_dir().exists() or list(appearance.backgrounds_dir().iterdir()) == []


def test_a_missing_picture_file_is_no_picture(client):
    as_human(client)
    client.put("/api/settings/appearance/image", json={"name": "bg.png", "content_base64": b64(PNG)})
    for f in appearance.backgrounds_dir().iterdir():
        f.unlink()
    s = client.get("/api/settings/appearance").json()
    assert s["image"] is None and s["custom"]["background"] == "ribbons"


def test_settings_json_cannot_point_outside_backgrounds(client):
    config.SETTINGS_FILE.write_text(json.dumps({"appearance": {"image": "../settings.json", "theme": "custom",
                                                               "custom": {"background": "image"}}}))
    config._SETTINGS_CACHE = (-1.0, {})
    assert client.get("/api/settings/appearance").json()["image"] is None
    assert client.get("/api/settings/appearance/image").status_code == 404


def test_only_the_researcher_changes_the_appearance(client):
    with TestClient(create_app(), headers={"X-RD-Request": "1"}) as agent:
        assert agent.get("/api/settings/appearance").status_code == 200
        assert agent.patch("/api/settings/appearance", json={"theme": "custom"}).status_code == 403
        assert agent.put("/api/settings/appearance/image", json={"name": "a.png", "content_base64": b64(PNG)}).status_code == 403
        assert agent.delete("/api/settings/appearance/image").status_code == 403
