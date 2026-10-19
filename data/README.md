# 本地数据目录

公开仓库不包含原始招生表、考生成绩或本机数据库。请把自己有权使用的 Excel 放入本目录。

- [字段、文件名与缺失值规则](../docs/数据模板说明.md)
- [可填写的 Excel 模板与合成示例](../data_templates/README.md)

仅演示时执行 `python scripts/prepare_demo_data.py`，会在空的 `data/demo/` 中准备 14 份合成示例。该命令拒绝覆盖现有资料，不改动其他数据。

先校验 `python scripts/rebuild_graph.py --validate --data-dir data/demo`，再按主 README 的独立空数据库流程构建。不要将示例数据导入真实业务库。
