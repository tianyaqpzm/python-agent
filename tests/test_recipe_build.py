import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.kb.recipe_build_service import RecipeParser, RecipeBuildService

def test_recipe_parser_parse_file():
    # Setup temporary recipe file
    with tempfile.TemporaryDirectory() as tmpdir:
        data_path = Path(tmpdir)
        meat_dir = data_path / "meat_dish"
        meat_dir.mkdir()
        
        recipe_file = meat_dir / "宫保鸡丁.md"
        content = """# 宫保鸡丁
        难度：★★
        
        ## 食材
        鸡胸肉，花生米。
        
        ## 步骤
        1. 切丁炒熟。
        """
        with open(recipe_file, "w", encoding="utf-8") as f:
            f.write(content)
        
        # Execute parsing
        parsed = RecipeParser.parse_file(recipe_file, data_path)
        
        # Assertions
        assert parsed["dish_name"] == "宫保鸡丁"
        assert parsed["category"] == "荤菜"
        assert parsed["difficulty"] == "简单"
        assert "meat_dish/宫保鸡丁.md" in parsed["file_path"]
        assert parsed["file_hash"] is not None

def test_recipe_parser_split_recipe():
    content = """# 宫保鸡丁
    ## 食材
    鸡胸肉
    ## 步骤
    炒熟
    """
    chunks = RecipeParser.split_recipe(content)
    assert len(chunks) >= 2
    assert "食材" in chunks[0] or "宫保鸡丁" in chunks[0]

class MockAsyncSession:
    def __init__(self):
        self.execute = AsyncMock()
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass
        
    def begin(self):
        return self

@pytest.mark.asyncio
async def test_recipe_build_service_execute_task():
    # Instantiate MockAsyncSession
    mock_session = MockAsyncSession()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None  # Mock task not existing
    mock_session.execute.return_value = mock_result

    # Mock embeddings
    mock_embeddings = AsyncMock()
    mock_embeddings.aembed_documents.return_value = [[0.1, 0.2]]

    with patch("app.services.kb.recipe_build_service.AsyncSessionLocal", return_value=mock_session), \
         patch("app.services.kb.recipe_build_service.RecipeBuildService.get_embeddings", return_value=mock_embeddings), \
         tempfile.TemporaryDirectory() as tmpdir:
        
        data_path = Path(tmpdir)
        settings_mock = MagicMock()
        settings_mock.CONFIG_DATA_PATH = str(data_path)
        
        # Create a mock recipe file
        recipe_file = data_path / "test_recipe.md"
        with open(recipe_file, "w", encoding="utf-8") as f:
            f.write("# Test Recipe\n★★\n## Content\nHello World")

        with patch("app.services.kb.recipe_build_service.settings", settings_mock):
            # Trigger build task execution
            await RecipeBuildService._execute_build_task("task-123")
            
            # Check that task records and recipes were inserted
            assert mock_session.execute.call_count >= 3

