"""
Knowledge System - Integrated Data Catalog + RAG Memory

Provides unified interface for:
- Registering data artifacts (Catalog)
- Storing task learnings (RAG)
- Querying execution history
- Retrieving relevant context for new tasks
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional

from control_plane_v2.data_catalog import DataCatalog
from control_plane_v2.azure_openai_rag_memory import AzureOpenAIRAGMemory

logger = logging.getLogger(__name__)


class KnowledgeSystem:
    """
    Unified knowledge management for task execution.
    
    Combines:
    - Data Catalog (structured metadata)
    - RAG Memory (Azure OpenAI semantic search)
    """
    
    def __init__(
        self, 
        workspace_root: str,
        catalog_dir: str = None,
        vectordb_dir: str = None,
        azure_endpoint: str = None,
        azure_api_key: str = None,
        azure_api_version: str = None
    ):
        """
        Initialize knowledge system.
        
        Args:
            workspace_root: Root directory for knowledge storage (run directory)
            catalog_dir: Directory for catalog storage (default: workspace_root/catalog)
            vectordb_dir: Directory for vector database storage (default: workspace_root/vectordb)
            azure_endpoint: Azure OpenAI endpoint (optional, will load from env_info.json if not provided)
            azure_api_key: Azure OpenAI API key (optional)
            azure_api_version: Azure OpenAI API version (optional)
        """
        self.workspace_root = Path(workspace_root)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        
        # Use provided directories or defaults
        self.catalog_dir = Path(catalog_dir) if catalog_dir else (self.workspace_root / "catalog")
        self.vectordb_dir = Path(vectordb_dir) if vectordb_dir else (self.workspace_root / "vectordb")
        
        # Create directories
        self.catalog_dir.mkdir(parents=True, exist_ok=True)
        self.vectordb_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize catalog in catalog directory
        catalog_path = self.catalog_dir / "data_catalog.json"
        self.catalog = DataCatalog(str(catalog_path))
        
        # Load Azure config if not provided
        if not all([azure_endpoint, azure_api_key, azure_api_version]):
            azure_config = self._load_azure_config()
        else:
            azure_config = {
                "endpoint": azure_endpoint,
                "api_key": azure_api_key,
                "api_version": azure_api_version
            }
        
        # Initialize RAG with Azure OpenAI in vectordb directory
        try:
            self.rag = AzureOpenAIRAGMemory(
                workspace_root=str(self.vectordb_dir),
                azure_endpoint=azure_config["endpoint"],
                api_key=azure_config["api_key"],
                api_version=azure_config["api_version"],
                deployment_name="text-embedding-3-small"
            )
            logger.info(f"[KNOWLEDGE] Initialized with Azure OpenAI embeddings")
        except Exception as e:
            logger.warning(f"[KNOWLEDGE] Failed to initialize Azure RAG: {e}")
            logger.warning(f"[KNOWLEDGE] Using fallback knowledge system (no embeddings)")
            # Create a simple fallback that just stores/retrieves JSON
            self.rag = None
        
        logger.info(f"[KNOWLEDGE] Initialized in {workspace_root}")
        logger.info(f"[KNOWLEDGE] Catalog dir: {self.catalog_dir}")
        logger.info(f"[KNOWLEDGE] VectorDB dir: {self.vectordb_dir}")
        logger.info(f"[KNOWLEDGE] Catalog: {self.catalog.get_stats()['total_files']} files")
        if self.rag:
            logger.info(f"[KNOWLEDGE] RAG: {self.rag.get_stats().get('total_learnings', 0)} learnings")
        else:
            logger.info(f"[KNOWLEDGE] RAG: Disabled (fallback mode)")
    
    def _load_azure_config(self) -> Dict[str, str]:
        """Load Azure OpenAI config from env_info.json"""
        try:
            # Look for env_info.json in parent directories
            current = Path(__file__).parent
            for _ in range(5):  # Search up to 5 levels
                env_file = current / "env_info.json"
                if env_file.exists():
                    with open(env_file) as f:
                        config = json.load(f)
                    azure = config["llm_config"]["azure"]
                    return {
                        "endpoint": azure["endpoint"],
                        "api_key": azure["api_key"],
                        "api_version": azure["api_version"]
                    }
                current = current.parent
            
            raise FileNotFoundError("env_info.json not found")
        except Exception as e:
            logger.error(f"[KNOWLEDGE] Failed to load Azure config: {e}")
            raise
    
    def register_task_completion(
        self,
        task_id: str,
        task_type: str,
        success: bool,
        output_files: List[str],
        learnings: Dict[str, Any],
        execution_time: float = None,
        file_metadata: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, Any]:
        """
        Register complete task execution including files and learnings.
        
        Args:
            task_id: Task identifier
            task_type: Type of task (extract, transform, etc.)
            success: Whether task succeeded
            output_files: List of file paths created
            learnings: Task learnings dictionary
            execution_time: Execution time in seconds
            file_metadata: Optional per-file metadata (schema, row_count, etc.)
            
        Returns:
            Registration result with catalog and RAG status
        """
        result = {
            "task_id": task_id,
            "catalog_status": "pending",
            "rag_status": "pending",
            "files_registered": 0,
            "learnings_indexed": False
        }
        
        # Register files in catalog
        file_ids = []
        for file_path in output_files:
            if Path(file_path).exists():
                meta = file_metadata.get(file_path, {}) if file_metadata else {}
                file_id = self.catalog.register_file(
                    file_path=file_path,
                    task_id=task_id,
                    file_type=meta.get("file_type", "data"),
                    schema=meta.get("schema"),
                    row_count=meta.get("row_count"),
                    metadata=meta.get("metadata", {})
                )
                if file_id:
                    file_ids.append(file_id)
        
        result["files_registered"] = len(file_ids)
        result["catalog_status"] = "success" if file_ids else "no_files"
        
        # Add learnings to RAG
        if learnings and self.rag:
            # Convert learnings dict to a descriptive text for embedding
            learning_text = self._format_learnings_for_rag(learnings, task_id, task_type)
            
            rag_success = self.rag.add_learning(
                text=learning_text,
                task_id=task_id,
                task_type=task_type,
                success=success,
                metadata={"execution_time": execution_time, "learnings": learnings}
            )
            result["learnings_indexed"] = rag_success
            result["rag_status"] = "success" if rag_success else "failed"
        else:
            result["rag_status"] = "no_learnings" if not learnings else "rag_disabled"
        
        logger.info(f"[KNOWLEDGE] Registered {task_id}: {result['files_registered']} files, learnings={result['learnings_indexed']}")
        return result
    
    def get_context_for_task(
        self,
        task_description: str,
        task_type: str,
        dependencies: List[str] = None
    ) -> Dict[str, Any]:
        """
        Get relevant context for a new task.
        
        Provides:
        - Input files from dependencies (Catalog)
        - Similar task learnings (RAG)
        - Best practices for task type (RAG)
        - Error patterns to avoid (RAG)
        
        Args:
            task_description: Description of the task
            task_type: Type of task
            dependencies: List of dependency task IDs
            
        Returns:
            Context dictionary with catalog and RAG results
        """
        context = {
            "input_files": {},
            "similar_tasks": [],
            "best_practices": [],
            "error_patterns": []
        }
        
        # Get input files from dependencies (Catalog)
        if dependencies:
            for dep_id in dependencies:
                files = self.catalog.get_files_by_task(dep_id)
                if files:
                    context["input_files"][dep_id] = files
        
        # Use RAG's built-in get_context_for_task method (if available)
        if self.rag:
            rag_context = self.rag.get_context_for_task(
                task_description=task_description,
                task_type=task_type,
                dependencies=dependencies or []
            )
            
            # Merge RAG context
            context["similar_tasks"] = rag_context.get("similar_tasks", [])
            context["best_practices"] = [
                p.get("description", "") 
                for p in rag_context.get("relevant_practices", [])
            ]
            
            # Get error patterns (search for failed tasks)
            error_results = self.rag.search(
                query=f"Common issues in {task_type}",
                task_type=task_type,
                success_only=False,  # Include failures
                top_k=3
            )
            context["error_patterns"] = [
                {
                    "task": e["metadata"]["task_id"],
                    "gotchas": e["metadata"].get("learnings", {}).get("gotchas", [])
                }
                for e in error_results if e["metadata"].get("learnings", {}).get("gotchas")
            ]
        
        logger.info(f"[KNOWLEDGE] Context for '{task_type}': {len(context['input_files'])} deps, {len(context['similar_tasks'])} similar, {len(context['best_practices'])} practices")
        return context
    
    def search_solutions_for_error(self, error_message: str) -> List[Dict]:
        """
        Find how similar errors were solved.
        
        Args:
            error_message: Error message or description
            
        Returns:
            List of similar error cases with solutions
        """
        if not self.rag:
            return []
        
        # Search for similar errors (including failed tasks)
        results = self.rag.search(
            query=error_message,
            success_only=False,  # Include failures
            top_k=5
        )
        
        # Return with solutions
        solutions = []
        for r in results:
            learnings = r["metadata"].get("learnings", {})
            if learnings.get("solution") or learnings.get("fix_applied"):
                solutions.append({
                    "task_id": r["metadata"]["task_id"],
                    "error_description": r["document"],
                    "solution": learnings.get("solution") or learnings.get("fix_applied"),
                    "similarity": r["similarity"]
                })
        
        return solutions[:3]
    
    def get_file_by_pattern(self, name_pattern: str) -> List[Dict]:
        """Search catalog for files matching pattern"""
        return self.catalog.search_files(name_pattern=name_pattern)
    
    def get_files_from_task(self, task_id: str) -> List[Dict]:
        """Get all files from a specific task"""
        return self.catalog.get_files_by_task(task_id)
    
    def _format_learnings_for_rag(
        self, 
        learnings: Dict[str, Any], 
        task_id: str, 
        task_type: str
    ) -> str:
        """
        Convert learnings dictionary to a descriptive text for embedding.
        
        The text should capture the essence of what was learned
        in a way that semantic search can find it later.
        """
        parts = [f"Task {task_id} ({task_type}):"]
        
        # Add key learnings
        if "key_learnings" in learnings:
            if isinstance(learnings["key_learnings"], list):
                parts.extend(learnings["key_learnings"])
            else:
                parts.append(str(learnings["key_learnings"]))
        
        # Add recommendations
        if "recommendations" in learnings:
            parts.append(f"Recommendations: {learnings['recommendations']}")
        
        # Add gotchas
        if "gotchas" in learnings:
            gotchas = learnings["gotchas"]
            if isinstance(gotchas, list):
                parts.append("Gotchas: " + "; ".join(gotchas))
            else:
                parts.append(f"Gotchas: {gotchas}")
        
        # Add best practices
        if "best_practices" in learnings:
            practices = learnings["best_practices"]
            if isinstance(practices, list):
                parts.extend([f"Best practice: {p}" for p in practices])
            else:
                parts.append(f"Best practice: {practices}")
        
        # Add solution/fix
        if "solution" in learnings:
            parts.append(f"Solution: {learnings['solution']}")
        if "fix_applied" in learnings:
            parts.append(f"Fix: {learnings['fix_applied']}")
        
        # Add any other string values
        for key, value in learnings.items():
            if key not in ['key_learnings', 'recommendations', 'gotchas', 'best_practices', 'solution', 'fix_applied']:
                if isinstance(value, str):
                    parts.append(f"{key}: {value}")
        
        return " ".join(parts)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive knowledge system statistics"""
        catalog_stats = self.catalog.get_stats()
        rag_stats = self.rag.get_stats() if self.rag else {"total_learnings": 0, "status": "disabled"}
        
        return {
            "catalog": catalog_stats,
            "rag": rag_stats,
            "integrated": True,
            "workspace": str(self.workspace_root)
        }
    
    def export_context_for_prompt(self, context: Dict[str, Any]) -> str:
        """
        Format context as a string for LLM prompts.
        
        Args:
            context: Context dictionary from get_context_for_task
            
        Returns:
            Formatted string for inclusion in prompts
        """
        lines = []
        
        # Input files
        if context["input_files"]:
            lines.append("**AVAILABLE INPUT FILES:**")
            for dep_id, files in context["input_files"].items():
                lines.append(f"\nFrom {dep_id}:")
                for file in files:
                    lines.append(f"  - {file['name']} ({file['size_bytes']/1024:.1f} KB)")
                    if file.get("row_count"):
                        lines.append(f"    Rows: {file['row_count']}")
                    lines.append(f"    Path: {file['path']}")
        
        # Best practices
        if context["best_practices"]:
            lines.append("\n**BEST PRACTICES FROM SIMILAR TASKS:**")
            for i, practice in enumerate(context["best_practices"], 1):
                lines.append(f"  {i}. {practice}")
        
        # Error patterns to avoid
        if context["error_patterns"]:
            lines.append("\n**COMMON GOTCHAS TO AVOID:**")
            for pattern in context["error_patterns"]:
                gotchas = pattern.get("gotchas", [])
                if isinstance(gotchas, list):
                    for gotcha in gotchas[:2]:  # Max 2 per task
                        lines.append(f"  - {gotcha}")
        
        # Similar successful tasks
        if context["similar_tasks"]:
            lines.append("\n**SIMILAR SUCCESSFUL TASKS:**")
            for task in context["similar_tasks"][:2]:  # Top 2
                lines.append(f"\n  Task: {task['task_id']}")
                if task["similarity_score"]:
                    lines.append(f"  Similarity: {task['similarity_score']:.2f}")
                learnings = task.get("learnings", {})
                if "recommendations" in learnings:
                    lines.append(f"  Key insight: {learnings['recommendations'][:150]}")
        
        return "\n".join(lines)

