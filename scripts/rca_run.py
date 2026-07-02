#!/usr/bin/env python3
"""Run and inspect RCA experiment executions.

Examples:
  scripts/rca_run.py run --input-id 1 --prompt-id 1 --model gemma4:26b
  scripts/rca_run.py list-runs
  scripts/rca_run.py list-steps
  scripts/rca_run.py show-run 1
  scripts/rca_run.py show-result 1
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request


API_BASE = os.environ.get("RCA_API_BASE", "http://localhost:18001")
MYSQL_ROOT_PASSWORD = os.environ.get("MYSQL_ROOT_PASSWORD", "Mobigen_1234")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "chat_demo")
MYSQL_SERVICE = os.environ.get("RCA_MYSQL_SERVICE", "mysql")


def mysql_cmd() -> list[str]:
    return [
        "docker",
        "compose",
        "exec",
        "-T",
        MYSQL_SERVICE,
        "mysql",
        "-uroot",
        f"-p{MYSQL_ROOT_PASSWORD}",
        MYSQL_DATABASE,
    ]


def run_mysql(sql: str) -> str:
    proc = subprocess.run(
        mysql_cmd() + ["-N", "-B"],
        input=sql,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "mysql command failed")
    return proc.stdout


def post_json(path: str, payload: dict, timeout: int) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_run(args: argparse.Namespace) -> None:
    result = post_json(
        "/api/rca/run/normal",
        {
            "input_id": args.input_id,
            "prompt_id": args.prompt_id,
            "model": args.model,
            "priority": args.priority,
        },
        args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_list_runs(_args: argparse.Namespace) -> None:
    sql = """
SELECT r.run_id, r.run_mode, COUNT(s.step_id) AS step_count, r.update_dt
FROM PR_RCA_RUN r
LEFT JOIN PR_RCA_STEP s ON s.run_id = r.run_id
GROUP BY r.run_id, r.run_mode, r.update_dt
ORDER BY r.run_id DESC
LIMIT 50;
"""
    print(run_mysql(sql), end="")


def cmd_list_steps(_args: argparse.Namespace) -> None:
    sql = """
SELECT step_id, step_type, run_id, input_id, prompt_id, result_id, update_dt
FROM PR_RCA_STEP
ORDER BY step_id DESC
LIMIT 50;
"""
    print(run_mysql(sql), end="")


def cmd_show_run(args: argparse.Namespace) -> None:
    run_id = int(args.run_id)
    sql = f"""
SELECT r.run_id, r.run_mode, r.update_dt
FROM PR_RCA_RUN r
WHERE r.run_id = {run_id};
SELECT s.step_id, s.step_type, s.input_id, s.prompt_id, s.result_id, s.update_dt
FROM PR_RCA_STEP s
WHERE s.run_id = {run_id}
ORDER BY s.step_id;
"""
    print(run_mysql(sql), end="")


def cmd_show_result(args: argparse.Namespace) -> None:
    sql = f"SELECT text FROM PR_RCA_RESULT WHERE result_id={int(args.result_id)};"
    print(run_mysql(sql), end="")


def cmd_counts(_args: argparse.Namespace) -> None:
    sql = """
SELECT 'inputs', COUNT(*) FROM PR_RCA_INPUT;
SELECT 'prompts', COUNT(*) FROM PR_RCA_PROMPT;
SELECT 'runs', COUNT(*) FROM PR_RCA_RUN;
SELECT 'steps', COUNT(*) FROM PR_RCA_STEP;
SELECT 'results', COUNT(*) FROM PR_RCA_RESULT;
"""
    print(run_mysql(sql), end="")


def main() -> None:
    parser = argparse.ArgumentParser(description="RCA run/result 확인 스크립트")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run")
    p.add_argument("--input-id", type=int, required=True)
    p.add_argument("--prompt-id", type=int, required=True)
    p.add_argument("--model", default="gemma4:26b")
    p.add_argument("--priority", type=int, default=0)
    p.add_argument("--timeout", type=int, default=600)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("list-runs")
    p.set_defaults(func=cmd_list_runs)

    p = sub.add_parser("list-steps")
    p.set_defaults(func=cmd_list_steps)

    p = sub.add_parser("show-run")
    p.add_argument("run_id", type=int)
    p.set_defaults(func=cmd_show_run)

    p = sub.add_parser("show-result")
    p.add_argument("result_id", type=int)
    p.set_defaults(func=cmd_show_result)

    p = sub.add_parser("counts")
    p.set_defaults(func=cmd_counts)

    args = parser.parse_args()
    try:
        args.func(args)
    except urllib.error.HTTPError as exc:
        sys.stderr.write(exc.read().decode("utf-8") + "\n")
        raise SystemExit(exc.code)


if __name__ == "__main__":
    main()
