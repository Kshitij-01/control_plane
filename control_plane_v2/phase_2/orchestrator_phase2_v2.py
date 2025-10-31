"""
Phase 2 Orchestrator v2 - Clean and Efficient
Intelligent orchestrator for Phase 2 task execution with workspace tools
"""

import logging
import sys
import json
import asyncio
import time
import pickle
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from scipy.spatial.distance import cosine

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from autogen_core import (
    RoutedAgent, MessageContext, message_handler,
    SingleThreadedAgentRuntime, AgentId, CancellationToken,
    FunctionCall, TRACE_LOGGER_NAME, EVENT_LOGGER_NAME
)
from autogen_core.code_executor import CodeBlock
from autogen_core.models import (
    ChatCompletionClient, SystemMessage, UserMessage, 
    AssistantMessage, FunctionExecutionResult, FunctionExecutionResultMessage
)
from autogen_core.tools import FunctionTool
from autogen_ext.code_executors.local import LocalCommandLineCodeExecutor
from typing_extensions import Annotated

logger = logging.getLogger(__name__)

@dataclass
class SimpleMessage:
    """Simple message for orchestrator communication"""
    content: str

@dataclass
class OrchestratorEvent:
    """Structured event for logging"""
    event_type: str
    task_id: str
    message: str
    timestamp: str
    details: Optional[Dict[str, Any]] = None

# Utility functions
def get_latest_run_path() -> Optional[Path]:
    """Get the path to the latest run directory"""
    runs_dir = project_root / "runs"
    if not runs_dir.exists():
        return None
    
    run_dirs = [d for d in runs_dir.iterdir() if d.is_dir() and d.name.startswith('run_')]
    if not run_dirs:
        return None
    
    return max(run_dirs, key=lambda x: x.stat().st_mtime)

def get_run_path(run_id: str) -> Optional[Path]:
    """Get the path to a specific run directory"""
    if run_id == 'latest':
        return get_latest_run_path()
    else:
        runs_dir = project_root / "runs"
        run_path = runs_dir / run_id
        return run_path if run_path.exists() else None

async def get_openai_embedding(text: str) -> List[float]:
    """Get OpenAI embedding for text using Azure OpenAI"""
    try:
        # Import Azure OpenAI client (correct for 2025)
        from openai import AsyncAzureOpenAI
        
        # Load env info for API key
        env_info_path = project_root / "env_info.json"
        with open(env_info_path, 'r') as f:
            env_info = json.load(f)
        
        azure_config = env_info['llm_config']['azure']
        
        # Create Azure OpenAI client (correct syntax for 2025)
        client = AsyncAzureOpenAI(
            api_key=azure_config['api_key'],
            azure_endpoint=azure_config['endpoint'],
            api_version=azure_config['api_version']
        )
        
        # Get embedding
        response = await client.embeddings.create(
            model=azure_config['embeddings']['deployment_name'],
            input=text
        )
        
        return response.data[0].embedding
        
    except Exception as e:
        logger.error(f"Failed to get OpenAI embedding: {e}")
        # Return zero vector as fallback
        return [0.0] * 1536  # OpenAI embedding dimension

# Vector Store for RAG
class SimpleVectorStore:
    """Simple vector store using NumPy and cosine similarity"""
    
    def __init__(self, store_path: Path):
        self.store_path = store_path
        self.embeddings = []
        self.texts = []
        self.metadata = []
        self.load_store()
    
    def load_store(self):
        """Load existing vector store from file"""
        if self.store_path.exists():
            try:
                with open(self.store_path, 'rb') as f:
                    data = pickle.load(f)
                    self.embeddings = data.get('embeddings', [])
                    self.texts = data.get('texts', [])
                    self.metadata = data.get('metadata', [])
            except Exception as e:
                logger.warning(f"Failed to load vector store: {e}")
                self.init_empty()
        else:
            self.init_empty()
    
    def save_store(self):
        """Save vector store to file"""
        try:
            data = {
                'embeddings': self.embeddings,
                'texts': self.texts,
                'metadata': self.metadata
            }
            with open(self.store_path, 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.error(f"Failed to save vector store: {e}")
    
    def init_empty(self):
        """Initialize empty vector store"""
        self.embeddings = []
        self.texts = []
        self.metadata = []
        self.save_store()
    
    def add(self, text: str, embedding: List[float], metadata: Dict = None):
        """Add text with embedding to vector store"""
        self.embeddings.append(np.array(embedding))
        self.texts.append(text)
        self.metadata.append(metadata or {})
        self.save_store()
    
    def search(self, query_embedding: List[float], top_k: int = 5) -> List[Dict]:
        """Search for similar embeddings using cosine similarity"""
        if not self.embeddings:
            return []
        
        query_vec = np.array(query_embedding)
        
        # Check if query is zero vector
        if np.allclose(query_vec, 0):
            logger.warning("Query embedding is zero vector, returning empty results")
            return []
        
        similarities = []
        
        for i, emb in enumerate(self.embeddings):
            # Check if stored embedding is zero vector
            if np.allclose(emb, 0):
                similarities.append((0.0, i))
                continue
            
            # Calculate cosine similarity (safe from division by zero)
            try:
                sim = 1 - cosine(query_vec, emb)
                # Handle NaN values
                if np.isnan(sim):
                    sim = 0.0
                similarities.append((sim, i))
            except Exception as e:
                logger.warning(f"Error calculating similarity for embedding {i}: {e}")
                similarities.append((0.0, i))
        
        # Sort by similarity (descending)
        similarities.sort(reverse=True)
        
        # Return top_k results
        results = []
        for sim, idx in similarities[:top_k]:
            results.append({
                "text": self.texts[idx],
                "metadata": self.metadata[idx],
                "similarity": float(sim)
            })
        
        return results
    
    def get_stats(self) -> Dict:
        """Get vector store statistics"""
        return {
            "total_embeddings": len(self.embeddings),
            "store_path": str(self.store_path),
            "last_updated": self.store_path.stat().st_mtime if self.store_path.exists() else None
        }

# File Catalog Management
class FileCatalog:
    """Simple file tracking with description and absolute path"""
    
    def __init__(self, catalog_path: Path):
        self.catalog_path = catalog_path
    
    def add_file(self, relative_path: str, absolute_path: str, description: str):
        """Add file to catalog"""
        # Normalize path separators to forward slashes for consistency
        normalized_path = relative_path.replace('\\', '/')
        catalog = self.load_catalog()
        catalog["files"][normalized_path] = {
            "path": normalized_path,
            "absolute_path": absolute_path,
            "description": description
        }
        self.save_catalog(catalog)
    
    def get_file(self, relative_path: str) -> Dict:
        """Get file info by relative path - normalize path separators"""
        # Normalize path separators to forward slashes for consistent lookup
        normalized_path = relative_path.replace('\\', '/')
        catalog = self.load_catalog()
        # Try normalized path first
        result = catalog["files"].get(normalized_path, {})
        if not result:
            # Fallback: try with backslashes (for backward compatibility)
            result = catalog["files"].get(relative_path.replace('/', '\\'), {})
        return result
    
    def get_all_files(self) -> Dict:
        """Get all files in catalog"""
        catalog = self.load_catalog()
        return catalog["files"]
    
    def load_catalog(self) -> Dict:
        """Load catalog from JSON file"""
        if self.catalog_path.exists():
            with open(self.catalog_path, 'r') as f:
                return json.load(f)
        return {"version": "1.0", "files": {}}
    
    def save_catalog(self, catalog: Dict):
        """Save catalog to JSON file"""
        with open(self.catalog_path, 'w') as f:
            json.dump(catalog, f, indent=2)

# Tool Functions
async def search_workspace(
    query: str, 
    run_id: Annotated[str, "The run ID to search within"],
    file_types: Annotated[List[str], "File extensions to search for (e.g., ['.py', '.json', '.txt'])"]
) -> Dict[str, Any]:
    """Search for files and content in the workspace for a specific run"""
    try:
        workspace_path = get_run_path(run_id)
        if not workspace_path:
            return {"error": f"Run {run_id} not found"}
        
        results = {
            "run_id": workspace_path.name,
            "workspace_path": str(workspace_path),
            "query": query,
            "matches": []
        }
        
        query_words = query.lower().replace('_', ' ').replace('-', ' ').split()
        
        for file_path in workspace_path.rglob("*"):
            if not file_path.is_file():
                continue
                
            # Check file extension filter
            if file_types and file_path.suffix not in file_types:
                continue
            
            filename_lower = file_path.name.lower().replace('_', ' ').replace('-', ' ')
            
            # Check filename match
            if all(word in filename_lower for word in query_words):
                results["matches"].append({
                    "type": "filename_match",
                    "path": str(file_path.relative_to(workspace_path)),
                    "full_path": str(file_path),
                    "size": file_path.stat().st_size
                })
            
            # Check content match for text files
            elif file_path.suffix in ['.txt', '.py', '.json', '.md', '.log']:
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if query.lower() in content.lower():
                            lines = content.split('\n')
                            matching_lines = [
                                {"line_number": i, "content": line.strip()}
                                for i, line in enumerate(lines, 1)
                                if query.lower() in line.lower()
                            ]
                            
                            results["matches"].append({
                                "type": "content_match",
                                "path": str(file_path.relative_to(workspace_path)),
                                "full_path": str(file_path),
                                "matching_lines": matching_lines[:10],
                                "total_matches": len(matching_lines)
                            })
                except Exception:
                    continue
        
        return results
        
    except Exception as e:
        return {"error": f"Search failed: {str(e)}"}

async def execute_python_code(
    code: str,
    run_id: Annotated[str, "The run ID to execute code in"],
    description: Annotated[str, "Description of what the code does"]
) -> Dict[str, Any]:
    """Execute Python code in the workspace for a specific run"""
    try:
        workspace_path = get_run_path(run_id)
        if not workspace_path:
            return {"error": f"Run {run_id} not found"}
        
        # Create code execution directory
        code_exec_dir = workspace_path / "code_execution"
        code_exec_dir.mkdir(exist_ok=True)
        
        # Create code executor
        code_executor = LocalCommandLineCodeExecutor(
            work_dir=str(workspace_path),
            timeout=120
        )
        
        await code_executor.start()
        
        try:
            result = await code_executor.execute_code_blocks(
                code_blocks=[CodeBlock(language="python", code=code)],
                cancellation_token=CancellationToken()
            )
            
            return {
                "run_id": workspace_path.name,
                "workspace_path": str(workspace_path),
                "description": description,
                "exit_code": result.exit_code,
                "stdout": result.output if hasattr(result, 'output') else str(result),
                "stderr": result.stderr if hasattr(result, 'stderr') else "",
                "success": result.exit_code == 0
            }
            
        finally:
            await code_executor.stop()
            
    except Exception as e:
        return {"error": f"Code execution failed: {str(e)}"}

async def read_execution_plan(
    run_id: Annotated[str, "Run ID to read execution plan from (use 'latest' for most recent)"]
) -> str:
    """Read and return the complete execution plan JSON content for analysis"""
    try:
        workspace_path = get_run_path(run_id)
        if not workspace_path:
            return f"Run {run_id} not found"
        
        execution_plan_file = workspace_path / "phase1" / "execution_plan.json"
        if not execution_plan_file.exists():
            return f"Execution plan not found at {execution_plan_file}"
        
        with open(execution_plan_file, 'r') as f:
            return f.read()
        
    except Exception as e:
        return f"Error reading execution plan: {str(e)}"

async def manage_vector_store(
    action: Annotated[str, "Action: 'add', 'search', 'init', 'stats'"],
    run_id: Annotated[str, "Run ID to manage vector store for"],
    text: Annotated[str, "Text to add or search query"] = "",
    metadata: Annotated[Dict, "Metadata for the text (for add action)"] = None,
    top_k: Annotated[int, "Number of top results to return (for search)"] = 5
) -> Dict[str, Any]:
    """Manage the vector store for RAG knowledge storage and retrieval"""
    try:
        workspace_path = get_run_path(run_id)
        if not workspace_path:
            return {"error": f"Run {run_id} not found"}
        
        vector_store_path = workspace_path / "vector_store.pkl"
        vector_store = SimpleVectorStore(vector_store_path)
        
        if action == "init":
            vector_store.init_empty()
            return {"success": True, "message": "Vector store initialized"}
        
        elif action == "add":
            if not text:
                return {"error": "Missing text parameter for add action"}
            
            # Get OpenAI embedding
            embedding = await get_openai_embedding(text)
            vector_store.add(text, embedding, metadata or {})
            return {
                "success": True,
                "message": f"Added text to vector store",
                "text": text[:100] + "..." if len(text) > 100 else text
            }
        
        elif action == "search":
            if not text:
                return {"error": "Missing text parameter for search action"}
            
            # Get OpenAI embedding for search
            query_embedding = await get_openai_embedding(text)
            results = vector_store.search(query_embedding, top_k)
            return {
                "success": True,
                "query": text,
                "results": results,
                "total_results": len(results)
            }
        
        elif action == "stats":
            stats = vector_store.get_stats()
            return {"success": True, "stats": stats}
        
        else:
            return {"error": f"Unknown action: {action}. Use 'init', 'add', 'search', or 'stats'"}
        
    except Exception as e:
        return {"error": f"Vector store operation failed: {str(e)}"}

async def manage_file_catalog(
    action: Annotated[str, "Action: 'add', 'get', 'list', 'init'"],
    run_id: Annotated[str, "Run ID to manage catalog for"],
    relative_path: Annotated[str, "Relative file path (for add/get actions)"] = "",
    absolute_path: Annotated[str, "Absolute file path (for add action)"] = "",
    description: Annotated[str, "File description (for add action)"] = ""
) -> Dict[str, Any]:
    """Manage the file catalog for tracking files with descriptions and absolute paths"""
    try:
        workspace_path = get_run_path(run_id)
        if not workspace_path:
            return {"error": f"Run {run_id} not found"}
        
        catalog_path = workspace_path / "file_catalog.json"
        catalog = FileCatalog(catalog_path)
        
        if action == "init":
            # Initialize empty catalog
            catalog.save_catalog({"version": "1.0", "files": {}})
            return {"success": True, "message": "File catalog initialized"}
        
        elif action == "add":
            if not relative_path or not absolute_path or not description:
                return {"error": "Missing required parameters for add action"}
            
            catalog.add_file(relative_path, absolute_path, description)
            return {
                "success": True, 
                "message": f"Added file to catalog: {relative_path}",
                "file_info": catalog.get_file(relative_path)
            }
        
        elif action == "get":
            if not relative_path:
                return {"error": "Missing relative_path for get action"}
            
            file_info = catalog.get_file(relative_path)
            if not file_info:
                return {"error": f"File not found in catalog: {relative_path}"}
            
            return {"success": True, "file_info": file_info}
        
        elif action == "list":
            all_files = catalog.get_all_files()
            return {
                "success": True,
                "total_files": len(all_files),
                "files": all_files
            }
        
        else:
            return {"error": f"Unknown action: {action}. Use 'init', 'add', 'get', or 'list'"}
        
    except Exception as e:
        return {"error": f"Catalog operation failed: {str(e)}"}

async def scan_and_populate_knowledge_systems(
    run_id: Annotated[str, "Run ID to scan and populate knowledge systems for"]
) -> Dict[str, Any]:
    """Scan the workspace directory and automatically populate both catalog and vector store"""
    try:
        workspace_path = get_run_path(run_id)
        if not workspace_path:
            return {"error": f"Run {run_id} not found"}
        
        # Initialize systems
        catalog_path = workspace_path / "file_catalog.json"
        vector_store_path = workspace_path / "vector_store.pkl"
        catalog = FileCatalog(catalog_path)
        vector_store = SimpleVectorStore(vector_store_path)
        
        # Initialize empty systems
        catalog.save_catalog({"version": "1.0", "files": {}})
        vector_store.init_empty()
        
        # Scan all files in workspace
        files_found = []
        for file_path in workspace_path.rglob("*"):
            if file_path.is_file() and not file_path.name.startswith('.'):
                relative_path = str(file_path.relative_to(workspace_path))
                absolute_path = str(file_path.resolve())
                
                # Generate description based on file extension and name
                description = generate_file_description(file_path)
                
                # Add to catalog
                catalog.add_file(relative_path, absolute_path, description)
                
                # Add file info to vector store
                file_info_text = f"File: {relative_path}. {description}. Located at: {absolute_path}"
                embedding = await get_openai_embedding(file_info_text)
                vector_store.add(file_info_text, embedding, {
                    "type": "file_info",
                    "relative_path": relative_path,
                    "absolute_path": absolute_path,
                    "file_extension": file_path.suffix,
                    "file_size": file_path.stat().st_size
                })
                
                files_found.append({
                    "relative_path": relative_path,
                    "absolute_path": absolute_path,
                    "description": description,
                    "size": file_path.stat().st_size
                })
        
        return {
            "success": True,
            "message": f"Successfully scanned and populated knowledge systems",
            "files_found": len(files_found),
            "files": files_found[:10],  # Show first 10 files
            "catalog_path": str(catalog_path),
            "vector_store_path": str(vector_store_path)
        }
        
    except Exception as e:
        return {"error": f"Failed to scan and populate knowledge systems: {str(e)}"}

def generate_file_description(file_path: Path) -> str:
    """Generate a description for a file based on its name and extension"""
    name = file_path.name.lower()
    ext = file_path.suffix.lower()
    
    # Common file types
    if ext == '.csv':
        return "CSV data file containing structured data"
    elif ext == '.json':
        return "JSON configuration or data file"
    elif ext == '.py':
        return "Python script or module"
    elif ext == '.txt':
        return "Text file with documentation or data"
    elif ext == '.md':
        return "Markdown documentation file"
    elif ext == '.log':
        return "Log file with execution or error information"
    elif ext == '.parquet':
        return "Parquet data file with columnar storage"
    elif ext == '.xlsx' or ext == '.xls':
        return "Excel spreadsheet file"
    elif 'profile' in name:
        return "Data profiling results or configuration"
    elif 'execution' in name or 'plan' in name:
        return "Execution plan or task configuration"
    elif 'manifest' in name:
        return "Task manifest or metadata file"
    elif 'summary' in name:
        return "Summary or report file"
    elif 'result' in name or 'output' in name:
        return "Task execution result or output file"
    else:
        return f"Data file with {ext} extension"

async def get_task_context(
    run_id: Annotated[str, "Run ID to get context for"],
    task_description: Annotated[str, "Description of the task to get context for"],
    required_files: Annotated[List[str], "List of required file names"]
) -> Dict[str, Any]:
    """Get comprehensive context for a task including file paths and RAG knowledge"""
    try:
        workspace_path = get_run_path(run_id)
        if not workspace_path:
            return {"error": f"Run {run_id} not found"}
        
        # Initialize systems
        catalog_path = workspace_path / "file_catalog.json"
        vector_store_path = workspace_path / "vector_store.pkl"
        catalog = FileCatalog(catalog_path)
        vector_store = SimpleVectorStore(vector_store_path)
        
        # Get file paths from catalog
        file_paths = {}
        for file_name in required_files:
            file_info = catalog.get_file(file_name)
            if file_info:
                file_paths[file_name] = file_info["absolute_path"]
            else:
                # Try to find file in workspace
                found_files = list(workspace_path.rglob(file_name))
                if found_files:
                    file_paths[file_name] = str(found_files[0])
        
        # Search vector store for relevant context
        rag_context = []
        if vector_store.get_stats()["total_embeddings"] > 0:
            query_embedding = await get_openai_embedding(task_description)
            rag_results = vector_store.search(query_embedding, top_k=5)
            rag_context = rag_results
        
        return {
            "success": True,
            "task_description": task_description,
            "file_paths": file_paths,
            "rag_context": rag_context,
            "workspace_path": str(workspace_path)
        }
        
    except Exception as e:
        return {"error": f"Failed to get task context: {str(e)}"}

# Create tools
workspace_search_tool = FunctionTool(
    search_workspace, 
    description="Search for files and content in the workspace for a specific run. Use 'latest' for the most recent run."
)

code_execution_tool = FunctionTool(
    execute_python_code,
    description="Execute Python code in the workspace for a specific run. Use 'latest' for the most recent run."
)

execution_plan_tool = FunctionTool(
    read_execution_plan,
    description="Read and return the complete execution plan JSON content for analysis."
)

file_catalog_tool = FunctionTool(
    manage_file_catalog,
    description="Manage the file catalog for tracking files with descriptions and absolute paths. Actions: 'init', 'add', 'get', 'list'."
)

vector_store_tool = FunctionTool(
    manage_vector_store,
    description="Manage the vector store for RAG knowledge storage and retrieval. Actions: 'init', 'add', 'search', 'stats'."
)

task_context_tool = FunctionTool(
    get_task_context,
    description="Get comprehensive context for a task including file paths and RAG knowledge from previous tasks."
)

scan_knowledge_tool = FunctionTool(
    scan_and_populate_knowledge_systems,
    description="Scan the entire workspace directory and automatically populate both the file catalog and vector store with all discovered files."
)

class OrchestratorPhase2V2(RoutedAgent):
    """Phase 2 Orchestrator - Clean and efficient implementation"""
    
    def __init__(self, model_client: ChatCompletionClient) -> None:
        super().__init__("Phase 2 Orchestrator v2 - Intelligent task orchestrator")
        self._model_client = model_client
        self._tools = [workspace_search_tool, code_execution_tool, execution_plan_tool, file_catalog_tool, vector_store_tool, task_context_tool, scan_knowledge_tool]
        
        # Setup logging
        self._trace_logger = logging.getLogger(f"{TRACE_LOGGER_NAME}.orchestrator_phase2_v2")
        self._event_logger = logging.getLogger(f"{EVENT_LOGGER_NAME}.orchestrator_phase2_v2")
        
        self._trace_logger.setLevel(logging.DEBUG)
        if not self._trace_logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
            self._trace_logger.addHandler(handler)
        
        # System message
        self._system_messages = [SystemMessage(content="""You are an intelligent AI coordinator for workspace knowledge management. 
Your primary task is to scan the workspace and populate knowledge systems.

You have access to seven powerful tools:

1. read_execution_plan: Read and analyze the complete execution plan JSON structure
2. search_workspace: Search for files and content within a specific run directory
3. execute_python_code: Execute Python code in the workspace to read files, analyze data, and perform computations
4. manage_file_catalog: Manage the file catalog for tracking files with descriptions and absolute paths
5. manage_vector_store: Manage the vector store for RAG knowledge storage and retrieval
6. get_task_context: Get comprehensive context for a task including file paths and RAG knowledge from previous tasks
7. scan_and_populate_knowledge_systems: Scan the entire workspace and automatically populate both catalog and vector store

INTELLIGENT ORCHESTRATION STRATEGY:
When you receive a message:
1. SCAN AND POPULATE KNOWLEDGE: Use scan_and_populate_knowledge_systems to automatically scan the entire workspace directory and populate both the file catalog and vector store with all discovered files
2. Report on what files were found and how the knowledge systems were populated
3. Use manage_vector_store with action='stats' to show the vector store statistics
4. Use manage_file_catalog with action='list' to show the catalog contents

SMART FILE MANAGEMENT:
- Track which tasks have been completed and their output files using manage_file_catalog
- Pass output files from completed tasks as input files to dependent tasks
- Ensure all required files are available before executing tasks
- Monitor execution results and handle failures gracefully

RAG KNOWLEDGE SHARING:
- Store insights from each task in the vector store using manage_vector_store with action='add'
- When starting new tasks, use get_task_context to retrieve relevant knowledge from previous tasks
- This enables knowledge transfer between tasks and improves task execution quality

TASK EXECUTION FLOW:
- Execute tasks in dependency order (sequential_first → independent → sequential_last)
- Monitor each task completion before starting dependent tasks
- Provide comprehensive feedback on execution progress
- Handle errors and retry failed tasks when appropriate

Always use 'latest' as the run_id unless specifically told otherwise.
Focus on scanning the workspace and populating the knowledge systems with comprehensive file information.""")]
        
        logger.info("OrchestratorPhase2V2 initialized successfully!")
    
    @message_handler
    async def handle_simple_message(self, message: SimpleMessage, ctx: MessageContext) -> SimpleMessage:
        """Handle messages with tool capabilities and iteration"""
        
        self._trace_logger.info("="*60)
        self._trace_logger.info("ORCHESTRATOR PHASE 2 V2 - PROCESSING MESSAGE")
        self._trace_logger.info("="*60)
        self._trace_logger.info(f"Received message: {message.content}")
        
        # Emit structured event
        event = OrchestratorEvent(
            event_type="message_received",
            task_id="orchestrator",
            message=message.content,
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            details={"message_length": len(message.content)}
        )
        self._event_logger.info(event)
        
        # Create session messages
        session = self._system_messages + [UserMessage(content=message.content, source="user")]
        
        # Allow multiple rounds of tool calling
        max_iterations = 30
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            logger.info(f"--- Iteration {iteration}/{max_iterations} ---")
            
            # Get response from model
            create_result = await self._model_client.create(
                messages=session,
                tools=self._tools,
                cancellation_token=ctx.cancellation_token,
            )
            
            # If no tool calls, return the string response
            if isinstance(create_result.content, str):
                logger.info(f"Final response (iteration {iteration}): {create_result.content}")
                logger.info("="*60)
                return SimpleMessage(content=create_result.content)
            
            # Handle tool calls
            assert isinstance(create_result.content, list) and all(
                isinstance(call, FunctionCall) for call in create_result.content
            )
            
            logger.info(f"Tool calls detected (iteration {iteration}): {len(create_result.content)}")
            
            # Add assistant message to session
            session.append(AssistantMessage(content=create_result.content, source="assistant"))
            
            # Execute tool calls
            results = await asyncio.gather(
                *[self._execute_tool_call(call, ctx.cancellation_token) for call in create_result.content]
            )
            
            # Add function execution results to session
            session.append(FunctionExecutionResultMessage(content=results))
            
            # Log tool results
            for result in results:
                if result.is_error:
                    logger.warning(f"Tool {result.name} failed: {result.content}")
                else:
                    logger.info(f"Tool {result.name} succeeded")
        
        # If we've reached max iterations, get final response
        final_result = await self._model_client.create(
            messages=session,
            cancellation_token=ctx.cancellation_token,
        )
        
        assert isinstance(final_result.content, str)
        logger.info(f"Final response after {max_iterations} iterations: {final_result.content}")
        logger.info("="*60)
        
        return SimpleMessage(content=final_result.content)
    
    async def _execute_tool_call(self, call: FunctionCall, cancellation_token: CancellationToken) -> FunctionExecutionResult:
        """Execute a tool call efficiently"""
        
        # Find the tool by name
        tool = next((tool for tool in self._tools if tool.name == call.name), None)
        assert tool is not None, f"Tool {call.name} not found"
        
        try:
            arguments = json.loads(call.arguments)
            logger.info(f"Executing tool {call.name} with args: {arguments}")
            
            result = await tool.run_json(arguments, cancellation_token)
            result_str = tool.return_value_as_string(result)
            
            logger.info(f"Tool {call.name} result: {result_str[:200]}...")
            
            return FunctionExecutionResult(
                call_id=call.id, 
                content=result_str, 
                is_error=False, 
                name=tool.name
            )
        except Exception as e:
            logger.error(f"Tool {call.name} failed: {str(e)}")
            return FunctionExecutionResult(
                call_id=call.id, 
                content=str(e), 
                is_error=True, 
                name=tool.name
            )

async def main():
    """Test the orchestrator"""
    logger.info("Starting Phase 2 Orchestrator v2 test")
    
    # Create runtime
    runtime = SingleThreadedAgentRuntime()
    
    # Register orchestrator
    await OrchestratorPhase2V2.register(
        runtime,
        "orchestrator_phase2_v2",
        lambda: OrchestratorPhase2V2(model_client=None)  # Will be set by run_from_phase2_v2.py
    )
    
    # Start runtime
    runtime.start()
    
    # Create a simple test message
    test_message = SimpleMessage(content="Hello from test!")
    
    logger.info("Sending test message to orchestrator...")
    
    # Send message
    agent_id = AgentId("orchestrator_phase2_v2", "default")
    result = await runtime.send_message(test_message, agent_id)
    
    logger.info(f"Message sent, result: {result}")
    
    # Wait a bit
    await asyncio.sleep(2)
    
    logger.info("Test complete!")

if __name__ == "__main__":
    asyncio.run(main())