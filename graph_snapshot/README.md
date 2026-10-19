# 完整浙江历史知识图谱快照

从已构建的本地 Neo4j 项目库在线只读导出。范围为浙江生源、2019–2024 年历史资料，包含 317,582 个节点、1,499,418 条有向关系、19 种节点标签、22 种关系类型。完整计数、生成时间、项目约束与索引定义以 `manifest.json` 为准。

| 文件 | 内容 | 大小 |
| --- | --- | --- |
| `nodes.jsonl.gz` | 所有节点、标签、属性与快照引用 ID | 约 19.2 MiB |
| `relationships.jsonl.gz` | 所有有向关系、类型、端点引用和属性 | 约 8.6 MiB |
| `manifest.json` | 格式版本、SHA-256、内容哈希、统计及 schema | 约 5 KiB |

不是原生 `.dump` 文件，不能用 `neo4j-admin database load` 加载。无需 Git LFS、APOC、原始 Excel 或 DeepSeek Key。原 Neo4j 数据库账户、密码、系统库、SQLite 与考生成绩均不在快照中。源文件名称、工作表、行号、哈希及人工核对的公开网址属于事实溯源，随数据保留。导出器会检查凭据模式和本机绝对路径，不输出敏感值。

## 导入

安装项目依赖、启动 Neo4j 并在 `.env` 填写自己的 HTTP 地址、数据库名、用户名和密码；详见[项目 README](../README.md)。目标必须是专用于本项目的全新空库/独立实例。

```powershell
# 从项目根目录执行；validate 不连接数据库
python scripts/graph_snapshot.py validate
python scripts/graph_snapshot.py import
```

`--path` 可指定其他快照目录；`--batch-size 500` 可降低单批内存占用（默认 2000）。已验证 Neo4j Community 2026.04.0；使用 Cypher 5 兼容模式和 HTTP 事务接口。不同版本的索引/约束兼容性需要在空实例中先验证。

导入依次校验文件、创建临时唯一索引、分批导入节点和关系、验证总数/分组计数、恢复项目 schema、等待索引就绪、移除临时映射字段。Dataset 在导入过程中保持未就绪，完成后恢复原状态。非空库或已有约束的库会被拒绝，脚本不删除现有数据。中断后请使用新的空库重试；不要向含部分数据的库重复导入。不要将配置指向 `system` 数据库。

## 格式与重新导出

格式 ID：`vrs-graph-jsonl-v1`。gzip 解压后每行是一个 UTF-8 JSON 对象：

```json
{"id":0,"labels":["Institution"],"properties":{"name":"示例院校"}}
```

```json
{"id":0,"start":0,"end":1,"type":"HAS_OFFER","properties":{}}
```

上面的数字仅为格式示例；实际内部 ID 仅用于快照内定位，导入端重新分配数据库 ID，完成后删除映射。当前源图谱仅含字符串、整数、浮点与布尔属性；未来增加时间、空间或其他 Neo4j 专有类型时，需要扩展格式，脚本会拒绝不能无损处理的类型。

重新导出时，应暂停其他图谱写入操作（Web 查询可继续），输出到不存在或空的目录；完成后才生成清单。前后统计复核不能检测并发的同数量属性改写，因此导出期间不要重建或修订图谱。

```powershell
python scripts/graph_snapshot.py export --path data/local-snapshot
python scripts/graph_snapshot.py validate --path data/local-snapshot
```

此路径默认被 Git 忽略。发布新的快照前，检查其隐私、数据范围与来源使用许可。历史录取与计划不代表当前招生政策，缺失和冲突数据的适用限制见项目 README。
