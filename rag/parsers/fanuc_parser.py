"""
Fanuc 文档解析器
一级 (## N.) → 元数据标签
二级 (## N.M) → 分类过滤
三级 (### 具体内容) → 父块
子块 → 报警描述/排除方法
"""

import re

from rag.parsers.base_parser import BaseParser


class FanucParser(BaseParser):
    RE_LEVEL1 = re.compile(r"^## (\d+)\.\s+(.+?)(?:\.\.\d+)?$", re.MULTILINE)
    RE_LEVEL2 = re.compile(r"^## (\d+\.\d+)\s+(.+?)(?:\.\.\d+)?$", re.MULTILINE)
    RE_ALARM_CODE = re.compile(r"(?:SV|OT|PS|AL|OH|DS|SR|MC|SP|EX)\d{3,4}")

    def __init__(self, file_path):
        super().__init__("fanuc", file_path)

    def parse(self) -> list[dict]:
        self.load()
        self._level1_map: dict[str, str] = {}
        self._level2_map: dict[str, str] = {}

        for m in self.RE_LEVEL1.finditer(self._raw_content):
            self._level1_map[m.group(1)] = m.group(2).strip()
        for m in self.RE_LEVEL2.finditer(self._raw_content):
            self._level2_map[m.group(1)] = m.group(2).strip()

        chunks: list[dict] = []
        level2_sections = self._split_by_level2()

        for section_num, section_title, section_content in level2_sections:
            level1_tag = self._get_level1_tag(section_num)
            level2_category = f"{section_num} {section_title}"
            parent_chunks = self._split_into_parent_chunks(
                section_content, level1_tag, level2_category
            )
            chunks.extend(parent_chunks)

        return chunks

    def _get_level1_tag(self, section_num: str) -> str:
        level1_num = section_num.split(".")[0]
        tag = self._level1_map.get(level1_num, "")
        return f"{level1_num}.{tag}" if tag else level1_num

    def _split_by_level2(self) -> list[tuple[str, str, str]]:
        results = []
        matches = list(self.RE_LEVEL2.finditer(self._raw_content))
        for i, match in enumerate(matches):
            section_num = match.group(1)
            section_title = match.group(2).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(self._raw_content)
            content = self._raw_content[start:end].strip()
            if content:
                results.append((section_num, section_title, content))
        return results

    def _split_into_parent_chunks(
        self, content: str, level1_tag: str, level2_category: str
    ) -> list[dict]:
        chunks: list[dict] = []
        sub_sections = re.split(r"(?=^### )", content, flags=re.MULTILINE)

        for sub_section in sub_sections:
            sub_section = sub_section.strip()
            if not sub_section or len(sub_section) < 50:
                continue

            title_match = re.match(r"###\s+(.+)", sub_section)
            section_title = title_match.group(1).strip() if title_match else "未命名章节"

            alarm_codes = self.RE_ALARM_CODE.findall(sub_section)
            alarm_code = alarm_codes[0] if alarm_codes else None
            images = self.extract_images(sub_section)

            parent_id = self.generate_chunk_id(
                "fanuc", level2_category.replace(" ", "_"), len(chunks)
            )

            # 父块
            chunks.append({
                "chunk_id": parent_id,
                "parent_id": None,
                "chunk_type": "parent",
                "source": "fanuc",
                "text": sub_section,
                "section_title": section_title,
                "alarm_code": alarm_code,
                "level1_tag": level1_tag,
                "level2_category": level2_category,
                "images": images,
            })

            # 子块
            child_texts = self._extract_child_texts(sub_section)
            for child_label, child_text in child_texts:
                chunks.append({
                    "chunk_id": self.generate_chunk_id(parent_id, child_label),
                    "parent_id": parent_id,
                    "chunk_type": "child",
                    "source": "fanuc",
                    "text": child_text,
                    "section_title": f"{section_title} - {child_label}",
                    "alarm_code": alarm_code,
                    "level1_tag": level1_tag,
                    "level2_category": level2_category,
                    "images": [],
                })

        return chunks

    def _extract_child_texts(self, text: str) -> list[tuple[str, str]]:
        children = []
        desc_match = re.search(
            r"(?:说明|现象|故障内容)[：:]\s*(.*?)(?=(?:反应|排除|处理|参数)\s*[：:]|\Z)",
            text, re.DOTALL,
        )
        if desc_match and len(desc_match.group(1).strip()) > 10:
            children.append(("description", desc_match.group(1).strip()))

        sol_match = re.search(
            r"(?:排除方法|处理办法)[：:]\s*(.*?)(?=(?:程序继续|备注|注意)\s*[：:]|\Z)",
            text, re.DOTALL,
        )
        if sol_match and len(sol_match.group(1).strip()) > 10:
            children.append(("solution", sol_match.group(1).strip()))

        if not children:
            clean = self.clean_text(text)[:200]
            if len(clean) > 20:
                children.append(("summary", clean))

        return children
