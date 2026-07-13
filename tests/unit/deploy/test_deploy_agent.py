from __future__ import annotations

import os
import subprocess
from pathlib import Path


CANDIDATE_SHA = "a" * 40
DEPLOYED_SHA = "b" * 40
REPO_ROOT = Path(__file__).resolve().parents[3]
AGENT = REPO_ROOT / "deploy" / "tideglass-deploy-agent"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_compose_up_failure_restores_previous_release(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    command_log = tmp_path / "docker.log"
    deploy_root = tmp_path / "deploy"
    deploy_root.mkdir()
    env_file = tmp_path / "production.env"
    env_file.write_text("SESSION_SECRET=test-only\n", encoding="utf-8")
    state_file = deploy_root / "last-deployed-sha"
    state_file.write_text(f"{DEPLOYED_SHA}\n", encoding="utf-8")

    _write_executable(
        fake_bin / "curl",
        f"""#!/usr/bin/env bash
if [[ "${{!#}}" == https://api.github.com/* ]]; then
  printf '%s\n' '{{"workflow_runs":[{{"head_sha":"{CANDIDATE_SHA}","html_url":"https://example.test/run"}}]}}'
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "git",
        f"""#!/usr/bin/env bash
if [[ "$1" == "ls-remote" ]]; then
  printf '%s\\trefs/heads/main\n' '{CANDIDATE_SHA}'
elif [[ "$1" == "clone" ]]; then
  destination="${{!#}}"
  mkdir -p "$destination/.git"
  : > "$destination/docker-compose.yml"
fi
exit 0
""",
    )
    _write_executable(
        fake_bin / "docker",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
if [[ "$1" == "inspect" && "$2" == "--format" ]]; then
  printf '%s\n' 'sha256:previous-image'
  exit 0
fi
if [[ "$1" == "compose" && "$*" == *"repository"* && "$*" != *"rollback-repository"* && "$*" == *" up -d --no-deps web"* ]]; then
  exit 1
fi
exit 0
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_DOCKER_LOG": str(command_log),
            "TIDEGLASS_DEPLOY_ROOT": str(deploy_root),
            "TIDEGLASS_CHECKOUT_DIR": str(deploy_root / "repository"),
            "TIDEGLASS_ROLLBACK_CHECKOUT_DIR": str(deploy_root / "rollback-repository"),
            "TIDEGLASS_STATE_FILE": str(state_file),
            "TIDEGLASS_FAILED_STATE_FILE": str(deploy_root / "failed-deployment-sha"),
            "TIDEGLASS_ENV_FILE": str(env_file),
            "TIDEGLASS_HEALTH_RETRY_SECONDS": "0",
        }
    )

    result = subprocess.run(
        [str(AGENT)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "new deployment failed during docker compose up" in result.stdout
    assert "the previous web release was restored successfully" in result.stderr
    assert (deploy_root / "failed-deployment-sha").read_text(encoding="utf-8").strip() == CANDIDATE_SHA

    commands = command_log.read_text(encoding="utf-8")
    assert "repository" in commands
    assert "rollback-repository" in commands
    assert "up -d --no-deps --force-recreate --no-build web" in commands
