from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional
from urllib.request import Request, urlopen


class OllamaService:
    """Local DeepSeek via Ollama, used for Neo4j-related AI tasks."""

    def __init__(self, base_url: str, model: str, timeout: int = 90) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def configured(self) -> bool:
        return bool(self.base_url)

    def chat(self, question: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.configured():
            return {
                "source": "ollama",
                "configured": False,
                "answer": "未配置本地Ollama服务，请在 setting.yaml 中填写 ollama.base_url。",
            }

        prompt = self._build_prompt(question, context or {})
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是高考志愿推荐系统助手，请给出简洁、可执行建议。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "stream": False,
        }
        req = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            if not content:
                content = "本地模型返回为空，请稍后重试。"
            cleaned = self._normalize_for_display(content)
            return {
                "source": "ollama",
                "configured": True,
                "answer": cleaned,
                "raw_answer": content,
            }
        except Exception as exc:
            return {"source": "ollama", "configured": True, "answer": f"本地模型调用失败: {exc}"}

    @staticmethod
    def _build_prompt(question: str, context: Dict[str, Any]) -> str:
        if not context:
            return question
        ctx = json.dumps(context, ensure_ascii=False)
        return f"问题：{question}\n上下文：{ctx}\n请结合上下文给出建议。"

    @staticmethod
    def _normalize_for_display(text: str) -> str:
        t = (text or "").strip()
        if not t:
            return t
        t = re.sub(r"```[\w-]*\n?", "", t)
        t = t.replace("```", "")
        stripped = t.strip()
        if (stripped.startswith("{") and stripped.endswith("}")) or (
            stripped.startswith("[") and stripped.endswith("]")
        ):
            try:
                obj = json.loads(stripped)

                def flatten(prefix: str, val: Any, out: list[str]) -> None:
                    if isinstance(val, dict):
                        for k, v in val.items():
                            p = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
                            flatten(p, v, out)
                        return
                    if isinstance(val, list):
                        for i, v in enumerate(val, start=1):
                            p = f"{prefix}{i}" if prefix else str(i)
                            flatten(p, v, out)
                        return
                    out.append(f"{prefix}: {val}")

                lines: list[str] = []
                flatten("", obj, lines)
                t = "\n".join(lines)
            except Exception:
                pass
        t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.MULTILINE)
        t = re.sub(r"^\s*[-*_]{3,}\s*$", "", t, flags=re.MULTILINE)
        t = t.replace("**", "").replace("__", "")
        t = re.sub(r"^\s*[-*]\s+", "", t, flags=re.MULTILINE)
        t = re.sub(r"^\s*\d+\.\s+", "", t, flags=re.MULTILINE)
        t = re.sub(r"^\s*[\"']\s*$", "", t, flags=re.MULTILINE)
        t = re.sub(r"\n{3,}", "\n\n", t).strip()
        return t

    def query_institution_info_batch(self, institutions: list[dict]) -> Dict[str, Any]:
        if not institutions:
            return {"source": "ollama", "configured": self.configured(), "data": {}}

        if not self.configured():
            return {
                "source": "ollama",
                "configured": False,
                "data": {},
                "answer": "未配置本地Ollama服务",
            }

        names = [item["name"] for item in institutions]
        need_level = any(item.get("need_level") for item in institutions)
        need_nature = any(item.get("need_nature") for item in institutions)

        fields_desc = []
        if need_level:
            fields_desc.append('"level": "办学层次（本科 或 专科）"')
        if need_nature:
            fields_desc.append(
                '"nature": "办学性质（公办 或 民办 或 中外合作办学 或 内地与港澳台地区合作办学）"'
            )
        fields_str = "、".join(fields_desc) if fields_desc else "信息"

        prompt = (
            f"你是一个中国高等教育信息查询助手。请查询以下院校的官方信息，返回每所院校的{fields_str}。\n\n"
            "要求：\n"
            "1. 办学层次取值为：本科、专科\n"
            "2. 办学性质取值为：公办、民办、中外合作办学、内地与港澳台地区合作办学\n"
            "3. 优先使用学校官网信息，确保信息准确可信\n"
            "4. 如果无法确定某项信息，请填写\"未知\"\n"
            "5. 只返回JSON，不要任何其他内容\n\n"
            "请按以下JSON格式返回：\n"
            "{\n"
        )
        for name in names:
            fields = []
            if need_level:
                fields.append('"level": "本科或专科"')
            if need_nature:
                fields.append('"nature": "公办或民办等"')
            prompt += f'  "{name}": {{{", ".join(fields)}}},\n'
        prompt += "}\n\n需要查询的院校列表：\n"
        for i, name in enumerate(names, 1):
            prompt += f"{i}. {name}\n"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是中国高等教育信息查询助手，请严格按JSON格式返回查询结果。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "stream": False,
        }
        req = Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            parsed = self._parse_institution_json(content, names)
            return {
                "source": "ollama",
                "configured": True,
                "data": parsed,
                "raw_answer": content,
            }
        except Exception as exc:
            return {
                "source": "ollama",
                "configured": True,
                "data": {},
                "answer": f"本地模型调用失败: {exc}",
            }

    @staticmethod
    def _parse_institution_json(content: str, names: list[str]) -> Dict[str, Dict[str, str]]:
        if not content:
            return {}
        json_str = content.strip()
        code_block_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
        if code_block_match:
            json_str = code_block_match.group(1).strip()
        brace_start = json_str.find("{")
        brace_end = json_str.rfind("}")
        if brace_start != -1 and brace_end != -1:
            json_str = json_str[brace_start : brace_end + 1]
        try:
            raw = json.loads(json_str)
        except json.JSONDecodeError:
            return {}
        parsed: Dict[str, Dict[str, str]] = {}
        for name in names:
            if name in raw and isinstance(raw[name], dict):
                entry = raw[name]
                parsed[name] = {
                    "level": str(entry.get("level", "")).strip() if entry.get("level") else "",
                    "nature": str(entry.get("nature", "")).strip() if entry.get("nature") else "",
                }
            else:
                for key, value in raw.items():
                    if isinstance(value, dict) and (name in key or key in name):
                        parsed[name] = {
                            "level": str(value.get("level", "")).strip() if value.get("level") else "",
                            "nature": str(value.get("nature", "")).strip() if value.get("nature") else "",
                        }
                        break
                if name not in parsed:
                    parsed[name] = {"level": "", "nature": ""}
        return parsed
