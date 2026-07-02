#!/usr/bin/env python3
"""Manage RCA experiment prompts.

Examples:
  scripts/rca_prompt.py create --file prompt.md
  scripts/rca_prompt.py list
  scripts/rca_prompt.py show 1
  scripts/rca_prompt.py update 1 --file prompt_v2.md
  scripts/rca_prompt.py delete 1
"""
from __future__ import annotations

import argparse
import hashlib
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


def sql_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(args: argparse.Namespace) -> str:
    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            return f.read()
    if args.text is not None:
        return args.text
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("--file 또는 --text 또는 stdin 입력이 필요합니다")


def post_json(path: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_create(args: argparse.Namespace) -> None:
    text = read_text(args).strip()
    if not text:
        raise SystemExit("prompt text가 비어 있습니다")
    print(json.dumps(post_json("/api/rca/prompt", {"text": text, "priority": args.priority}), ensure_ascii=False, indent=2))


def cmd_list(_args: argparse.Namespace) -> None:
    sql = """
SELECT prompt_id, priority, hash, update_dt, LEFT(REPLACE(REPLACE(text, '\\n', ' '), '\\t', ' '), 100)
FROM PR_RCA_PROMPT
ORDER BY prompt_id DESC;
"""
    print(run_mysql(sql), end="")


def cmd_show(args: argparse.Namespace) -> None:
    sql = f"SELECT text FROM PR_RCA_PROMPT WHERE prompt_id={int(args.prompt_id)};"
    print(run_mysql(sql), end="")


def cmd_update(args: argparse.Namespace) -> None:
    text = read_text(args).strip()
    if not text:
        raise SystemExit("prompt text가 비어 있습니다")
    prompt_hash = sha256_text(text)
    priority_sql = f", priority={int(args.priority)}" if args.priority is not None else ""
    sql = (
        "UPDATE PR_RCA_PROMPT "
        f"SET text={sql_quote(text)}, hash={sql_quote(prompt_hash)}{priority_sql} "
        f"WHERE prompt_id={int(args.prompt_id)};"
        f"SELECT prompt_id, hash, priority, update_dt FROM PR_RCA_PROMPT WHERE prompt_id={int(args.prompt_id)};"
    )
    print(run_mysql(sql), end="")


def cmd_delete(args: argparse.Namespace) -> None:
    prompt_id = int(args.prompt_id)
    used = run_mysql(f"SELECT COUNT(*) FROM PR_RCA_STEP WHERE prompt_id={prompt_id};").strip()
    if used and int(used) > 0:
        raise SystemExit(f"prompt_id={prompt_id}는 PR_RCA_STEP {used}건에서 사용 중이라 삭제하지 않습니다")
    print(run_mysql(f"DELETE FROM PR_RCA_PROMPT WHERE prompt_id={prompt_id}; SELECT ROW_COUNT();"), end="")


def main() -> None:
    parser = argparse.ArgumentParser(description="RCA prompt 관리 스크립트")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create")
    p.add_argument("--file")
    p.add_argument("--text")
    p.add_argument("--priority", type=int, default=0)
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("list")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show")
    p.add_argument("prompt_id", type=int)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("update")
    p.add_argument("prompt_id", type=int)
    p.add_argument("--file")
    p.add_argument("--text")
    p.add_argument("--priority", type=int)
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("delete")
    p.add_argument("prompt_id", type=int)
    p.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
