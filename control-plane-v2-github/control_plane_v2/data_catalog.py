"""
Data Catalog - Structured metadata about data artifacts and tasks

Tracks:
- Files created by tasks (path, schema, row count, checksum)
- Task lineage and dependencies
- Data flow between tasks
"""

import json
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DataCatalog:
    """
    Centralized catalog of all data artifacts produced during execution.
    
    Provides:
    - Fast file lookups by task or type
    - Lineage tracking
    - Schema metadata
    - Validation support
    """
    
    def __init__(self, catalog_path: str):
        """
        Initialize data catalog.
        
        Args:
            catalog_path: Path to catalog JSON file
        """
        self.catalog_path = Path(catalog_path)
        self.catalog: Dict[str, Any] = {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "files": {},  # file_id -> metadata
            "tasks": {},  # task_id -> file list
            "lineage": {},  # file_id -> source task
            "task_summaries": {}  # NEW: task_id -> comprehensive task summary
        }
        self._load()
    
    def _load(self):
        """Load existing catalog from disk"""
        if self.catalog_path.exists():
            try:
                with open(self.catalog_path, 'r') as f:
                    self.catalog = json.load(f)
                logger.info(f"[CATALOG] Loaded {len(self.catalog['files'])} files from catalog")
            except Exception as e:
                logger.warning(f"[CATALOG] Could not load catalog: {e}, starting fresh")
    
    def _save(self):
        """Persist catalog to disk"""
        try:
            self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.catalog_path, 'w') as f:
                json.dump(self.catalog, f, indent=2)
            logger.debug(f"[CATALOG] Saved to {self.catalog_path}")
        except Exception as e:
            logger.error(f"[CATALOG] Failed to save: {e}")
    
    def register_file(
        self,
        file_path: str,
        task_id: str,
        file_type: str = "data",
        schema: Optional[Dict] = None,
        row_count: Optional[int] = None,
        metadata: Optional[Dict] = None
    ) -> str:
        """
        Register a file in the catalog.
        
        Args:
            file_path: Full path to file
            task_id: Task that created this file
            file_type: Type of file (data, schema, report, etc.)
            schema: Optional schema information
            row_count: Optional row count for data files
            metadata: Additional metadata
            
        Returns:
            file_id: Unique identifier for this file
        """
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"[CATALOG] File does not exist: {file_path}")
            return None
        
        # Generate file ID from path
        file_id = hashlib.md5(str(path.absolute()).encode()).hexdigest()[:16]
        
        # Calculate checksum
        try:
            with open(path, 'rb') as f:
                checksum = hashlib.md5(f.read()).hexdigest()
        except:
            checksum = None
        
        # Register file
        file_info = {
            "file_id": file_id,
            "path": str(path.absolute()),
            "name": path.name,
            "task_id": task_id,
            "file_type": file_type,
            "size_bytes": path.stat().st_size,
            "checksum": checksum,
            "schema": schema or {},
            "row_count": row_count,
            "created_at": datetime.now().isoformat(),
            "metadata": metadata or {}
        }
        
        self.catalog["files"][file_id] = file_info
        
        # Update task index
        if task_id not in self.catalog["tasks"]:
            self.catalog["tasks"][task_id] = []
        self.catalog["tasks"][task_id].append(file_id)
        
        # Update lineage
        self.catalog["lineage"][file_id] = {
            "source_task": task_id,
            "created_at": file_info["created_at"]
        }
        
        self._save()
        logger.info(f"[CATALOG] Registered {path.name} (file_id={file_id}, task={task_id})")
        return file_id
    
    def get_files_by_task(self, task_id: str) -> List[Dict]:
        """Get all files created by a task"""
        file_ids = self.catalog["tasks"].get(task_id, [])
        return [self.catalog["files"][fid] for fid in file_ids if fid in self.catalog["files"]]
    
    def get_file_by_type(self, file_type: str, task_id: Optional[str] = None) -> List[Dict]:
        """Get files by type, optionally filtered by task"""
        results = []
        for file_info in self.catalog["files"].values():
            if file_info["file_type"] == file_type:
                if task_id is None or file_info["task_id"] == task_id:
                    results.append(file_info)
        return results
    
    def get_latest_file(self, file_type: Optional[str] = None) -> Optional[Dict]:
        """Get most recently created file, optionally by type"""
        candidates = []
        for file_info in self.catalog["files"].values():
            if file_type is None or file_info["file_type"] == file_type:
                candidates.append(file_info)
        
        if not candidates:
            return None
        
        return max(candidates, key=lambda x: x["created_at"])
    
    def search_files(self, name_pattern: str = None, task_prefix: str = None) -> List[Dict]:
        """Search files by name pattern or task prefix"""
        results = []
        for file_info in self.catalog["files"].values():
            match = True
            if name_pattern and name_pattern.lower() not in file_info["name"].lower():
                match = False
            if task_prefix and not file_info["task_id"].startswith(task_prefix):
                match = False
            if match:
                results.append(file_info)
        return results
    
    def get_stats(self) -> Dict:
        """Get catalog statistics"""
        return {
            "total_files": len(self.catalog["files"]),
            "total_tasks": len(self.catalog["tasks"]),
            "total_size_mb": sum(f["size_bytes"] for f in self.catalog["files"].values()) / 1024 / 1024,
            "file_types": list(set(f["file_type"] for f in self.catalog["files"].values()))
        }
    
    # ========== NEW: ARTIFACT REF SUPPORT (ZERO-COPY ARCHITECTURE) ==========
    
    def register_artifact(self, artifact_dict: Dict) -> str:
        """
        Register an artifact using the new ArtifactRef model.
        
        Args:
            artifact_dict: Dictionary representation of ArtifactRef
            
        Returns:
            artifact_id: Unique identifier (typically sha256-based)
        """
        artifact_id = artifact_dict.get("id", hashlib.sha256(artifact_dict["path"].encode()).hexdigest()[:16])
        
        # Store artifact with enhanced metadata
        self.catalog["files"][artifact_id] = {
            "file_id": artifact_id,
            "artifact_id": artifact_id,  # Alias for new architecture
            "logical_name": artifact_dict.get("logical_name", ""),
            "filename": artifact_dict.get("filename", ""),
            "path": artifact_dict["path"],
            "name": artifact_dict.get("filename", Path(artifact_dict["path"]).name),
            "file_type": artifact_dict.get("file_type", "data"),
            "mime_type": artifact_dict.get("mime_type"),
            "size_bytes": artifact_dict.get("size_bytes", 0),
            "sha256": artifact_dict.get("sha256"),
            "checksum": artifact_dict.get("sha256"),  # Alias for compatibility
            "task_id": artifact_dict.get("produced_by_task", ""),
            "produced_by_task": artifact_dict.get("produced_by_task", ""),
            "created_at": artifact_dict.get("created_at", datetime.now().isoformat()),
            "metadata": {}
        }
        
        # Update task index
        task_id = artifact_dict.get("produced_by_task", "")
        if task_id:
            if task_id not in self.catalog["tasks"]:
                self.catalog["tasks"][task_id] = []
            self.catalog["tasks"][task_id].append(artifact_id)
        
        # Update lineage
        if task_id:
            self.catalog["lineage"][artifact_id] = {
                "source_task": task_id,
                "created_at": self.catalog["files"][artifact_id]["created_at"]
            }
        
        self._save()
        logger.info(f"[CATALOG] Registered artifact: {artifact_dict.get('logical_name', artifact_dict.get('filename'))} (id={artifact_id[:8]}...)")
        return artifact_id
    
    def register_task_summary(self, task_id: str, summary: Dict[str, Any]):
        """
        Store comprehensive task summary for intelligent file routing.
        
        This enables the orchestrator to intelligently route files between tasks
        by understanding what each file contains and which files are relevant
        for downstream tasks.
        
        Args:
            task_id: Unique identifier for the task
            summary: Comprehensive task summary with output_files metadata
        """
        self.catalog['task_summaries'][task_id] = {
            **summary,
            'registered_at': datetime.now().isoformat()
        }
        self._save()
        logger.info(f"[CATALOG] Registered task summary for {task_id} with {len(summary.get('output_files', []))} file(s)")
    
    def get_task_summary(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve comprehensive task summary by task_id.
        
        Args:
            task_id: Task identifier
            
        Returns:
            Task summary dict or None if not found
        """
        return self.catalog['task_summaries'].get(task_id)
    
    def get_artifacts_by_task(self, task_id: str) -> List[Dict]:
        """
        Get all artifacts produced by a task (new ArtifactRef format).
        
        Args:
            task_id: Task identifier
            
        Returns:
            List of artifact dictionaries compatible with ArtifactRef
        """
        file_ids = self.catalog["tasks"].get(task_id, [])
        artifacts = []
        
        for fid in file_ids:
            if fid in self.catalog["files"]:
                file_info = self.catalog["files"][fid]
                # Convert to ArtifactRef-compatible format
                artifact = {
                    "id": file_info.get("artifact_id", file_info["file_id"]),
                    "logical_name": file_info.get("logical_name", file_info.get("name", "")),
                    "filename": file_info.get("filename", file_info.get("name", "")),
                    "path": file_info["path"],
                    "file_type": file_info.get("file_type", "data"),
                    "mime_type": file_info.get("mime_type"),
                    "size_bytes": file_info.get("size_bytes", 0),
                    "sha256": file_info.get("sha256", file_info.get("checksum")),
                    "produced_by_task": file_info.get("produced_by_task", file_info.get("task_id")),
                    "created_at": file_info.get("created_at")
                }
                artifacts.append(artifact)
        
        return artifacts
    
    def get_artifact_by_logical_name(self, logical_name: str) -> Optional[Dict]:
        """
        Get artifact by logical name (e.g., 'batch_1').
        
        Args:
            logical_name: Logical name to search for
            
        Returns:
            Artifact dictionary or None
        """
        for file_info in self.catalog["files"].values():
            if file_info.get("logical_name") == logical_name:
                return {
                    "id": file_info.get("artifact_id", file_info["file_id"]),
                    "logical_name": file_info.get("logical_name", ""),
                    "filename": file_info.get("filename", file_info.get("name", "")),
                    "path": file_info["path"],
                    "file_type": file_info.get("file_type", "data"),
                    "mime_type": file_info.get("mime_type"),
                    "size_bytes": file_info.get("size_bytes", 0),
                    "sha256": file_info.get("sha256", file_info.get("checksum")),
                    "produced_by_task": file_info.get("produced_by_task", file_info.get("task_id")),
                    "created_at": file_info.get("created_at")
                }
        return None
    
    def get_artifacts_by_filename(self, filename: str) -> List[Dict]:
        """
        Get artifacts by exact filename match.
        
        Args:
            filename: Filename to search for
            
        Returns:
            List of matching artifacts
        """
        artifacts = []
        for file_info in self.catalog["files"].values():
            if file_info.get("filename") == filename or file_info.get("name") == filename:
                artifact = {
                    "id": file_info.get("artifact_id", file_info["file_id"]),
                    "logical_name": file_info.get("logical_name", ""),
                    "filename": file_info.get("filename", file_info.get("name", "")),
                    "path": file_info["path"],
                    "file_type": file_info.get("file_type", "data"),
                    "mime_type": file_info.get("mime_type"),
                    "size_bytes": file_info.get("size_bytes", 0),
                    "sha256": file_info.get("sha256", file_info.get("checksum")),
                    "produced_by_task": file_info.get("produced_by_task", file_info.get("task_id")),
                    "created_at": file_info.get("created_at")
                }
                artifacts.append(artifact)
        return artifacts

