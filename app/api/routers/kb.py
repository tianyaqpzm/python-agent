import os
import logging
import json
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.security import CurrentUser, get_current_user
from app.services.kb.data_prep import DataPreparationService
from app.services.kb.indexing import IndexingService
from app.services.kb.retrieval import RetrievalService
from app.services.kb.generation import GenerationService

router = APIRouter()
logger = logging.getLogger(__name__)

# --- Dependencies / Service Locators ---

def get_data_prep_service() -> DataPreparationService:
    return DataPreparationService()

def get_indexing_service() -> IndexingService:
    return IndexingService()

def get_retrieval_service() -> RetrievalService:
    return RetrievalService()

def get_generation_service() -> GenerationService:
    return GenerationService()

# --- Schemas ---

class IngestRequest(BaseModel):
    file_path: str = Field(..., description="物理/挂载磁盘下的绝对路径文件")
    category: str = Field(..., description="分类/类别标签,如 'policy', 'recipe'.")
    tenant_id: str = Field(default="default", description="环境/租户隔离.")
    
    # --- 动态传入的 RAG 核心参数 ---
    # 1. Data Preparation
    chunk_size: Optional[int] = Field(default=None, description="文本分块大小")
    chunk_overlap: Optional[int] = Field(default=None, description="片段重叠字符数")
    separators: Optional[List[str]] = Field(default=None, description="文本切割偏好符号")
    
    # 2. Indexing & Retrieval
    embedding_model: Optional[str] = Field(default=None, description="Embedding 模型")
    vector_store: Optional[str] = Field(default=None, description="向量数据库类型")
    top_k: Optional[int] = Field(default=5, description="检索结果数")
    score_threshold: Optional[float] = Field(default=None, description="评分阈值")
    enable_hybrid_search: Optional[bool] = Field(default=True, description="是否启用混合检索")
    alpha_weight: Optional[float] = Field(default=0.5, description="权重比例")
    
    # 3. Generation
    generation_model: Optional[str] = Field(default=None, description="生成模型名称")
    temperature: Optional[float] = Field(default=0.7, description="采样温度")
    max_tokens: Optional[int] = Field(default=1000, description="最大生成长度")
    system_prompt: Optional[str] = Field(default=None, description="系统提示词")
    
    # 4. Evaluation
    enable_evaluation: bool = Field(default=False, description="是否开启自动评估")
    evaluation_metrics: Optional[List[str]] = Field(default=None, description="评估指标列表")

class RetrievalRequest(BaseModel):
    query: str = Field(..., description="要查询的问题或关键词")
    category: Optional[str] = Field(default=None, description="需要过滤所属知识的类型/分类")
    tenant_id: str = Field(default="default", description="分片所属环境/租户")
    top_k: int = Field(default=5, ge=1, le=20, description="最大返回片段数")

class RetrievalResponse(BaseModel):
    items: List[Dict[str, Any]]
    total_found: int

class AskRequest(BaseModel):
    query: str = Field(..., description="用户提问的内容")
    category: Optional[str] = Field(default=None, description="知识库隔离分区")
    tenant_id: str = Field(default="default", description="租户分区")
    stream: bool = Field(default=True, description="是否流式输出")

# --- Endpoints ---

@router.post("/documents/ingest", summary="本地文件入库分析及索引", status_code=status.HTTP_201_CREATED)
async def ingest_document(
    req: IngestRequest,
    prep_svc: DataPreparationService = Depends(get_data_prep_service),
    idx_svc: IndexingService = Depends(get_indexing_service),
    _: CurrentUser = Depends(get_current_user),
):
    """
    负责接收存储路径、调用智能提取与向量建立索引落盘 pgvector。
    Java端仅传递本地共享磁盘可读的绝对路径进来。
    """
    if not os.path.exists(req.file_path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error_code": "DEP_0100", "error_msg": f"参数异常，文件路径未找到或引擎无权访问: {req.file_path}"}
        )
    
    try:
        # 1. 解析和分块
        try:
            extra_configs = {
                "chunk_size": req.chunk_size,
                "chunk_overlap": req.chunk_overlap,
                "separators": req.separators
            }
            chunks = prep_svc.load_and_split(req.file_path, category=req.category, tenant_id=req.tenant_id, extra_metadata=extra_configs)
        except RuntimeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "DEP_0501", "error_msg": f"文件拆解错误: {e}"}
            )
            
        # 2. 存入大模型进行 Embed 后，刷入矢量持久库
        try:
            inserted_count = await idx_svc.build_and_save_index(
                chunks, 
                embedding_model=req.embedding_model,
                vector_store=req.vector_store
            )
        except RuntimeError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_code": "DEP_0502", "error_msg": f"向量化回写错误: {e}"}
            )
            
        # 3. 如果开启了评估，记录日志（后续可集成 RAGAS 等库）
        if req.enable_evaluation:
            logger.info(f"开启自动评估流程, 指标: {req.evaluation_metrics}")

        return {
            "status": "success",
            "message": f"成功解构、分段与向量化文件 [{os.path.basename(req.file_path)}].",
            "metrics": {
                "chunks_generated": len(chunks),
                "chunks_inserted": inserted_count,
                "evaluation_triggered": req.enable_evaluation
            }
        }
    except Exception as e:
        logger.error(f"知识库注入未知崩溃: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

@router.post("/retrieve", summary="提问搜索 (向量近似查询) 可单独由Java获取Chunks", response_model=RetrievalResponse)
async def retrieve_knowledge(
    req: RetrievalRequest,
    ret_svc: RetrievalService = Depends(get_retrieval_service),
    _: CurrentUser = Depends(get_current_user),
):
    """
    获取包含原文本分块(Chunk)以及评分的检索列表。如果Java仍需单独处理查询，可以用这个接口。
    """
    try:
        results = await ret_svc.search(
            query=req.query,
            category=req.category,
            tenant_id=req.tenant_id,
            top_k=req.top_k
        )
        return RetrievalResponse(
            items=results,
            total_found=len(results)
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ask", summary="知识搜索合并聊天集成回答接口")
async def ask_knowledge(
    req: AskRequest,
    ret_svc: RetrievalService = Depends(get_retrieval_service),
    gen_svc: GenerationService = Depends(get_generation_service),
    _: CurrentUser = Depends(get_current_user),
):
    """
    接收用户提问，先在向量库做过滤查询 (Retrieval)，随后用 LLM 做上下文润色并答复 (Generation)。
    返回格式可以是 Stream (SSE) 或者是普通 JSON，根据 stream 字段控制。
    """
    try:
        # 1. 召回
        context_docs = await ret_svc.search(
            query=req.query,
            category=req.category,
            tenant_id=req.tenant_id,
            top_k=5
        )
        
        # 2. 生成 (Stream vs Blocking)
        if req.stream:
            async def event_generator():
                try:
                    async for chunk in gen_svc.generate_answer_stream(req.query, context_docs, category=req.category):
                        # Pack stream in SSE format
                        yield f"data: {json.dumps({'content': chunk})}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    logger.error(f"KB Stream Error: {e}")
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                    
            return StreamingResponse(event_generator(), media_type="text/event-stream")
        else:
            final_answer = await gen_svc.generate_answer(req.query, context_docs, category=req.category)
            return {
                "query": req.query,
                "answer": final_answer,
                "source_count": len(context_docs)
            }
            
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
