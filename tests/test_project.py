import pytest

from ytkit import project


def test_project_root_default_is_parent_of_scripts_dir(tmp_path, monkeypatch):
    monkeypatch.delenv(project.ENV_ROOT, raising=False)
    script = tmp_path / 'scripts' / 'x.py'
    script.parent.mkdir()
    script.write_text('')
    assert project.project_root(script) == tmp_path


def test_project_root_falls_back_to_a_channel_toml_found_from_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv(project.ENV_ROOT, raising=False)
    (tmp_path / 'channel.toml').write_text('', encoding='utf-8')
    deep = tmp_path / 'a' / 'b'
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    elsewhere = tmp_path.parent / 'pkg' / 'site' / 'mod.py'   # 共有パッケージの中(プロジェクトの外)から呼ばれた想定
    assert project.project_root(elsewhere) == tmp_path


def test_project_root_prefers_script_side_channel_toml(tmp_path, monkeypatch):
    monkeypatch.delenv(project.ENV_ROOT, raising=False)
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'channel.toml').write_text('', encoding='utf-8')
    other = tmp_path / 'other'
    other.mkdir()
    (other / 'channel.toml').write_text('', encoding='utf-8')
    monkeypatch.chdir(other)
    assert project.project_root(tmp_path / 'scripts' / 'x.py') == tmp_path


def test_project_root_env_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv(project.ENV_ROOT, str(tmp_path / 'other'))
    assert project.project_root(tmp_path / 'scripts' / 'x.py') == tmp_path / 'other'


def test_load_config_reads_toml_and_missing_file_is_named(tmp_path):
    (tmp_path / 'channel.toml').write_text('[channel]\nname = "テスト"\n', encoding='utf-8')
    cfg = project.load_config(tmp_path)
    assert cfg['channel']['name'] == 'テスト'
    with pytest.raises(project.ConfigError) as e:
        project.load_config(tmp_path / 'nowhere')
    assert 'channel.toml' in str(e.value) and 'YT_PROJECT_ROOT' in str(e.value)


def test_section_returns_requested_keys_and_names_the_missing_one():
    cfg = {'voice': {'speaker': 'A', 'style': 'B', 'extra': 1}}
    assert project.section(cfg, 'voice', ('speaker', 'style')) == {'speaker': 'A', 'style': 'B'}
    with pytest.raises(project.ConfigError) as e:
        project.section(cfg, 'voice', ('speaker', 'speed'))
    assert 'voice.speed' in str(e.value)


def test_require_returns_value_and_names_the_missing_key():
    cfg = {'channel': {'name': 'A'}, 'bgm': {}}
    assert project.require(cfg, 'channel.name') == 'A'
    with pytest.raises(project.ConfigError) as e:
        project.require(cfg, 'bgm.file')
    assert 'bgm.file' in str(e.value)
    with pytest.raises(project.ConfigError):
        project.require(cfg, 'voice.speaker')
