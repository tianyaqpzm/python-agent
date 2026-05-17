import os
import uuid
import hashlib
import logging
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime

from sqlalchemy import text
from langchain_text_splitters import MarkdownHeaderTextSplitter

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.domain.models import TaskRecord, KnowledgeDocument
from app.infrastructure.repositories.knowledge_repository import SqlAlchemyKnowledgeRepository

logger = logging.getLogger(__name__)

class RecipeParser:
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

    @classmethod
    def parse_file(cls, file_path: Path, data_path: Path) -> Dict[str, Any]:
        """读取并解析单个文件，计算其Hash并提取元数据"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        file_hash = hashlib.md5(content.encode('utf-8')).hexdigest()
        dish_name = file_path.stem

        # 计算相对路径作为唯一标识
        try:
            relative_path = file_path.relative_to(data_path).as_posix()
        except Exception:
            relative_path = file_path.as_posix()

        # 匹配分类
        category = '其他'
        for key, val in cls.CATEGORY_MAPPING.items():
            if key in file_path.parts:
                category = val
                break

        # 匹配难度
        difficulty = '未知'
        if '★★★★★' in content:
            difficulty = '非常困难'
        elif '★★★★' in content:
            difficulty = '困难'
        elif '★★★' in content:
            difficulty = '中等'
        elif '★★' in content:
            difficulty = '简单'
        elif '★' in content:
            difficulty = '非常简单'

        return {
            "file_path": relative_path,
            "file_hash": file_hash,
            "dish_name": dish_name,
            "category": category,
            "difficulty": difficulty,
            "content": content
        }

    @classmethod
    def split_recipe(cls, content: str) -> List[str]:
        """将菜谱内容按 Markdown 结构分块"""
        headers_to_split_on = [
            ("#", "主标题"),
            ("##", "二级标题"),
            ("###", "三级标题")
        ]
        splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=headers_to_split_on,
            strip_headers=False
        )
        chunks = splitter.split_text(content)
        # 过滤掉内容为空的分块
        return [chunk.page_content for chunk in chunks if chunk.page_content and chunk.page_content.strip()]

class RecipeBuildService:
    _embeddings = None
    _lock = asyncio.Lock()

    @classmethod
    def get_embeddings(cls):
        """懒加载 HuggingFaceEmbeddings 单例"""
        if cls._embeddings is None:
            logger.info("🏗️ Initializing BAAI/bge-small-zh-v1.5 embedding model...")
            from app.core.llm_factory import LLMFactory
            cls._embeddings = LLMFactory.get_embedding_model(
                provider="huggingface",
                model_name="BAAI/bge-small-zh-v1.5",
                api_key="",
                base_url=""
            )
        return cls._embeddings

    @classmethod
    async def trigger_build(cls, task_id: str):
        """异步触发构建背景任务"""
        asyncio.create_task(cls._execute_build_task(task_id))

    @classmethod
    async def _execute_build_task(cls, task_id: str):
        logger.info(f"🚀 Starting background recipe KB build task: {task_id}")
        data_path_str = getattr(settings, "CONFIG_DATA_PATH", "/tmp/ai_knowledge_uploads/recipes")
        data_path = Path(data_path_str)

        # 1. 初始化数据库中的任务记录
        async with AsyncSessionLocal() as session:
            async with session.begin():
                # 检查任务是否已存在，如不存在则插入
                res = await session.execute(
                    text("SELECT id FROM ms_task_record WHERE id = :id"),
                    {"id": task_id}
                )
                if not res.fetchone():
                    await session.execute(
                        text("INSERT INTO ms_task_record (id, task_type, status, total_count, processed_count) "
                             "VALUES (:id, 'KNOWLEDGE_BUILD', 'RUNNING', 0, 0)"),
                        {"id": task_id}
                    )

        if not data_path.exists():
            err_msg = f"Data directory not found: {data_path_str}"
            logger.error(err_msg)
            await cls._update_task_status(task_id, "FAILED", error_message=err_msg)
            return

        try:
            # 2. 扫描所有 md 文件
            md_files = list(data_path.rglob("*.md"))
            total_files = len(md_files)
            logger.info(f"📂 Found {total_files} markdown files under {data_path_str}")

            # 3. 加载 embeddings 模型
            embeddings = cls.get_embeddings()

            # 4. 开始遍历处理，支持增量追加
            processed_count = 0
            for md_file in md_files:
                # 4.1 解析文件属性
                parsed = RecipeParser.parse_file(md_file, data_path)
                dish_name = parsed["dish_name"]
                file_path = parsed["file_path"]
                file_hash = parsed["file_hash"]

                # 忽略 readme/template/contributing 等特殊文件
                if dish_name.lower() in ["readme", "contributing", "template"]:
                    processed_count += 1
                    continue

                # 4.2 更新任务进度 (当前处理项)
                await cls._update_task_progress(task_id, total_files, processed_count, dish_name)

                # 4.3 数据库增量对比
                should_skip = False
                existing_doc_id = None
                
                async with AsyncSessionLocal() as session:
                    repo = SqlAlchemyKnowledgeRepository(session)
                    existing_doc = await repo.find_by_filepath(file_path)

                    if existing_doc:
                        if existing_doc.file_hash == file_hash:
                            # Hash 无变化，直接跳过分块与向量计算
                            logger.info(f"⏭️ Skipping {dish_name} (incremental - no changes)")
                            should_skip = True
                        else:
                            # Hash 变化，记录旧文档以进行删除
                            logger.info(f"♻️ Updating {dish_name} (hash changed)")
                            existing_doc_id = existing_doc.id

                if should_skip:
                    processed_count += 1
                    await cls._update_task_progress(task_id, total_files, processed_count, dish_name)
                    continue

                if existing_doc_id is not None:
                    async with AsyncSessionLocal() as session:
                        async with session.begin():
                            repo = SqlAlchemyKnowledgeRepository(session)
                            await repo.delete_by_id(existing_doc_id)

                # 4.4 插入新文档记录
                async with AsyncSessionLocal() as session:
                    async with session.begin():
                        repo = SqlAlchemyKnowledgeRepository(session)
                        new_doc = KnowledgeDocument(
                            file_path=file_path,
                            file_hash=file_hash,
                            doc_type="recipe",
                            title=dish_name,
                            category=parsed["category"],
                            metadata={"difficulty": parsed["difficulty"]}
                        )
                        new_doc_id = await repo.save_document(new_doc)

                # 4.5 对文档内容进行分块并向量化入库
                chunks = RecipeParser.split_recipe(parsed["content"])
                if chunks:
                    # 批量计算 embedding
                    embeddings_list = await embeddings.aembed_documents(chunks)

                    async with AsyncSessionLocal() as session:
                        async with session.begin():
                            repo = SqlAlchemyKnowledgeRepository(session)
                            await repo.save_chunks(new_doc_id, chunks, embeddings_list)

                processed_count += 1
                await cls._update_task_progress(task_id, total_files, processed_count, dish_name)

            # 5. 任务标记为 SUCCESS
            await cls._update_task_status(task_id, "SUCCESS")
            logger.info(f"🎉 Recipe KB build task completed successfully: {task_id}")

        except Exception as e:
            err_msg = f"Failed to build recipe KB: {str(e)}"
            logger.error(err_msg, exc_info=True)
            await cls._update_task_status(task_id, "FAILED", error_message=err_msg)

    @classmethod
    async def _update_task_progress(cls, task_id: str, total_count: int, processed_count: int, current_item: str):
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    text("UPDATE ms_task_record SET total_count = :total_count, processed_count = :processed_count, "
                         "current_item_name = :current_item, update_time = CURRENT_TIMESTAMP WHERE id = :id"),
                    {
                        "id": task_id,
                        "total_count": total_count,
                        "processed_count": processed_count,
                        "current_item": current_item
                    }
                )

    @classmethod
    async def _update_task_status(cls, task_id: str, status: str, error_message: Optional[str] = None):
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    text("UPDATE ms_task_record SET status = :status, error_message = :err, update_time = CURRENT_TIMESTAMP "
                         "WHERE id = :id"),
                    {
                        "id": task_id,
                        "status": status,
                        "err": error_message
                    }
                )
