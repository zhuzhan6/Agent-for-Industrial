"""
文档解析器基类
"""

import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BaseParser(ABC):
    """文档解析器抽象基类"""

    def __init__(self, source: str, file_path: Path):
        self.source = source
        self.file_path = file_path
        self._raw_content: str = ""

    def load(self) -> str:
        if not self.file_path.exists():
            raise FileNotFoundError(f"文件不存在: {self.file_path}")
        self._raw_content = self.file_path.read_text(encoding="utf-8")
        return self._raw_content

    @abstractmethod
    def parse(self) -> list[dict]:
        """
        解析文档，返回分块列表
        每个分块: {
            "chunk_id": str,
            "parent_id": str | None,
            "chunk_type": "parent" | "child",
            "source": str,
            "text": str,
            "section_title": str,
            "alarm_code": str | None,
            "level1_tag": str | None,
            "level2_category": str | None,
            "images": list[str],
        }
        """
        ...

    def extract_images(self, text: str) -> list[str]:
        pattern = r"!\[.*?\]\((images/[^)]+)\)"
        return re.findall(pattern, text)

    def clean_text(self, text: str) -> str:
        text = re.sub(r"!\[.*?\]\(images/[^)]+\)", "", text)
        text = re.sub(r"<details>.*?</details>", "", text, flags=re.DOTALL)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def generate_chunk_id(self, *parts) -> str:
        return "_".join(str(p) for p in parts)
