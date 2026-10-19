from __future__ import annotations

import base64
import json
from typing import Any, Dict, List
from urllib.request import Request, urlopen


class Neo4jHttpClient:
    def __init__(self, base_url: str, username: str, password: str, database: str = "neo4j", timeout: int = 60) -> None:
        self.timeout = timeout
        self.url = f"{base_url.rstrip('/')}/db/{database}/tx/commit"
        token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("utf-8")
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {token}",
        }

    def run(self, statement: str, parameters: Dict[str, Any] | None = None) -> Dict[str, Any]:
        payload = {
            "statements": [
                {
                    "statement": statement,
                    "parameters": parameters or {},
                }
            ]
        }
        req = Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=self.headers,
        )
        with urlopen(req, timeout=self.timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if result.get("errors"):
            raise RuntimeError(result["errors"][0]["message"])
        return result

    def run_rows(self, statement: str, parameters: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
        result = self.run(statement, parameters)
        cols = result["results"][0]["columns"]
        rows = result["results"][0]["data"]
        output: List[Dict[str, Any]] = []
        for item in rows:
            output.append(dict(zip(cols, item["row"])))
        return output
