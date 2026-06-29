"""
VMC850 文档解析器
按故障代码（MECH-001~004）切块，父子结构
"""

import re

from rag.parsers.base_parser import BaseParser


class VMCParser(BaseParser):
    def __init__(self, file_path):
        super().__init__("vmc850", file_path)

    def parse(self) -> list[dict]:
        self.load()
        chunks: list[dict] = []
        pattern = r"(?=^## 故障代码：MECH-\d+)"
        sections = re.split(pattern, self._raw_content, flags=re.MULTILINE)

        for section in sections:
            section = section.strip()
            if not section:
                continue

            code_match = re.match(r"## 故障代码：(MECH-\d+)", section)
            if not code_match:
                continue

            alarm_code = code_match.group(1)
            phenomenon = self._extract_field(section, "现象说明")
            cause = self._extract_field(section, "可能原因")
            images = self.extract_images(section)

            parent_id = self.generate_chunk_id("vmc850", alarm_code)

            # 父块
            chunks.append({
                "chunk_id": parent_id,
                "parent_id": None,
                "chunk_type": "parent",
                "source": "vmc850",
                "text": section,
                "section_title": f"{alarm_code} 故障排除",
                "alarm_code": alarm_code,
                "level1_tag": None,
                "level2_category": None,
                "images": images,
            })

            # 子块: 现象说明
            if phenomenon:
                chunks.append({
                    "chunk_id": self.generate_chunk_id(parent_id, "phenomenon"),
                    "parent_id": parent_id,
                    "chunk_type": "child",
                    "source": "vmc850",
                    "text": phenomenon,
                    "section_title": f"{alarm_code} 现象说明",
                    "alarm_code": alarm_code,
                    "level1_tag": None,
                    "level2_category": None,
                    "images": [],
                })

            # 子块: 可能原因
            if cause:
                chunks.append({
                    "chunk_id": self.generate_chunk_id(parent_id, "cause"),
                    "parent_id": parent_id,
                    "chunk_type": "child",
                    "source": "vmc850",
                    "text": cause,
                    "section_title": f"{alarm_code} 可能原因",
                    "alarm_code": alarm_code,
                    "level1_tag": None,
                    "level2_category": None,
                    "images": [],
                })

        return chunks

    def _extract_field(self, text: str, field_name: str) -> str:
        pattern = rf"\*\*{field_name}[：:]\*\*\s*(.*?)(?=\n\*\*|\n## |\Z)"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""
