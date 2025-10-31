"""
Task Agent Tools - Real implementations
Tools for catalog access, knowledge base access, and code execution
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from autogen_core.code_executor import CodeBlock
from autogen_core.tools import FunctionTool
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor
from typing_extensions import Annotated

logger = logging.getLogger(__name__)


# TODO write function for FunctionTool
def todo_write_function(
    workspace_path: Annotated[str, "Workspace path where TODO file will be stored"],
    merge: Annotated[bool, "Whether to merge with existing todos (default False)"] = False,
    todos: Annotated[str, "JSON string of todo items with 'id', 'content', 'status' fields"] = "[]"
) -> str:
    """
    Write TODO list for task tracking
    
    Args:
        workspace_path: Workspace path where TODO file will be stored
        merge: Whether to merge with existing todos
        todos: JSON string of todo items with 'id', 'content', 'status' fields
    
    Returns:
        JSON string with success status and message
    """
    try:
        import json
        from pathlib import Path
        from control_plane_v2.phase_2.todo_models import TodoItem, TodoList, TodoWriteResponse
        from pydantic import ValidationError
        
        # Parse todos from JSON string and validate with Pydantic
        if isinstance(todos, str):
            todos_data = json.loads(todos)
        elif isinstance(todos, list):
            todos_data = todos
        else:
            raise ValueError(f"todos must be a JSON string or list, got {type(todos)}")
        
        # Validate with Pydantic
        try:
            new_todos = [TodoItem(**t) if isinstance(t, dict) else t for t in todos_data]
        except ValidationError as e:
            raise ValueError(f"Invalid TODO format: {e}")
        
        todo_file = Path(workspace_path) / "worker_todos.json"
        
        # Load existing TODOs if merging
        existing_todo_list = None
        if merge and todo_file.exists():
            with open(todo_file, 'r') as f:
                existing_data = json.load(f)
                existing_todo_list = TodoList(**existing_data)
        
        # Merge or replace
        if existing_todo_list and merge:
            # Create a dict of existing TODOs by ID
            existing_dict = {t.id: t for t in existing_todo_list.todos}
            # Update with new TODOs
            for new_todo in new_todos:
                if new_todo.id in existing_dict:
                    # Update existing TODO (preserve content if not provided)
                    existing_todo = existing_dict[new_todo.id]
                    if not new_todo.content and existing_todo.content:
                        new_todo.content = existing_todo.content
                existing_dict[new_todo.id] = new_todo
            # Create final list
            final_todos = list(existing_dict.values())
        else:
            final_todos = new_todos
        
        # Create TodoList and write
        todo_list = TodoList(todos=final_todos)
        with open(todo_file, 'w') as f:
            f.write(todo_list.model_dump_json(indent=2))
        
        # Return response
        response = TodoWriteResponse(
            success=True,
            message=f"TODO list updated with {len(new_todos)} items",
            todos_count=len(final_todos)
        )
        return response.model_dump_json()
    except Exception as e:
        from control_plane_v2.phase_2.todo_models import TodoWriteResponse
        response = TodoWriteResponse(
            success=False,
            message=f"Error: {str(e)}",
            todos_count=0
        )
        return response.model_dump_json()


# Directory scanning function for FunctionTool
async def scan_directory(
    base_path: Annotated[str, "Base directory path to scan from"],
    max_depth: Annotated[int, "Maximum depth to scan (default 3)"] = 3,
    include_files: Annotated[bool, "Include files in results (default True)"] = True,
    include_dirs: Annotated[bool, "Include directories in results (default True)"] = True,
    file_extensions: Annotated[Optional[str], "Comma-separated file extensions to filter (e.g., '.py,.json')"] = None
) -> Dict[str, Any]:
    """
    Scan a directory and return its structure.
    
    Args:
        base_path: Base directory path to start scanning from
        max_depth: Maximum depth to scan (default 3)
        include_files: Include files in results
        include_dirs: Include directories in results
        file_extensions: Filter by file extensions (comma-separated, e.g., '.py,.json')
    
    Returns:
        Dictionary with directory structure and file information
    """
    try:
        base = Path(base_path)
        if not base.exists():
            return {
                "success": False,
                "error": f"Path does not exist: {base_path}"
            }
        
        if not base.is_dir():
            return {
                "success": False,
                "error": f"Path is not a directory: {base_path}"
            }
        
        # Parse file extensions filter
        extensions = None
        if file_extensions:
            extensions = [ext.strip() for ext in file_extensions.split(',')]
        
        # Scan directory
        results = {
            "base_path": str(base.absolute()),
            "files": [],
            "directories": [],
            "total_files": 0,
            "total_dirs": 0
        }
        
        def scan_recursive(path: Path, current_depth: int):
            if current_depth > max_depth:
                return
            
            try:
                for item in path.iterdir():
                    # Skip hidden files/dirs
                    if item.name.startswith('.'):
                        continue
                    
                    if item.is_file() and include_files:
                        # Check extension filter
                        if extensions and item.suffix not in extensions:
                            continue
                        
                        results["files"].append({
                            "name": item.name,
                            "path": str(item.relative_to(base)),
                            "absolute_path": str(item.absolute()),
                            "size": item.stat().st_size,
                            "extension": item.suffix
                        })
                        results["total_files"] += 1
                    
                    elif item.is_dir() and include_dirs:
                        results["directories"].append({
                            "name": item.name,
                            "path": str(item.relative_to(base)),
                            "absolute_path": str(item.absolute())
                        })
                        results["total_dirs"] += 1
                        
                        # Recurse into subdirectory
                        scan_recursive(item, current_depth + 1)
            
            except PermissionError:
                logger.warning(f"Permission denied: {path}")
            except Exception as e:
                logger.error(f"Error scanning {path}: {e}")
        
        scan_recursive(base, 0)
        results["success"] = True
        return results
    
    except Exception as e:
        logger.error(f"Directory scan error: {e}")
        return {
            "success": False,
            "error": str(e)
        }


class TaskAgentTools:
    """Real tool implementations for task agents"""
    
    def __init__(self, workspace_path: Path, catalog, vector_store):
        self.workspace_path = workspace_path
        self.catalog = catalog
        self.vector_store = vector_store
        self.code_executor = LocalCommandLineCodeExecutor(
            work_dir=str(workspace_path),
            timeout=1800  # 30 minutes for code execution
        )
        
        # Create FunctionTool for directory scanning
        self.scan_directory_tool = FunctionTool(
            scan_directory,
            description="Scan a directory structure to discover files and subdirectories. Useful for exploring the workspace or finding specific files."
        )
        
        # Create FunctionTool for TODO tracking
        self.todo_write_tool = FunctionTool(
            todo_write_function,
            description="Write and update TODO list for task tracking. Use this to enumerate all tasks upfront and track progress."
        )
    
    async def access_catalog(
        self,
        action: str,
        file_name: Optional[str] = None,
        description: Optional[str] = None,
        absolute_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Access file catalog - read or write file information
        
        Args:
            action: "get", "add", "list"
            file_name: Name of file (for get/add)
            description: Description of file (for add)
            absolute_path: Absolute path to file (for add)
        
        Returns:
            Dict with result
        """
        try:
            if action == "get":
                result = self.catalog.get_file(file_name)
                return {"success": True, "data": result}
            
            elif action == "add":
                self.catalog.add_file(file_name, absolute_path, description)
                return {"success": True, "message": f"Added {file_name} to catalog"}
            
            elif action == "list":
                result = self.catalog.get_all_files()
                return {"success": True, "files": result}
            
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        
        except Exception as e:
            logger.error(f"Catalog access error: {e}")
            return {"success": False, "error": str(e)}
    
    async def access_knowledge_base(
        self,
        action: str,
        query: Optional[str] = None,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Access knowledge base (vector store) - read or write knowledge
        
        Args:
            action: "search", "add", "stats"
            query: Search query (for search)
            content: Content to add (for add)
            metadata: Metadata for content (for add)
        
        Returns:
            Dict with result
        """
        try:
            if action == "search":
                # Get embedding for query
                from control_plane_v2.phase_2.orchestrator_phase2_v2 import get_openai_embedding
                query_embedding = await get_openai_embedding(query)
                results = self.vector_store.search(query_embedding, top_k=5)
                return {"success": True, "data": results}
            
            elif action == "add":
                # Get embedding for content
                from control_plane_v2.phase_2.orchestrator_phase2_v2 import get_openai_embedding
                content_embedding = await get_openai_embedding(content)
                self.vector_store.add(content, content_embedding, metadata or {})
                logger.info(f"[VECTOR_STORE] Updated: Added entry with metadata: {metadata}")
                return {"success": True, "message": "Added to knowledge base"}
            
            elif action == "stats":
                stats = self.vector_store.get_stats()
                return {"success": True, "data": stats}
            
            else:
                return {"success": False, "error": f"Unknown action: {action}"}
        
        except Exception as e:
            logger.error(f"Knowledge base access error: {e}")
            return {"success": False, "error": str(e)}
    
    async def execute_python_code(self, code: str, cancellation_token = None) -> Dict[str, Any]:
        """
        Execute Python code using LocalCommandLineCodeExecutor
        
        Args:
            code: Python code to execute
            cancellation_token: Optional cancellation token
        
        Returns:
            Dict with execution result
        """
        try:
            code_block = CodeBlock(code=code, language="python")
            result = await self.code_executor.execute_code_blocks([code_block], cancellation_token=cancellation_token)
            
            return {
                "success": result.exit_code == 0,
                "output": result.output,
                "exit_code": result.exit_code
            }
        
        except Exception as e:
            logger.error(f"Code execution error: {e}")
            return {
                "success": False,
                "error": str(e),
                "output": "",
                "exit_code": -1
            }
    
    async def scan_dir(
        self,
        base_path: str,
        max_depth: int = 3,
        include_files: bool = True,
        include_dirs: bool = True,
        file_extensions: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Scan a directory structure
        
        Args:
            base_path: Base directory path to scan
            max_depth: Maximum depth to scan
            include_files: Include files in results
            include_dirs: Include directories in results
            file_extensions: Filter by extensions (e.g., '.py,.json')
        
        Returns:
            Dict with scan results
        """
        return await scan_directory(base_path, max_depth, include_files, include_dirs, file_extensions)
    
    
    def get_all_tools(self):
        """Get all tools as FunctionTool list for model client"""
        return [self.scan_directory_tool, self.todo_write_tool]
    
    async def cleanup(self):
        """Cleanup resources"""
        try:
            await self.code_executor.__aexit__(None, None, None)
        except:
            pass

