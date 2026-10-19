"""Configuration diagnostics with safe messages and no automatic model generation."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.graph_data import DATASET_ID
from app.neo4j_http import Neo4jHttpClient


class ConfigurationChecks:
    def __init__(self, settings):
        self.settings = settings
        self._cache = None
        self._checked = 0
        self._model = None
        self._model_checked = 0
        self._lock = threading.Lock()

    def neo4j(self):
        result = {"name": "Neo4j / 知识图谱", "required_for": "推荐、对比、图谱探索", "docs_url": "https://neo4j.com/docs/operations-manual/current/installation/windows/"}
        if not self.settings.neo4j_password.strip():
            return dict(result, state="missing", ready=False, title="数据库密码未填写", detail="在 .env 填写 NEO4J_PASSWORD，并配置 NEO4J_URL（HTTP 7474）、NEO4J_DB、NEO4J_USER，随后重启服务。")
        try:
            client = Neo4jHttpClient(self.settings.neo4j_url, self.settings.neo4j_user, self.settings.neo4j_password, self.settings.neo4j_db, timeout=5)
            rows = client.run_rows("MATCH (d:Dataset {dataset_id:$dataset}) RETURN d.import_status AS status,d.offer_count AS offer_count", {"dataset": DATASET_ID})
            if not rows:
                return dict(result, state="warning", ready=False, title="数据库已连接，图谱未导入", detail="运行 python scripts/graph_snapshot.py import 导入仓库快照，或按 README 从 Excel 构建。导入脚本只接受空库。")
            if rows[0]["status"] != "ready":
                return dict(result, state="warning", ready=False, title="数据库已连接，图谱尚未就绪", detail="图谱构建或导入未完成；完成后重新检查。导入失败时请使用新的空库重试。")
            return dict(result, state="ok", ready=True, title="数据库已连接，图谱已就绪", detail=f"浙江历史图谱可用，包含 {int(rows[0]['offer_count'] or 0):,} 条录取事实。")
        except HTTPError as exc:
            detail = "数据库认证失败，请核对用户名、密码并重启应用。" if exc.code in (401, 403) else "数据库 HTTP 接口不可用，请检查数据库名、HTTP 地址和 Neo4j 版本。"
        except Exception:
            detail = "无法连接数据库。请启动 Neo4j，并核对 HTTP 7474 端口、数据库名、用户名与密码；Neo4j 所需 JDK 版本见安装说明。"
        return dict(result, state="error", ready=False, title="数据库连接失败", detail=detail)

    def ocr(self):
        result = {"name": "Tesseract OCR", "required_for": "仅成绩图片识别", "docs_url": "https://tesseract-ocr.github.io/tessdoc/Installation.html"}
        command = self.settings.tesseract_cmd
        executable = str(Path(command)) if Path(command).is_file() else shutil.which(command)
        if not executable:
            return dict(result, state="missing", ready=False, title="OCR 未安装或路径未配置", detail="安装 Tesseract，加入 PATH 或设置 TESSERACT_CMD；文字录入与志愿推荐仍可使用。")
        try:
            version = subprocess.run([executable, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=4)
            languages = subprocess.run([executable, "--list-langs"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=4)
            if version.returncode or languages.returncode or "tesseract" not in (version.stdout + version.stderr).lower():
                raise ValueError("unavailable")
            installed = set((languages.stdout + "\n" + languages.stderr).splitlines())
            missing = {"chi_sim", "eng"} - installed
            if missing:
                return dict(result, state="warning", ready=False, title="OCR 已安装，语言包不完整", detail="请将 " + "、".join(sorted(missing)) + ".traineddata 安装到 Tesseract 的 tessdata 目录，再重新检查。")
            return dict(result, state="ok", ready=True, title="OCR 与中英文语言包可用", detail="已检测可执行程序、chi_sim 和 eng；可进行成绩图片识别，识别结果仍需人工核对。")
        except Exception:
            return dict(result, state="error", ready=False, title="OCR 启动失败", detail="请检查 TESSERACT_CMD、执行权限和 tessdata 目录，修改配置后重启服务。文字录入仍可使用。")

    def model(self):
        base = {"name": "DeepSeek API Key", "required_for": "AI 问答及分析", "docs_url": "https://platform.deepseek.com/", "configured": bool(self.settings.deepseek_api_key.strip())}
        if not base["configured"]:
            return dict(base, state="missing", verified=False, title="API Key 未填写", detail="在本机 .env 填写 DEEPSEEK_API_KEY 后重启服务。推荐与图谱查询无需模型 Key；请勿将 Key 提交到 Git。")
        if self._model and time.monotonic() - self._model_checked < 300:
            return dict(base, **self._model)
        return dict(base, state="warning", verified=False, title="API Key 已填写，尚未验证", detail="点击“验证 API 连接”检查认证与所配置模型是否可见；不会发送成绩或调用文本生成。")

    def verify_model(self):
        with self._lock:
            if not self.settings.deepseek_api_key.strip():
                return self.model()
            if self._model and time.monotonic() - self._model_checked < 30:
                return self.model()
            try:
                request = Request(self.settings.deepseek_base_url.rstrip("/") + "/models", headers={"Authorization": "Bearer " + self.settings.deepseek_api_key, "Accept": "application/json"})
                with urlopen(request, timeout=10) as response:
                    payload = json.loads(response.read(1024 * 1024))
                models = {item["id"] for item in payload["data"]}
                if self.settings.deepseek_model in models:
                    result = dict(state="ok", verified=True, title="API 认证成功，模型可见", detail="已验证所配置模型的访问权限；实际生成还取决于账户额度与服务状态。未发送成绩或生成文本。")
                else:
                    result = dict(state="warning", verified=False, title="API 认证成功，模型配置不匹配", detail="所配置 DEEPSEEK_MODEL 不在可用模型列表中，请核对官方模型 ID 并重启服务。")
            except HTTPError as exc:
                detail = "API Key 无效或无访问权限，请在平台检查 Key 后更新本机配置。" if exc.code in (401, 403) else "模型平台返回异常，请检查账户状态、API 地址或稍后重试。"
                result = dict(state="error", verified=False, title="API 验证失败", detail=detail)
            except Exception:
                result = dict(state="error", verified=False, title="API 连接失败", detail="请检查网络、DEEPSEEK_BASE_URL 和模型平台状态；此结果不能证明 Key 无效。")
            self._model, self._model_checked = result, time.monotonic()
            return self.model()

    def status(self):
        with self._lock:
            if not self._cache or time.monotonic() - self._checked >= 30:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    database, ocr = pool.submit(self.neo4j), pool.submit(self.ocr)
                    self._cache = {"neo4j": database.result(), "ocr": ocr.result()}
                self._checked = time.monotonic()
            return {"data_ready": self._cache["neo4j"]["ready"], "components": dict(self._cache, deepseek=self.model()), "cache_seconds": 30,
                    "hint": "配置从服务端读取；修改 .env 后重启服务。OCR 为可选项，Ollama 不参与当前云端主流程。"}
