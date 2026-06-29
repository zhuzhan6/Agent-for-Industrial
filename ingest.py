"""
数据导入脚本
解析文档 → LlamaIndex 向量化 → 入库 Qdrant
按品牌建立不同的 collection
"""

import logging
import sys

from config.settings import settings
from rag.index import build_index, build_all_indices
from rag.bm25_retriever import build_bm25_index
from rag.parsers.fanuc_parser import FanucParser
from rag.parsers.siemens_parser import SiemensParser
from rag.parsers.vmc_parser import VMCParser
from llama_index.core.schema import TextNode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _chunks_to_nodes(chunks: list[dict]) -> list[TextNode]:
    """将分块转换为 TextNode（用于 BM25 索引）"""
    nodes = []
    for chunk in chunks:
        if chunk["chunk_type"] == "child":  # 只索引子块
            node = TextNode(
                text=chunk["text"],
                id_=chunk["chunk_id"],
                metadata={
                    "source": chunk["source"],
                    "section_title": chunk.get("section_title", ""),
                    "alarm_code": chunk.get("alarm_code", ""),
                },
            )
            nodes.append(node)
    return nodes


def run_ingest(source: str | None = None, force_rebuild: bool = False) -> str:
    """执行数据导入（按品牌分collection）"""
    all_parsers = {
        "fanuc": FanucParser(settings.DATA_DIR / settings.SOURCE_FILES["fanuc"]),
        "siemens": SiemensParser(settings.DATA_DIR / settings.SOURCE_FILES["siemens"]),
        "vmc850": VMCParser(settings.DATA_DIR / settings.SOURCE_FILES["vmc850"]),
    }

    if source and source in all_parsers:
        parsers = {source: all_parsers[source]}
    else:
        parsers = all_parsers

    # 按品牌解析文档
    chunks_by_source = {}
    total_chunks = 0
    for name, parser in parsers.items():
        logger.info(f"解析 {name}...")
        chunks = parser.parse()
        logger.info(f"  → {len(chunks)} 个分块")
        chunks_by_source[name] = chunks
        total_chunks += len(chunks)

    if total_chunks == 0:
        return "未生成任何分块"

    # 按品牌构建向量索引
    logger.info(f"开始构建向量索引，共 {total_chunks} 个分块...")
    for source_name, chunks in chunks_by_source.items():
        logger.info(f"构建 {source_name} 向量索引...")
        build_index(chunks, source_name, force_rebuild=force_rebuild)

    # 构建 BM25 索引
    logger.info("构建 BM25 索引...")
    for source_name, chunks in chunks_by_source.items():
        nodes = _chunks_to_nodes(chunks)
        build_bm25_index(source_name, nodes)

    result = f"导入完成，共 {total_chunks} 个分块已入库，已按品牌分 collection"
    logger.info(result)
    return result


if __name__ == "__main__":
    force = "--force" in sys.argv
    source_arg = None
    for arg in sys.argv[1:]:
        if arg in ("fanuc", "siemens", "vmc850"):
            source_arg = arg

    run_ingest(source=source_arg, force_rebuild=force)
