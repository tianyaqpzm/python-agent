import os
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from pathlib import Path
from langchain_core.documents import Document
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    CSVLoader
)
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.core.config import settings

logger = logging.getLogger(__name__)


class BaseDocumentProcessor(ABC):
    """
    文档处理器的抽象基类，使用**模板方法模式** (Template Method Pattern)。
    定义了文档核心入库的数据流清洗、转换骨架。
    """
    def __init__(self, chunk_size: int, chunk_overlap: int, separators: List[str] = None):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        
        # 预处理分隔符：支持转义符识别并强制加入 "" 兜底
        self.separators = self._prepare_separators(separators)
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=self.separators
        )

    def _prepare_separators(self, separators: List[str]) -> List[str]:
        """
        对传入的分隔符进行健壮性预处理
        """
        default_seps = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
        if not separators:
            return default_seps
            
        # 自动识别并转换字面量转义字符串 (如 "\\n" -> "\n")
        # 解决前端可能由于 JSON 序列化或配置不当传来的字面量斜杠问题
        mapping = {"\\n": "\n", "\\t": "\t", "\\r": "\r"}
        processed = []
        for s in separators:
            for k, v in mapping.items():
                s = s.replace(k, v)
            processed.append(s)
            
        # 强制包含 "" 以确保分块逻辑最终能按字符拆分，防止单块超限
        if "" not in processed:
            processed.append("")
        return processed

    def process(self, file_path: str, base_metadata: dict) -> List[Document]:
        """
        模板方法：规定文档处理的生命周期
        """
        logger.info(f"[{self.__class__.__name__}] 1.开始处理文档: {file_path}")
        logger.info(f"[{self.__class__.__name__}] 2.分块策略配置 -> Size: {self.chunk_size}, Overlap: {self.chunk_overlap}, Separators: {self.separators}")
        
        # 1. 挂载加载器并读取原始文档
        docs = self._load(file_path)
        
        # 2. 从原始文档扩展细粒度定制的元数据 (Hook 方法)
        for doc in docs:
            self._enhance_metadata(doc)
            
        # 3. 按业务所需的智能策略分块
        chunks = self._split(docs)
        
        # 4. 包裹传递来的公共系统属性（防篡改）
        for chunk in chunks:
            chunk.metadata.update(base_metadata)
            
        logger.info(f"[{self.__class__.__name__}] 完成处理, 共生成 {len(chunks)} 个片段。")
        return chunks


    @abstractmethod
    def _load(self, file_path: str) -> List[Document]:
        """【强制实现】抽象读取方法，不同场景可能需要特殊加载库"""
        pass

    def _enhance_metadata(self, doc: Document) -> None:
        """【可选覆盖】钩子方法：用来额外从内容提取例如标签或层级"""
        pass

    def _split(self, docs: List[Document]) -> List[Document]:
        """【可选覆盖】默认使用 RecursiveCharacterTextSplitter 进行基础拆解"""
        return self.text_splitter.split_documents(docs)


class DefaultDocumentProcessor(BaseDocumentProcessor):
    """标准的文档处理器，作为所有知识库分类兜底的通用逻辑"""
    def _load(self, file_path: str) -> List[Document]:
        ext = file_path.lower().split('.')[-1]
        try:
            if ext == "pdf":
                loader = PyPDFLoader(file_path)
            elif ext == "csv":
                loader = CSVLoader(file_path)
            else:
                loader = TextLoader(file_path, encoding='utf-8')
            return loader.load()
        except Exception as e:
            logger.error(f"通用模型解析文档 {file_path} 时出错: {e}")
            raise RuntimeError(f"通用模型无法解析该文档: {e}")


class HowToCookDocumentProcessor(BaseDocumentProcessor):
    """专门针对做饭指南 HowToCook (大量 Markdown 食谱) 的处理器"""
    
    CATEGORY_MAPPING = {
        'meat_dish': '荤菜',
        'vegetable_dish': '素菜',
        'soup': '汤品',
        'dessert': '甜品',
        'breakfast': '早餐',
        'staple': '主食',
        'aquatic': '水产',
        'condiment': '调料',
        'drink': '饮品'
    }

    def _load(self, file_path: str) -> List[Document]:
        # 对于这个分类，我们通常预期全是 Markdown 和 TXT
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return [Document(page_content=content, metadata={"source": file_path})]
        except Exception as e:
            logger.error(f"HowToCook 解析文档 {file_path} 时出错: {e}")
            raise RuntimeError(f"HowToCook 解析该 Markdown 错误: {e}")

    def _enhance_metadata(self, doc: Document) -> None:
        file_path = Path(doc.metadata.get('source', ''))
        path_parts = file_path.parts

        # 挂载特别分类
        for key, value in self.CATEGORY_MAPPING.items():
            if key in path_parts:
                doc.metadata['recipe_category'] = value
                break

        doc.metadata['dish_name'] = file_path.stem

        # 星级难度解析
        content = doc.page_content
        if '★★★★★' in content:
            doc.metadata['difficulty'] = '非常困难'
        elif '★★★★' in content:
            doc.metadata['difficulty'] = '困难'
        elif '★★★' in content:
            doc.metadata['difficulty'] = '中等'
        elif '★★' in content:
            doc.metadata['difficulty'] = '简单'
        elif '★' in content:
            doc.metadata['difficulty'] = '非常简单'
        else:
            doc.metadata['difficulty'] = '未知'

    def _split(self, docs: List[Document]) -> List[Document]:
        # 因为我们覆写了 Load，这里只会接到一个巨大的 parent Document
        from langchain_text_splitters import MarkdownHeaderTextSplitter
        headers_to_split_on = [
            ("#", "主标题"),
            ("##", "二级标题"),
            ("###", "三级标题")
        ]
        markdown_splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on,
            strip_headers=False
        )
        
        all_chunks = []
        for doc in docs:
            # 第一阶段结构性拆解
            md_chunks = markdown_splitter.split_text(doc.page_content)
            
            # 继承上文的 Metadata 并再次送入 Recursive 拦截器，保证分片不超限
            for chunk in md_chunks:
                chunk.metadata.update(doc.metadata)
            
            final_sub_chunks = self.text_splitter.split_documents(md_chunks)
            all_chunks.extend(final_sub_chunks)
            
        return all_chunks


class DataPreparationService:
    """
    策略/工厂路由：根据类别自动实例化出不同的解析策略/模板方法，分发处理。
    """
    def __init__(self):
        self.chunk_size = settings.KB_CHUNK_SIZE
        self.chunk_overlap = settings.KB_CHUNK_OVERLAP

    def load_and_split(self, file_path: str, category: str, tenant_id: str = "default", extra_metadata: Dict[str, Any] = None) -> List[Document]:
        """
        加载文档并自动路由智能分块。
        """
        base_metadata = {
            "category": category,
            "tenant_id": tenant_id,
            "source_file": os.path.basename(file_path),
            **(extra_metadata or {})
        }

        # 路由策略
        d_chunk_size = extra_metadata.get("chunk_size") if extra_metadata and extra_metadata.get("chunk_size") else self.chunk_size
        d_chunk_overlap = extra_metadata.get("chunk_overlap") if extra_metadata and extra_metadata.get("chunk_overlap") is not None else self.chunk_overlap
        d_separators = extra_metadata.get("separators") if extra_metadata and extra_metadata.get("separators") else None

        if category.lower() in ["howtocook", "recipe"]:
            processor = HowToCookDocumentProcessor(d_chunk_size, d_chunk_overlap, d_separators)
        else:
            processor = DefaultDocumentProcessor(d_chunk_size, d_chunk_overlap, d_separators)

        # 过滤掉特殊的控制字段，避免他们污染普通 metadata
        clean_metadata = {k: v for k, v in base_metadata.items() if k not in ["chunk_size", "chunk_overlap", "separators"]}
        return processor.process(file_path, clean_metadata)
