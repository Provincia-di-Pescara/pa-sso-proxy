from app import version


def test_display_version_from_baked_file(tmp_path, monkeypatch):
    f = tmp_path / "app_version.txt"
    f.write_text("v0.9.16\n")
    monkeypatch.setattr(version, "VERSION_FILE", str(f))
    assert version.get_display_version() == "v0.9.16"


def test_release_version_from_baked_file(tmp_path, monkeypatch):
    f = tmp_path / "app_release.txt"
    f.write_text("v0.9.16-4-gabc1234+20261026\n")
    monkeypatch.setattr(version, "RELEASE_FILE", str(f))
    assert version.get_release_version() == "v0.9.16-4-gabc1234+20261026"


def test_release_version_falls_back_to_display_version(tmp_path, monkeypatch):
    # Immagini precedenti hanno solo app_version.txt.
    display = tmp_path / "app_version.txt"
    display.write_text("v0.9.16")
    monkeypatch.setattr(version, "VERSION_FILE", str(display))
    monkeypatch.setattr(version, "RELEASE_FILE", str(tmp_path / "missing.txt"))
    assert version.get_release_version() == "v0.9.16"
