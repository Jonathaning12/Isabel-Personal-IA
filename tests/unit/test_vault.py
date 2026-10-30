"""Unit tests for the Obsidian vault: path safety, reading, searching and writing."""

import pytest

from assistant.vault.notes import Vault, VaultError


@pytest.fixture
def vault(tmp_path):
    root = tmp_path / "vault"
    (root / "Proyectos").mkdir(parents=True)
    (root / ".obsidian").mkdir()
    (root / "Proyectos" / "atlas.md").write_text(
        "# Atlas\n- [ ] Enviar informe\n- [x] Hecho\n", encoding="utf-8"
    )
    (root / "Ideas.md").write_text("Una idea sobre café\n", encoding="utf-8")
    (root / ".obsidian" / "secret.md").write_text("config", encoding="utf-8")
    (root / "imagen.png").write_bytes(b"\x89PNG")
    (tmp_path / "outside.md").write_text("fuera", encoding="utf-8")
    return Vault(root, tmp_path / "backups")


@pytest.mark.parametrize(
    "path",
    [
        "../outside.md",
        "/etc/passwd.md",
        "C:/Windows/x.md",
        ".obsidian/secret.md",
        "Ideas.txt",
        "",
        "a/../../outside.md",
    ],
)
def test_paths_outside_markdown_notes_are_rejected(vault, path):
    with pytest.raises(VaultError):
        vault.resolve(path)


def test_symlink_escaping_the_vault_is_rejected(vault, tmp_path):
    link = vault.root / "link.md"
    try:
        link.symlink_to(tmp_path / "outside.md")
    except OSError:
        pytest.skip("symlinks not available")
    with pytest.raises(VaultError):
        vault.resolve("link.md")


def test_list_skips_hidden_folders_and_other_files(vault):
    paths = {n.path for n in vault.list_notes()}

    assert paths == {"Proyectos/atlas.md", "Ideas.md"}
    assert {n.path for n in vault.list_notes(folder="Proyectos")} == {"Proyectos/atlas.md"}
    assert {n.path for n in vault.list_notes(query="idea")} == {"Ideas.md"}


def test_read_search_and_tasks(vault):
    assert vault.read("Proyectos\\atlas.md")["content"].startswith("# Atlas")
    assert vault.search("CAFÉ") == [{"path": "Ideas.md", "line": 1, "text": "Una idea sobre café"}]
    assert vault.open_tasks() == [
        {"path": "Proyectos/atlas.md", "line": 2, "task": "Enviar informe"}
    ]
    with pytest.raises(VaultError):
        vault.read("No/existe.md")


def test_create_append_and_overwrite_with_backup(vault, tmp_path):
    vault.write("Diario/2026-10-30.md", "# Hoy", "create")
    with pytest.raises(VaultError):
        vault.write("Diario/2026-10-30.md", "otra vez", "create")

    vault.write("Diario/2026-10-30.md", "- [ ] Llamar a Ana", "append")
    assert vault.read("Diario/2026-10-30.md")["content"] == "# Hoy\n- [ ] Llamar a Ana\n"

    result = vault.write("Ideas.md", "Nueva versión", "overwrite")
    assert vault.read("Ideas.md")["content"] == "Nueva versión\n"
    backups = list((tmp_path / "backups").rglob("Ideas.md"))
    assert result["backup"] and backups[0].read_text(encoding="utf-8") == "Una idea sobre café\n"

    with pytest.raises(VaultError):
        vault.write("No/existe.md", "x", "overwrite")


def test_snapshot_shows_the_current_note_and_detects_any_edit(vault):
    before = vault.snapshot("Ideas.md")
    assert before["exists"] and before["chars"] == 20
    assert before["current"] == "Una idea sobre café\n"
    assert vault.snapshot("Nueva.md") == {"exists": False}

    # Same length, different content far into the note: the fingerprint still changes.
    (vault.root / "Ideas.md").write_text("Una idea sobre cafe\n", encoding="utf-8")
    assert vault.snapshot("Ideas.md")["sha256"] != before["sha256"]


def test_append_never_rewrites_existing_bytes(vault):
    legacy = "Canción con ñ\r\n".encode("cp1252")  # not UTF-8, CRLF line endings
    (vault.root / "Vieja.md").write_bytes(legacy)

    vault.write("Vieja.md", "- nueva línea", "append")

    data = (vault.root / "Vieja.md").read_bytes()
    assert data.startswith(legacy)  # untouched
    assert data.endswith("- nueva línea\n".encode())


def test_sync_paths_are_not_capped(vault):
    for i in range(250):
        (vault.root / f"n{i}.md").write_text("x", encoding="utf-8")

    assert len(vault.all_paths()) == 252
    assert len(vault.list_notes()) == 200  # what the model sees stays capped
