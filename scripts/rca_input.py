#!/usr/bin/env python3
"""Manage RCA experiment inputs.

Examples:
  scripts/rca_input.py import-sample --chunk-size 10000
  scripts/rca_input.py import-file docs/data/sample.dat --chunk-size 10000
  scripts/rca_input.py list
  scripts/rca_input.py show 1 --chars 2000
  scripts/rca_input.py delete 1
  scripts/rca_input.py delete-sample
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import subprocess
import sys
from typing import Optional
import urllib.request
import uuid


API_BASE = os.environ.get("RCA_API_BASE", "http://localhost:18001")
MYSQL_ROOT_PASSWORD = os.environ.get("MYSQL_ROOT_PASSWORD", "Mobigen_1234")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "chat_demo")
MYSQL_SERVICE = os.environ.get("RCA_MYSQL_SERVICE", "mysql")

HELP_EPILOG = """\
Examples:
  # 서버 컨테이너에 있는 docs/data/sample.dat를 10,000건 단위로 import
  ./rca_input.py import-sample --chunk-size 10000

  # 직접 파일 업로드 import
  ./rca_input.py import-file ../docs/data/sample.dat --chunk-size 10000 --input-name sample.dat

  # 저장된 input 목록 확인
  ./rca_input.py list

  # input 본문을 사람이 읽을 수 있게 출력
  ./rca_input.py show 1 --chars 20000

  # 아직 run/step에서 사용하지 않은 input 삭제
  ./rca_input.py delete 1
  ./rca_input.py delete-sample

Environment:
  RCA_API_BASE=http://localhost:18001
  MYSQL_ROOT_PASSWORD=Mobigen_1234
  MYSQL_DATABASE=chat_demo
  RCA_MYSQL_SERVICE=mysql
"""


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
        "--default-character-set=utf8mb4",
        MYSQL_DATABASE,
    ]


def run_mysql(sql: str) -> str:
    proc = subprocess.run(
        mysql_cmd() + ["--raw", "--batch", "--skip-column-names"],
        input=sql,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "mysql command failed")
    return proc.stdout


def multipart_form(fields: dict[str, str], files: Optional[dict[str, str]] = None) -> tuple[bytes, str]:
    boundary = f"----rca-boundary-{uuid.uuid4().hex}"
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    for name, path in (files or {}).items():
        filename = os.path.basename(path)
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            data = f.read()
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode())
        body.extend(data)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def post_multipart(path: str, fields: dict[str, str], files: Optional[dict[str, str]] = None) -> dict:
    data, content_type = multipart_form(fields, files)
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=data,
        headers={"Content-Type": content_type},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read().decode("utf-8"))


def cmd_import_sample(args: argparse.Namespace) -> None:
    result = post_multipart(
        "/api/rca/input/import/sample",
        {
            "chunk_size": str(args.chunk_size),
            "input_name": args.input_name or "",
            "priority": str(args.priority),
            "model": args.model,
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_import_file(args: argparse.Namespace) -> None:
    if not os.path.exists(args.file):
        raise SystemExit(f"파일을 찾을 수 없습니다: {args.file}")
    result = post_multipart(
        "/api/rca/input/import",
        {
            "chunk_size": str(args.chunk_size),
            "input_name": args.input_name or "",
            "priority": str(args.priority),
            "model": args.model,
        },
        {"file": args.file},
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_list(_args: argparse.Namespace) -> None:
    sql = """
SELECT input_id, input_name, priority, hash, update_dt, CHAR_LENGTH(text)
FROM PR_RCA_INPUT
ORDER BY input_id DESC;
"""
    print(run_mysql(sql), end="")


def cmd_show(args: argparse.Namespace) -> None:
    sql = f"SELECT LEFT(text, {int(args.chars)}) FROM PR_RCA_INPUT WHERE input_id={int(args.input_id)};"
    print(run_mysql(sql), end="")


def cmd_delete(args: argparse.Namespace) -> None:
    input_id = int(args.input_id)
    used = run_mysql(f"SELECT COUNT(*) FROM PR_RCA_STEP WHERE input_id={input_id};").strip()
    if used and int(used) > 0:
        raise SystemExit(f"input_id={input_id}는 PR_RCA_STEP {used}건에서 사용 중이라 삭제하지 않습니다")
    print(run_mysql(f"DELETE FROM PR_RCA_INPUT WHERE input_id={input_id}; SELECT ROW_COUNT();"), end="")


def cmd_delete_sample(args: argparse.Namespace) -> None:
    prefix = args.prefix
    prefix_sql = prefix.replace("\\", "\\\\").replace("'", "''")
    sql = f"""
DELETE i
FROM PR_RCA_INPUT i
LEFT JOIN PR_RCA_STEP s ON s.input_id = i.input_id
WHERE s.step_id IS NULL
  AND i.input_name LIKE '{prefix_sql}%';
SELECT ROW_COUNT();
"""
    print(run_mysql(sql), end="")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RCA input 생성/조회/삭제 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_EPILOG,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("import-sample")
    p.add_argument("--chunk-size", type=int, default=10000)
    p.add_argument("--input-name")
    p.add_argument("--priority", type=int, default=0)
    p.add_argument("--model", default="gemma4:26b")
    p.set_defaults(func=cmd_import_sample)

    p = sub.add_parser("import-file")
    p.add_argument("file")
    p.add_argument("--chunk-size", type=int, default=10000)
    p.add_argument("--input-name")
    p.add_argument("--priority", type=int, default=0)
    p.add_argument("--model", default="gemma4:26b")
    p.set_defaults(func=cmd_import_file)

    p = sub.add_parser("list")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show")
    p.add_argument("input_id", type=int)
    p.add_argument("--chars", type=int, default=2000)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("delete")
    p.add_argument("input_id", type=int)
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("delete-sample")
    p.add_argument("--prefix", default="sample.dat")
    p.set_defaults(func=cmd_delete_sample)

    if len(sys.argv) == 1:
        parser.print_help()
        raise SystemExit(0)

    args = parser.parse_args()
    try:
        args.func(args)
    except urllib.error.HTTPError as exc:
        sys.stderr.write(exc.read().decode("utf-8") + "\n")
        raise SystemExit(exc.code)


if __name__ == "__main__":
    main()
