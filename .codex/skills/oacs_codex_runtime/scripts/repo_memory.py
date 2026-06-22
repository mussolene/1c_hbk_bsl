from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from oacs.app import OacsServices, services
from oacs.core.attribution import Attribution
from oacs.core.json import hash_json
from oacs.memory.models import EvidenceItem


def main() -> None:
    payload = json.loads(sys.stdin.read() or "{}")
    action = str(payload.get("action", ""))
    if action == "capture":
        result = capture(payload)
    elif action == "context":
        result = context(payload)
    elif action == "auto_start":
        result = auto_start(payload)
    elif action == "auto_finish":
        result = auto_finish(payload)
    elif action == "autorun":
        result = autorun(payload)
    else:
        raise SystemExit(f"unsupported repo memory action: {action}")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def capture(payload: dict[str, Any]) -> dict[str, Any]:
    svc = _services(payload)
    task = _required(payload, "task")
    summary = _required(payload, "summary")
    cwd = _cwd(payload)
    repo_scope = _scope(payload, cwd)
    return _commit_repo_episode(
        svc,
        task,
        summary,
        _actor(payload),
        repo_scope,
        _repo_state(cwd),
    )


def context(payload: dict[str, Any]) -> dict[str, Any]:
    svc = _services(payload)
    task = _required(payload, "task")
    cwd = _cwd(payload)
    repo_scope = _scope(payload, cwd)
    capsule = svc.context.build(
        task,
        _actor(payload),
        _agent(payload),
        repo_scope,
        int(str(payload.get("budget", 4000))),
    )
    return {
        "capsule": capsule.model_dump(),
        "explain": svc.context.explain(capsule.id, _actor(payload)),
    }


def auto_start(payload: dict[str, Any]) -> dict[str, Any]:
    svc = _services(payload)
    task = _required(payload, "task")
    cwd = _cwd(payload)
    repo_scope = _scope(payload, cwd)
    capsule = svc.context.build(
        task,
        _actor(payload),
        _agent(payload),
        repo_scope,
        int(str(payload.get("budget", 4000))),
    )
    svc.audit.record(
        "repo.auto_start",
        _actor(payload),
        capsule.id,
        {"task_hash": hash_json(task), "auto_memory": True},
    )
    return {
        "task": task,
        "scope": repo_scope,
        "git": _repo_state(cwd),
        "capsule": capsule.model_dump(),
        "explain": svc.context.explain(capsule.id, _actor(payload)),
        "auto_memory_policy": {
            "start_writes_memory": False,
            "finish_commits_depth": 1,
            "d2_d3_auto_commit": False,
        },
    }


def auto_finish(payload: dict[str, Any]) -> dict[str, Any]:
    svc = _services(payload)
    task = _required(payload, "task")
    summary = _required(payload, "summary")
    cwd = _cwd(payload)
    return _commit_repo_episode(
        svc,
        task,
        summary,
        _actor(payload),
        _scope(payload, cwd),
        _repo_state(cwd),
        outcome=_optional(payload, "outcome"),
        auto_memory=True,
    )


def autorun(payload: dict[str, Any]) -> dict[str, Any]:
    svc = _services(payload)
    task = _required(payload, "task")
    command = _required(payload, "command")
    cwd = _cwd(payload)
    repo_scope = _scope(payload, cwd)
    capsule = svc.context.build(
        task,
        _actor(payload),
        _agent(payload),
        repo_scope,
        int(str(payload.get("budget", 4000))),
    )
    args = shlex.split(command)
    if not args:
        raise SystemExit("command must not be empty")
    timeout = int(str(payload.get("timeout", 300)))
    try:
        completed = subprocess.run(
            args,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        exit_code = completed.returncode
        stdout_tail = completed.stdout[-4000:]
        stderr_tail = completed.stderr[-4000:]
        outcome = "passed" if exit_code == 0 else "failed"
        summary = f"Autorun command {outcome}: {command}"
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout_tail = (exc.stdout or "")[-4000:] if isinstance(exc.stdout, str) else ""
        stderr_tail = (exc.stderr or "")[-4000:] if isinstance(exc.stderr, str) else ""
        outcome = "timeout"
        summary = f"Autorun command timed out after {timeout}s: {command}"
    memory = _commit_repo_episode(
        svc,
        task,
        summary,
        _actor(payload),
        repo_scope,
        _repo_state(cwd),
        outcome=outcome,
        command=command,
        exit_code=exit_code,
        auto_memory=True,
    )
    svc.audit.record(
        "repo.autorun",
        _actor(payload),
        str(memory["memory_id"]),
        {
            "capsule_id": capsule.id,
            "command_hash": hash_json(command),
            "exit_code": exit_code,
            "auto_memory": True,
        },
    )
    return {
        "task": task,
        "scope": repo_scope,
        "capsule_id": capsule.id,
        "command": command,
        "exit_code": exit_code,
        "outcome": outcome,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "memory": memory,
    }


def _commit_repo_episode(
    svc: OacsServices,
    task: str,
    summary: str,
    actor: str | None,
    repo_scope: list[str],
    state: dict[str, Any],
    *,
    outcome: str | None = None,
    command: str | None = None,
    exit_code: int | None = None,
    auto_memory: bool = False,
) -> dict[str, Any]:
    lines = [
        f"Repository task: {task}",
        f"Summary: {summary}",
        f"Git branch: {state['branch']}",
        f"Git commit: {state['commit']}",
        f"Dirty worktree: {state['dirty']}",
    ]
    if outcome:
        lines.append(f"Outcome: {outcome}")
    if command:
        lines.append(f"Command: {command}")
    if exit_code is not None:
        lines.append(f"Exit code: {exit_code}")
    evidence = [
        EvidenceItem(
            evidence_kind="repo_task_trace",
            claim="Repository development task summary",
            value=summary,
            source_ref=f"git:{state['commit']}",
            confidence=1.0,
            scope=repo_scope,
            slot="evidence",
            attribution=Attribution(
                source_actor_id=actor,
                source_actor_type="agent",
                recorded_by_actor_id=actor,
                role="agent_decision",
            ),
        )
    ]
    proposed = svc.memory.propose(
        "episode",
        1,
        "\n".join(lines),
        actor,
        repo_scope,
        evidence=evidence,
        attribution=Attribution(
            source_actor_id=actor,
            source_actor_type="agent",
            recorded_by_actor_id=actor,
            role="agent_decision",
        ),
    )
    committed = svc.memory.commit(proposed.id, actor)
    svc.audit.record(
        "repo.capture",
        actor,
        committed.id,
        {
            "task_hash": hash_json(task),
            "auto_memory": auto_memory,
            "outcome": outcome,
            "command_hash": hash_json(command) if command else None,
            "exit_code": exit_code,
        },
    )
    result: dict[str, Any] = {
        "memory_id": committed.id,
        "scope": repo_scope,
        "git": state,
        "status": committed.lifecycle_status,
    }
    if auto_memory:
        result["auto_memory_policy"] = {
            "committed_depth": 1,
            "committed_type": "episode",
            "d2_d3_auto_commit": False,
        }
    return result


def _services(payload: dict[str, Any]) -> OacsServices:
    return services(_optional(payload, "db"))


def _scope(payload: dict[str, Any], cwd: Path) -> list[str]:
    raw = payload.get("scope")
    if isinstance(raw, list) and raw:
        return [str(item) for item in raw]
    return _repo_scope(cwd)


def _repo_scope(cwd: Path) -> list[str]:
    root = _git_value(["rev-parse", "--show-toplevel"], cwd)
    repo_name = Path(root).name if root else cwd.resolve().name
    return [f"repo:{repo_name}"]


def _repo_state(cwd: Path) -> dict[str, Any]:
    changed = (_git_value(["status", "--short"], cwd) or "").splitlines()
    return {
        "branch": _git_value(["branch", "--show-current"], cwd) or "unknown",
        "commit": _git_value(["rev-parse", "--short", "HEAD"], cwd) or "unknown",
        "dirty": bool(changed),
        "changed_files": changed[:50],
    }


def _git_value(args: list[str], cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _cwd(payload: dict[str, Any]) -> Path:
    return Path(str(payload.get("cwd") or "."))


def _actor(payload: dict[str, Any]) -> str | None:
    return _optional(payload, "actor")


def _agent(payload: dict[str, Any]) -> str | None:
    return _optional(payload, "agent")


def _required(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None or str(value) == "":
        raise SystemExit(f"{key} is required")
    return str(value)


def _optional(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    text = str(value)
    return text or None


if __name__ == "__main__":
    main()
