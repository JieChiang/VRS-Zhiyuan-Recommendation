# VRS 志愿推荐系统

一个基于浙江历年录取数据的高考志愿推荐项目。输入位次、选科、专业和地区偏好后，可以生成冲稳保候选，再查看院校对比、历年录取情况和数据来源。

后端用 FastAPI，招生数据放在 Neo4j，页面是 Jinja2 和原生 JavaScript。AI 分析接入 DeepSeek，也提供 PyQt6 桌面入口。目前收录的是 **浙江生源、2019–2024 年历史数据**，不包含最新年度的完整招生信息。

## 最近更新

2026-10-23 这次主要补了两个功能：

- **推荐方案导出 Excel**：可以导出当前筛选结果，也可以导出整份推荐。文件里带有生成条件、选科状态、历史分数和位次，以及来源文件和行号。
- **Qt 桌面版**：打开后会自动启动或复用本地后端，补上了文件下载、多窗口共享状态和退出清理，不再需要先手动启动 Web 服务。

这次也整理了启动和配置说明。配置直接在本机 `.env` 中填写，浏览器版使用 Python 命令启动，Qt 版保留双击入口。

## 目前能做什么

- 按位次、三门选科、专业方向和省市筛选，生成冲、稳、保推荐。
- 查看同校同专业的历年分数、位次、计划数，以及排名和满意度。
- 浏览专业目录，查看专业介绍、AI 解读和职业方向。
- 录入模拟考成绩，支持图片 OCR、成绩整理和趋势分析。
- 调整位次、偏好和分层比例，对比不同方案。
- 浏览知识图谱，追踪录取记录的来源。
- 保存草稿、加入院校对比、移除和恢复推荐，导出 Excel。

普通推荐和图谱查询不需要 AI Key。问答、专业解读、成绩整理等 AI 功能会调用 DeepSeek；图片识别还需要 Tesseract。

## 环境准备

开发和测试主要使用 Windows、Python 3.11/3.12。Python 依赖在 `requirements.txt`，包含 Web、OCR、测试和 Qt 桌面入口；页面不需要 npm 构建，ECharts 已放在本地。

另外需要准备：

- **Neo4j 和匹配的 Java/JDK**：用于知识图谱与推荐查询。当前图谱已在 Neo4j Community 2026.04.0 上验证。
- **DeepSeek API Key**：只有使用 AI 功能时需要。
- **Tesseract 5 及 `chi_sim`、`eng` 语言包**：只有识别成绩图片时需要。

Neo4j 的安装要求见[官方文档](https://neo4j.com/docs/operations-manual/current/installation/requirements/)，Tesseract 的安装和语言包见[项目文档](https://tesseract-ocr.github.io/tessdoc/Installation.html)。

## 安装和配置

克隆仓库后，在项目虚拟环境中安装依赖。以下以已经创建好的 Conda `VRS` 环境为例，不要装进 base：

```powershell
git clone https://github.com/JieChiang/VRS-Zhiyuan-Recommendation.git
cd VRS-Zhiyuan-Recommendation
conda activate VRS
python -m pip install -r requirements.txt
```

在项目根目录新建 `.env`，填入自己的配置。已有该文件时直接编辑，不要覆盖：

```dotenv
NEO4J_URL=http://localhost:7474
NEO4J_DB=neo4j
NEO4J_USER=neo4j
NEO4J_PASSWORD=
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash
DEEPSEEK_TIMEOUT=90
TESSERACT_CMD=tesseract
APP_HOST=127.0.0.1
APP_PORT=8000
```

`NEO4J_PASSWORD` 必填，`DEEPSEEK_API_KEY` 按需填写。`NEO4J_URL` 使用 HTTP 地址，不是 `bolt://`；Tesseract 不在 PATH 中时，把 `TESSERACT_CMD` 改为程序完整路径。修改配置后重启服务。

配置读取顺序为：进程环境变量 → `VRS_ENV_FILE` 指定文件 → 项目 `.env` → 用户私有配置 → `setting.yaml`。Windows 用户私有配置默认在 `%APPDATA%/VRS/private.env`。仓库中的 `setting.yaml` 只保留通用默认值，密码和 Key 留空。

登录后可以在侧栏“环境与 API 配置”检查数据库、图谱和 OCR 状态。API Key 填写后可手动验证；只有配置缺失或不可用时，页面顶部才会提示。

## 准备图谱

仓库已有 `graph_snapshot/`，包含浙江 2019–2024 年图谱的逻辑快照，约 31.8 万个节点、149.9 万条关系。文件保留招生事实和来源，不包含数据库账户、密码或用户策略。具体数量和校验值见 [manifest.json](graph_snapshot/manifest.json)。

先启动 Neo4j，配置好 `.env`，然后导入一个**专用于本项目的空数据库**：

```powershell
# 本地文件校验，不连接数据库
python scripts/graph_snapshot.py validate
# 校验通过后导入
python scripts/graph_snapshot.py import
```

这不是 Neo4j 原生 dump，不能用 `neo4j-admin database load` 加载。导入器遇到非空库会拒绝执行，不会自动删库。导入中断后需要使用新的空库重试，详细步骤见 [快照说明](graph_snapshot/README.md)。

如果要换成自己的 Excel 数据，先参考 [14 份示例模板](data_templates/README.md) 和 [字段说明](docs/数据模板说明.md)：

```powershell
python scripts/prepare_demo_data.py
python scripts/rebuild_graph.py --validate --data-dir data/demo
python scripts/rebuild_graph.py --sample 2 --data-dir data/demo
# 确认配置的是独立空库后再构建
python scripts/rebuild_graph.py --data-dir data/demo
```

模板中的数据是合成示例，不能混入真实录取资料。自己的原始表放在本地 `data/` 或其他独立目录，不提交到仓库。通常直接导入快照就够了，不需要再执行一次 Excel 重建。

## 启动

### 浏览器版

在已激活的项目环境中运行：

```powershell
python run_server.py
```

打开 [本地首页](http://127.0.0.1:8000)。也可以指定端口启动：

```powershell
python scripts/start_local.py --port 8765
```

后者会等服务就绪后打开浏览器，添加 `--no-browser` 可只启动服务。

### Qt 桌面版

```powershell
python desktop_app.py
# 指定其他端口
python desktop_app.py --port 8000
```

Windows 也可以双击 `启动桌面版.bat`。这个脚本使用本机 VRS 环境的 Python 路径，换电脑后需要修改其中的 `VRS_PYTHON`。

桌面版默认使用 `127.0.0.1:8765`：已有 VRS 服务就复用，没有则自动启动。端口被其他程序占用时会提示错误。关闭最后一个窗口后，只停止本次新建的服务，已有服务不受影响。

桌面支持 F5 刷新、内部多窗口、Excel 保存对话框，外部链接交给系统浏览器打开。草稿、缓存和默认下载目录在 `storage/desktop/`，不上传仓库。桌面与普通浏览器的草稿各自独立，后端 SQLite 数据共用。更多说明见 [桌面版说明](docs/桌面版说明.md)。

当前登录仍是演示入口，填写任意非空用户名和密码即可，请勿使用真实账户密码。项目还没有正式的多用户权限和数据隔离，不建议直接部署到公网。

## 导出推荐方案

在“推荐院校 → 推荐列表”选择导出范围，再点“导出 Excel”。浏览器版和 Qt 桌面版都可以使用。

- **当前筛选结果**：按搜索词、冲稳保层次、办学层次和性质导出当前看到的记录。
- **全部推荐结果**：导出当前方案的整份列表，保留展示顺序，最多 300 条。

Excel 有“方案说明”和“推荐清单”两张表，支持筛选和冻结表头。生成方案时会保存当时的位次、选科和偏好，后续修改表单不会改写这份记录。旧结果没有保存生成条件时会注明，重新生成即可补全。

缺失数值留空，原始零值保留。单独列出的待核实记录、目标院校补充列表和策略优化结果不包含在导出中。导出只整理已有结果，不调用 AI，也不重新查询数据库。

## 推荐结果怎么看

这些结果只用于整理历史参考，不能当作录取承诺或正式志愿表。

- 默认检索全部符合条件的历史候选；选用位次窗口时才限制检索范围。
- 选科按招生计划原文核验。完整填写三门后，资料不全的记录单独列出；没有匹配计划不等于不限选科。
- 冲稳保目前沿用 ±300 位次分界，比例为 0 的层次不会参与补足。概率和策略权重尚未经过真实录取样本校准。
- 分数不作第二次硬过滤。当前缺少完整的一分一段表、批次和其他报考限制，最终仍要核对当年招生章程。
- AI 输出是辅助分析，不是招生事实。使用时会把问题、相关成绩文本和少量图谱资料发送到 DeepSeek，并消耗 API 额度。

图谱结构和数据处理规则见 [知识图谱说明](docs/知识图谱重构方案.md)。

## 测试

```powershell
python -m unittest discover -s tests -v
node tests/frontend_regression.cjs
python scripts/check_secrets.py --history
python scripts/verify_desktop.py
python scripts/verify_desktop.py --entry
```

当前 104 项 Python 测试通过。Qt 测试使用隐藏窗口，检查实际登录、下载、多窗口和启动退出；环境检查使用模拟数据，不调用真实模型。

浏览器流程测试可选安装 `requirements-dev.txt`：

```powershell
python -m pip install -r requirements-dev.txt
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\storage\browser-runtime"
python -m playwright install chromium --only-shell
python scripts/verify_recommendation_export.py
```

测试截图和下载样本保存在本地 `storage/`。`scripts/verify_llm.py --live` 会调用真实付费 API，日常回归不需要运行。

## 目录

```text
app/                页面、API、推荐与图谱服务、Qt 窗口
data/               本地原始资料（不提交）
data_templates/     合成 Excel 模板和字段定义
graph_snapshot/     可导入的历史图谱快照
docs/               数据、图谱和桌面版说明
scripts/            启动、导入、校验和测试工具
tests/              单元与前端测试
storage/            数据库、缓存、草稿和测试产物（不提交）
```

API Key、数据库密码只保存在本机环境变量或私有配置中。`.env`、SQLite、原始资料、浏览器缓存和日志都不进入公开仓库。ECharts 的许可证保留在 `app/static/vendor/`，数据来源和使用限制见对应文档。
