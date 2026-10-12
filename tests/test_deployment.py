import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text())
DEPLOY_SCRIPT = WORKFLOW["jobs"]["deploy"]["steps"][0]["with"]["script"]
SSH_REMOTE = "git@github.com:WanMusa/ai-platform_local-llm.git"


def run(*args, **kwargs):
    return subprocess.run(args, text=True, capture_output=True, **kwargs)


@pytest.fixture
def deployment(tmp_path):
    home = tmp_path / "home"
    target = home / "projects/ai-platform_local-llm"
    target.mkdir(parents=True)
    (target / ".env").write_text("preserve-this-file\n")
    (home / ".ssh").mkdir()
    for name in ("local_llm_github", "known_hosts"):
        (home / ".ssh" / name).touch()
    source = tmp_path / "source"
    source.mkdir()
    assert run("git", "init", "-b", "main", str(source)).returncode == 0
    (source / ".gitignore").write_text(".env\n")
    (source / "scripts").mkdir()
    (source / "scripts/start_services.sh").write_text("echo STARTED\n")
    assert run("git", "-C", str(source), "add", ".").returncode == 0
    assert run("git", "-C", str(source), "-c", "user.name=Test", "-c",
               "user.email=test@example.invalid", "commit", "-m", "fixture").returncode == 0
    config = tmp_path / "gitconfig"
    assert run("git", "config", "--file", str(config),
               f"url.{source}.insteadOf", SSH_REMOTE).returncode == 0
    env = dict(os.environ, HOME=str(home), GIT_CONFIG_GLOBAL=str(config))
    return target, source, env


def deploy(env):
    return run("bash", "-c", DEPLOY_SCRIPT, env=env)


def test_precreated_env_bootstrap_and_repeat(deployment):
    target, _, env = deployment
    for _ in range(2):
        result = deploy(env)
        assert result.returncode == 0, result.stderr
        assert "STARTED" in result.stdout
        assert (target / ".env").read_text() == "preserve-this-file\n"
    assert run("git", "-C", str(target), "branch", "--show-current").stdout.strip() == "main"


def test_nonclone_local_files_are_not_overwritten(deployment):
    target, _, env = deployment
    (target / "important.txt").write_text("keep me")
    result = deploy(env)
    assert result.returncode != 0
    assert "not a Git clone" in result.stdout
    assert (target / "important.txt").read_text() == "keep me"
    assert not (target / ".git").exists()


def test_existing_https_remote_migrates_and_dirty_edits_refused(deployment):
    target, _, env = deployment
    assert deploy(env).returncode == 0
    assert run("git", "-C", str(target), "remote", "set-url", "origin",
               "https://github.com/WanMusa/ai-platform_local-llm.git").returncode == 0
    assert deploy(env).returncode == 0
    (target / "scripts/start_services.sh").write_text("echo LOCAL_EDIT\n")
    result = deploy(env)
    assert result.returncode != 0
    assert "clean main checkout" in result.stdout
    assert "LOCAL_EDIT" in (target / "scripts/start_services.sh").read_text()


def test_unexpected_remote_not_printed_or_changed(deployment):
    target, _, env = deployment
    assert deploy(env).returncode == 0
    remote = "https://unexpected.invalid/another-repo.git"
    run("git", "-C", str(target), "remote", "set-url", "origin", remote)
    result = deploy(env)
    assert result.returncode != 0
    assert remote not in result.stdout + result.stderr
    assert run("git", "-C", str(target), "remote", "get-url", "origin").stdout.strip() == remote


def test_missing_env_preflight(deployment):
    target, _, env = deployment
    (target / ".env").unlink()
    assert deploy(env).returncode != 0
    assert not (target / ".git").exists()


def test_incomplete_bootstrap_can_retry(deployment):
    target, _, env = deployment
    run("git", "-C", str(target), "init", "-b", "main")
    run("git", "-C", str(target), "remote", "add", "origin", SSH_REMOTE)
    assert deploy(env).returncode == 0
    assert (target / ".env").read_text() == "preserve-this-file\n"


def test_ignored_local_file_collision_refused(deployment):
    target, source, env = deployment
    assert deploy(env).returncode == 0
    (target / ".git/info/exclude").write_text("notes.txt\n")
    (target / "notes.txt").write_text("local notes")
    (source / "notes.txt").write_text("upstream notes")
    run("git", "-C", str(source), "add", "notes.txt")
    run("git", "-C", str(source), "-c", "user.name=Test", "-c",
        "user.email=test@example.invalid", "commit", "-m", "new file")
    result = deploy(env)
    assert result.returncode != 0
    assert (target / "notes.txt").read_text() == "local notes"


def test_workflow_serial_and_timeouts():
    assert WORKFLOW["concurrency"]["cancel-in-progress"] is False
    assert WORKFLOW["jobs"]["deploy"]["timeout-minutes"] >= 55
    assert WORKFLOW["jobs"]["deploy"]["steps"][0]["with"]["command_timeout"] == "55m"
    assert "StrictHostKeyChecking=yes" in DEPLOY_SCRIPT


@pytest.mark.parametrize("failed_step", ["", "config", "model"])
def test_start_services_order_and_failure_is_closed(tmp_path, failed_step):
    project = tmp_path / "app"
    (project / "scripts").mkdir(parents=True)
    script = project / "scripts/start_services.sh"
    script.write_text((ROOT / "scripts/start_services.sh").read_text())
    (project / ".env").touch()
    calls = tmp_path / "calls"
    shell_env = tmp_path / "bash_env"
    shell_env.write_text("""
docker() {
    printf '%s\\n' "$*" >> "$CALL_LOG"
    if [ "$FAIL_STEP" = config ] && [ "$*" = "compose config --quiet" ]; then return 1; fi
    return 0
}
timeout() {
    printf 'timeout %s\\n' "$1" >> "$CALL_LOG"
    if [ "$FAIL_STEP" = model ]; then return 124; fi
    shift
    "$@"
}
""")
    env = dict(os.environ, BASH_ENV=str(shell_env), CALL_LOG=str(calls), FAIL_STEP=failed_step)
    result = run("bash", str(script), env=env)
    recorded = calls.read_text()
    if failed_step:
        assert result.returncode != 0
        assert "compose up -d --build" not in recorded
    else:
        assert result.returncode == 0
        assert recorded.index("compose up -d ollama") < recorded.index("timeout 1800")
        assert recorded.index("timeout 1800") < recorded.index("compose up -d --build")
        assert 'ollama show "$LLM_MODEL"' in recorded
        assert 'ollama pull "$LLM_MODEL"' in recorded


@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose CLI unavailable")
def test_compose_config_and_required_https_values(tmp_path):
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text((ROOT / "docker-compose.yml").read_text())
    (tmp_path / ".env").touch()
    env_file = tmp_path / "compose.env"
    values = {
        "APP_DOMAIN": "localgemma.wanagents.duckdns.org",
        "LETSENCRYPT_EMAIL": "test@example.invalid",
        "LOCAL_LLM_API_TOKEN": "unit-test-only-bearer-value-0123456789",
    }
    env = {k: v for k, v in os.environ.items() if k not in values}

    def config(settings):
        env_file.write_text("".join(f"{k}={v}\n" for k, v in settings.items()))
        return run("docker", "compose", "--env-file", str(env_file), "-f",
                   str(compose_file), "config", "--no-env-resolution",
                   "--format", "json", env=env)

    result = config(values)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    api = data["services"]["local-llm-api"]
    ollama = data["services"]["ollama"]
    assert not api.get("ports") and not ollama.get("ports")
    assert api["environment"]["VIRTUAL_HOST"] == values["APP_DOMAIN"]
    assert api["environment"]["LETSENCRYPT_HOST"] == values["APP_DOMAIN"]
    assert api["environment"]["VIRTUAL_PORT"] == "8000"
    assert set(api["networks"]) == {"ai_platform", "model_private"}
    assert set(ollama["networks"]) == {"model_private"}
    assert ollama["volumes"][0]["source"] == "ollama_data"
    assert data["networks"]["ai_platform"]["external"] is True
    for name in values:
        assert config({**values, name: ""}).returncode != 0
