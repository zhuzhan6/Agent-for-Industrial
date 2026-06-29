"""
Siemens 840D 文档解析器
按报警号切块，父子结构
"""

import re

from rag.parsers.base_parser import BaseParser


class SiemensParser(BaseParser):
    def __init__(self, file_path):
        super().__init__("siemens", file_path)

    def parse(self) -> list[dict]:
        self.load()
        chunks: list[dict] = []
        pattern = r"(?=^#{1,3}\s+\d{3,5}\s)"
        sections = re.split(pattern, self._raw_content, flags=re.MULTILINE)

        for section in sections:
            section = section.strip()
            if not section:
                continue

            code_match = re.match(r"#{1,3}\s+(\d{3,5})\s", section)
            if not code_match:
                continue

            alarm_code = code_match.group(1)
            title_match = re.match(r"#{1,3}\s+\d{3,5}\s*(.*)", section)
            section_title = title_match.group(1).strip() if title_match else ""
            description = self._extract_field(section, "说明")
            reaction = self._extract_field(section, "反应")
            images = self.extract_images(section)

            parent_id = self.generate_chunk_id("siemens", alarm_code)

            # 父块
            chunks.append({
                "chunk_id": parent_id,
                "parent_id": None,
                "chunk_type": "parent",
                "source": "siemens",
                "text": section,
                "section_title": f"{alarm_code} {section_title}",
                "alarm_code": alarm_code,
                "level1_tag": None,
                "level2_category": None,
                "images": images,
            })

            # 子块: 说明
            if description:
                chunks.append({
                    "chunk_id": self.generate_chunk_id(parent_id, "desc"),
                    "parent_id": parent_id,
                    "chunk_type": "child",
                    "source": "siemens",
                    "text": description,
                    "section_title": f"{alarm_code} 说明",
                    "alarm_code": alarm_code,
                    "level1_tag": None,
                    "level2_category": None,
                    "images": [],
                })

            # 子块: 反应
            if reaction:
                chunks.append({
                    "chunk_id": self.generate_chunk_id(parent_id, "reaction"),
                    "parent_id": parent_id,
                    "chunk_type": "child",
                    "source": "siemens",
                    "text": reaction,
                    "section_title": f"{alarm_code} 反应",
                    "alarm_code": alarm_code,
                    "level1_tag": None,
                    "level2_category": None,
                    "images": [],
                })

        return chunks

    def _extract_field(self, text: str, field_name: str) -> str:
        pattern = rf"{field_name}[：:]\s*(.*?)(?=(?:反应|排除方法|程序继续|参数)[：:]|\n---|\n## |\Z)"
        match = re.search(pattern, text, re.DOTALL)
        return match.group(1).strip() if match else ""
