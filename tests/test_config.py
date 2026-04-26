from pathlib import Path

from seedance_aspect.config import load_config


def test_loads_env_from_seedance_aspect_home(monkeypatch, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                'ARK_API_KEY="ark-from-home"',
                'SEEDANCE_MODEL="doubao-seedance-2-0-260128"',
                'TOS_BUCKET="bucket-from-home"',
                'TOS_REGION="cn-beijing"',
            ]
        ),
        encoding="utf-8",
    )
    for key in [
        "ARK_API_KEY",
        "SEEDANCE_MODEL",
        "SEEDANCE_ENDPOINT",
        "TOS_BUCKET",
        "TOS_REGION",
        "SEEDANCE_ASPECT_ENV",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SEEDANCE_ASPECT_HOME", str(tmp_path))
    child = tmp_path / "missing-child"
    child.mkdir()
    monkeypatch.chdir(child)

    config = load_config()

    assert config.api_key == "ark-from-home"
    assert config.model == "doubao-seedance-2-0-260128"
    assert config.tos_bucket == "bucket-from-home"


def test_explicit_env_file_has_priority_over_project_env(monkeypatch, tmp_path: Path):
    explicit_env = tmp_path / "explicit.env"
    explicit_env.write_text('ARK_API_KEY="ark-from-explicit"\n', encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env").write_text('ARK_API_KEY="ark-from-project"\n', encoding="utf-8")

    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.setenv("SEEDANCE_ASPECT_ENV", str(explicit_env))
    monkeypatch.chdir(project)

    config = load_config()

    assert config.api_key == "ark-from-explicit"


def test_os_region_is_accepted_as_tos_region_fallback(monkeypatch, tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text('OS_REGION="cn-shanghai"\n', encoding="utf-8")

    monkeypatch.setenv("SEEDANCE_ASPECT_ENV", str(env_file))
    monkeypatch.setenv("TOS_REGION", "")
    monkeypatch.delenv("OS_REGION", raising=False)
    monkeypatch.chdir(tmp_path)

    config = load_config()

    assert config.tos_region == "cn-shanghai"
