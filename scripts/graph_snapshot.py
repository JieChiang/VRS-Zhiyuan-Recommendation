"""Portable, bounded-memory graph snapshots. No APOC, database shutdown or auth export."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import settings
from app.neo4j_http import Neo4jHttpClient

FORMAT = "vrs-graph-jsonl-v1"
TEMP_LABEL = "VRSImportNode"
TEMP_ID = "__vrs_import_id"
TEMP_STATUS = "__vrs_import_status"
SECRET = re.compile(r"(?i)(?:sk-[a-z0-9_-]{16,}|gh[pousr]_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,}|-----BEGIN .*PRIVATE KEY-----)")
PRIVATE_PATH = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|/Users/|/home/)")
PRIVATE_FIELD = re.compile(r"(?i)(?:password|api_?key|access_?token|secret)")


def encoded(record):
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def audit(record):
    """Reject private credentials/paths and types this portable format cannot preserve."""
    for key, value in record["properties"].items():
        if key.startswith("__vrs_import_") or PRIVATE_FIELD.search(key):
            raise ValueError("快照包含私有或保留属性，拒绝导出")
        values = value if isinstance(value, list) else [value]
        for item in values:
            if type(item) not in (str, int, float, bool):
                raise ValueError("快照包含不支持的属性类型")
            if isinstance(item, str) and (SECRET.search(item) or PRIVATE_PATH.search(item)):
                raise ValueError("快照包含凭据或本机绝对路径，拒绝导出")
    if TEMP_LABEL in record.get("labels", []):
        raise ValueError("源图谱存在未完成导入，拒绝导出")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stats(client):
    return {
        "nodes": client.run_rows("MATCH (n) RETURN count(n) AS total")[0]["total"],
        "relationships": client.run_rows("MATCH ()-[r]->() RETURN count(r) AS total")[0]["total"],
        "labels": {r["name"]: r["total"] for r in client.run_rows("MATCH (n) UNWIND labels(n) AS name RETURN name,count(*) AS total ORDER BY name")},
        "relationship_types": {r["name"]: r["total"] for r in client.run_rows("MATCH ()-[r]->() RETURN type(r) AS name,count(*) AS total ORDER BY name")},
    }


def export_snapshot(client, folder, batch_size=5000):
    folder = Path(folder)
    if folder.exists() and any(folder.iterdir()):
        raise ValueError("导出目录非空，拒绝覆盖")
    folder.mkdir(parents=True, exist_ok=True)
    before = stats(client)
    types = client.run_rows("MATCH (n) UNWIND keys(n) AS k RETURN DISTINCT valueType(n[k]) AS type UNION MATCH ()-[r]->() UNWIND keys(r) AS k RETURN DISTINCT valueType(r[k]) AS type")
    allowed = re.compile(r"^(?:STRING|INTEGER|FLOAT|BOOLEAN) NOT NULL$|^LIST<(?:STRING|INTEGER|FLOAT|BOOLEAN) NOT NULL> NOT NULL$")
    if any(not allowed.fullmatch(row["type"]) for row in types):
        raise ValueError("图谱含日期、空间或其他类型，当前格式不能无损导出")
    schema = [r["createStatement"] for r in client.run_rows("SHOW CONSTRAINTS YIELD createStatement RETURN createStatement")]
    schema += [r["createStatement"] for r in client.run_rows("SHOW INDEXES YIELD type,owningConstraint,createStatement WHERE type <> 'LOOKUP' AND owningConstraint IS NULL RETURN createStatement")]
    datasets = client.run_rows("MATCH (d:Dataset) RETURN properties(d) AS properties")
    manifest = {"format": FORMAT, "created_at": datetime.now(timezone.utc).isoformat(), "counts": before,
                "datasets": [d["properties"] for d in datasets], "schema": schema, "files": []}
    for kind in ("nodes", "relationships"):
        filename = kind + ".jsonl.gz"
        last, count, digest = -1, 0, hashlib.sha256()
        # CYPHER 5 keeps compatibility with Neo4j 5 and 2026. Internal IDs are
        # snapshot-local references only; the destination allocates its own IDs.
        query = ("CYPHER 5 MATCH (n) WHERE id(n)>$after RETURN id(n) AS id,labels(n) AS labels,properties(n) AS properties ORDER BY id LIMIT $limit"
                 if kind == "nodes" else "CYPHER 5 MATCH (a)-[r]->(b) WHERE id(r)>$after RETURN id(r) AS id,id(a) AS start,id(b) AS end,type(r) AS type,properties(r) AS properties ORDER BY id LIMIT $limit")
        with (folder / filename).open("wb") as raw, gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as stream:
            while True:
                rows = client.run_rows(query, {"after": last, "limit": batch_size})
                if not rows:
                    break
                for row in rows:
                    audit(row)
                    content = encoded(row)
                    stream.write(content)
                    digest.update(content)
                last = rows[-1]["id"]
                count += len(rows)
                if count % 100000 < batch_size:
                    print(f"export {kind}: {count}", flush=True)
        if count != before[kind]:
            raise ValueError("导出期间图谱发生变化，快照无效，请在停止图谱写入后重试")
        manifest["files"].append({"name": filename, "kind": kind, "count": count,
                                  "bytes": (folder / filename).stat().st_size,
                                  "sha256": sha256(folder / filename), "content_sha256": digest.hexdigest()})
    if stats(client) != before:
        raise ValueError("导出期间图谱发生变化，拒绝生成完成标记")
    # Written last: incomplete exports cannot be imported.
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def validate_snapshot(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != FORMAT:
        raise ValueError("不支持的快照格式")
    if {f["kind"] for f in manifest["files"]} != {"nodes", "relationships"} or len(manifest["files"]) != 2:
        raise ValueError("快照文件列表不完整")
    for item in manifest["files"]:
        if item["name"] != item["kind"] + ".jsonl.gz":
            raise ValueError("无效快照文件名")
        path = folder / item["name"]
        if sha256(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise ValueError("快照校验失败：" + item["name"])
        digest, count = hashlib.sha256(), 0
        with gzip.open(path, "rb") as stream:
            for line in stream:
                record = json.loads(line)
                audit(record)
                digest.update(line)
                count += 1
        if count != item["count"] or count != manifest["counts"][item["kind"]] or digest.hexdigest() != item["content_sha256"]:
            raise ValueError("快照内容校验失败：" + item["name"])
    for statement in manifest["schema"]:
        if not re.match(r"^CREATE (?:CONSTRAINT|(?:RANGE |TEXT |POINT |FULLTEXT |VECTOR )?INDEX) ", statement) or ";" in statement:
            raise ValueError("快照含不支持的索引或约束语句")
    return manifest


def identifier(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("无效标签或关系类型")
    return "`" + value.replace("`", "``") + "`"


def import_snapshot(client, folder, batch_size=2000):
    folder = Path(folder)
    manifest = validate_snapshot(folder)  # Hash and privacy check before any writes.
    if client.run_rows("MATCH (n) RETURN count(n) AS total")[0]["total"]:
        raise ValueError("目标数据库非空，拒绝覆盖。请配置独立空库/实例；脚本不会删除现有图谱")
    if client.run_rows("SHOW CONSTRAINTS"):
        raise ValueError("目标数据库含约束，请使用全新的空项目数据库")
    client.run(f"CREATE CONSTRAINT vrs_snapshot_import_id FOR (n:{TEMP_LABEL}) REQUIRE n.{TEMP_ID} IS UNIQUE")
    for kind in ("nodes", "relationships"):
        buffers, total = defaultdict(list), 0

        def flush():
            nonlocal total
            for group, rows in buffers.items():
                if not rows:
                    continue
                if kind == "nodes":
                    labels = ":".join(identifier(v) for v in group)
                    query = f"UNWIND $rows AS row CREATE (n:{TEMP_LABEL}:{labels}) SET n = row.properties, n.{TEMP_ID}=row.id RETURN count(n) AS total"
                else:
                    query = f"UNWIND $rows AS row MATCH (a:{TEMP_LABEL} {{{TEMP_ID}:row.start}}), (b:{TEMP_LABEL} {{{TEMP_ID}:row.end}}) CREATE (a)-[r:{identifier(group)}]->(b) SET r=row.properties RETURN count(r) AS total"
                written = client.run_rows(query, {"rows": rows})[0]["total"]
                if written != len(rows):
                    raise ValueError("关系端点缺失，导入未完成，请使用新的空库重试")
                total += written
                rows.clear()

        with gzip.open(folder / (kind + ".jsonl.gz"), "rt", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if kind == "nodes":
                    group = tuple(sorted(row["labels"]))
                    if not group:
                        raise ValueError("项目快照不接受无标签节点")
                    if "Dataset" in group:
                        row["properties"][TEMP_STATUS] = row["properties"].get("import_status")
                        row["properties"]["import_status"] = "snapshot_importing"
                else:
                    group = row["type"]
                buffers[group].append(row)
                if sum(map(len, buffers.values())) >= batch_size:
                    flush()
                    if total % 100000 < batch_size:
                        print(f"import {kind}: {total}", flush=True)
            flush()
        if total != manifest["counts"][kind]:
            raise ValueError("导入计数不一致")
    # Validate counts and grouping while Dataset stays unavailable to the UI.
    actual = stats(client)
    actual["labels"].pop(TEMP_LABEL, None)
    if actual != manifest["counts"]:
        raise ValueError("导入后图谱统计不一致，保留导入标记以便检查")
    for statement in manifest["schema"]:
        client.run(statement)
    client.run("CALL db.awaitIndexes(300)")
    # Remove temporary metadata in bounded transactions; Dataset becomes ready last.
    while True:
        result = client.run_rows(f"MATCH (n:{TEMP_LABEL}) WHERE NOT n:Dataset WITH n LIMIT $limit REMOVE n:{TEMP_LABEL},n.{TEMP_ID} RETURN count(n) AS total", {"limit": batch_size})
        if not result[0]["total"]:
            break
    client.run(f"MATCH (n:{TEMP_LABEL}:Dataset) SET n.import_status=n.{TEMP_STATUS} REMOVE n:{TEMP_LABEL},n.{TEMP_ID},n.{TEMP_STATUS}")
    client.run("DROP CONSTRAINT vrs_snapshot_import_id")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "validate", "import"])
    parser.add_argument("--path", type=Path, default=ROOT / "graph_snapshot")
    parser.add_argument("--batch-size", type=int, default=2000)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 20000:
        parser.error("batch-size 必须为 1–20000")
    try:
        if args.action == "validate":
            manifest = validate_snapshot(args.path)
        else:
            if settings.neo4j_db.lower() == "system":
                raise ValueError("禁止操作 Neo4j system 数据库")
            client = Neo4jHttpClient(settings.neo4j_url, settings.neo4j_user, settings.neo4j_password, settings.neo4j_db, timeout=300)
            manifest = (export_snapshot if args.action == "export" else import_snapshot)(client, args.path, args.batch_size)
        print(json.dumps({"action": args.action, "ok": True, "counts": manifest["counts"]}, ensure_ascii=False))
    except Exception as exc:
        # Upstream exceptions can echo query parameters. Never print credentials.
        print(f"失败（{type(exc).__name__}）：" + (str(exc) if isinstance(exc, (ValueError, FileNotFoundError)) else "请检查数据库连接、权限和 Neo4j 版本；未完成导入请使用新空库重试"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
