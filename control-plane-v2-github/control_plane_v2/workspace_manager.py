"""
Workspace Manager - Handles run/phase/task directory structure

Directory Structure:
test_results/
  run_20251011_234500/              # RUN-SPECIFIC (timestamp)
    phase0/                         # PHASE 0: Classification
      classification_result.json
      side_tasks/
        task_1/
          result.json
        task_2/
          result.json
    phase1/                         # PHASE 1: Division
      division_result.json
      packages/
        independent_1.json
        sequential_last_1.json
    phase2/                         # PHASE 2: Execution
      independent_1_transform_email/    # TASK-SPECIFIC
        email_data.json
        result.json
      sequential_last_1_merge/
        validated_data.json
        result.json
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
import shutil

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Manages hierarchical workspace structure: run -> phase -> task"""
    
    def __init__(self, base_dir: Path = None):
        """
        Initialize workspace manager
        
        Args:
            base_dir: Base directory for all runs (default: runs/ in root)
        """
        if base_dir is None:
            # Point to root-level runs/ directory
            base_dir = Path(__file__).parent.parent / "runs"
        
        self.base_dir = Path(base_dir)
        self.run_dir: Optional[Path] = None
        self.phase_dirs: Dict[str, Path] = {}
        self.task_dirs: Dict[str, Path] = {}
    
    def create_run_directory(self, run_id: Optional[str] = None) -> Path:
        """
        Create a new run-specific directory
        
        Args:
            run_id: Optional run identifier (default: timestamp)
        
        Returns:
            Path to run directory
        """
        if run_id is None:
            run_id = datetime.now().strftime("run_%Y%m%d_%H%M%S")
        
        self.run_dir = self.base_dir / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Created run directory: {self.run_dir}")
        return self.run_dir
    
    def get_phase_directory(self, phase: str, create: bool = True) -> Path:
        """
        Get directory for a specific phase
        
        Args:
            phase: Phase name ('phase0', 'phase1', 'phase2')
            create: Whether to create directory if it doesn't exist
        
        Returns:
            Path to phase directory
        """
        if self.run_dir is None:
            raise ValueError("Run directory not created. Call create_run_directory() first.")
        
        if phase not in self.phase_dirs:
            phase_dir = self.run_dir / phase
            if create:
                phase_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created phase directory: {phase_dir}")
            self.phase_dirs[phase] = phase_dir
        
        return self.phase_dirs[phase]
    
    def get_task_directory(
        self,
        phase: str,
        task_id: str,
        create: bool = True
    ) -> Path:
        """
        Get directory for a specific task within a phase
        
        Args:
            phase: Phase name ('phase0', 'phase1', 'phase2')
            task_id: Task identifier
            create: Whether to create directory if it doesn't exist
        
        Returns:
            Path to task directory
        """
        phase_dir = self.get_phase_directory(phase, create=False)
        
        task_key = f"{phase}/{task_id}"
        if task_key not in self.task_dirs:
            task_dir = phase_dir / task_id
            if create:
                task_dir.mkdir(parents=True, exist_ok=True)
                logger.info(f"Created task directory: {task_dir}")
            self.task_dirs[task_key] = task_dir
        
        return self.task_dirs[task_key]
    
    def get_side_task_directory(
        self,
        task_num: int,
        create: bool = True
    ) -> Path:
        """
        Get directory for a Phase 0 side task
        
        Args:
            task_num: Side task number
            create: Whether to create directory if it doesn't exist
        
        Returns:
            Path to side task directory
        """
        phase0_dir = self.get_phase_directory('phase0', create=False)
        side_tasks_dir = phase0_dir / 'side_tasks'
        
        if create:
            side_tasks_dir.mkdir(parents=True, exist_ok=True)
        
        task_dir = side_tasks_dir / f"task_{task_num}"
        if create:
            task_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created side task directory: {task_dir}")
        
        return task_dir
    
    def copy_files_between_tasks(
        self,
        source_task_id: str,
        target_task_id: str,
        file_names: List[str],
        source_phase: str = 'phase2',
        target_phase: str = 'phase2'
    ) -> Dict[str, Path]:
        """
        Copy files from one task directory to another
        
        Args:
            source_task_id: Source task identifier
            target_task_id: Target task identifier
            file_names: List of file names to copy
            source_phase: Source phase (default: 'phase2')
            target_phase: Target phase (default: 'phase2')
        
        Returns:
            Dict mapping original filename to new path
        """
        source_dir = self.get_task_directory(source_phase, source_task_id, create=False)
        target_dir = self.get_task_directory(target_phase, target_task_id, create=True)
        
        copied_files = {}
        for file_name in file_names:
            source_file = source_dir / file_name
            target_file = target_dir / file_name
            
            if source_file.exists():
                shutil.copy2(source_file, target_file)
                copied_files[file_name] = target_file
                logger.info(f"Copied: {source_file} -> {target_file}")
            else:
                logger.warning(f"Source file not found: {source_file}")
        
        return copied_files
    
    def get_dependency_file_path(
        self,
        dependency_task_id: str,
        file_name: str,
        phase: str = 'phase2'
    ) -> Optional[Path]:
        """
        Get path to a file from a dependency task
        
        Args:
            dependency_task_id: Task ID that created the file
            file_name: Name of the file
            phase: Phase where the task ran (default: 'phase2')
        
        Returns:
            Path to the file, or None if not found
        """
        dep_dir = self.get_task_directory(phase, dependency_task_id, create=False)
        file_path = dep_dir / file_name
        
        if file_path.exists():
            return file_path
        
        logger.warning(f"Dependency file not found: {file_path}")
        return None
    
    def cleanup_run(self, keep_latest: int = 5):
        """
        Clean up old run directories, keeping only the latest N runs
        
        Args:
            keep_latest: Number of recent runs to keep
        """
        if not self.base_dir.exists():
            return
        
        # Get all run directories sorted by modification time
        run_dirs = sorted(
            [d for d in self.base_dir.iterdir() if d.is_dir() and d.name.startswith('run_')],
            key=lambda x: x.stat().st_mtime,
            reverse=True
        )
        
        # Delete old runs
        for old_run in run_dirs[keep_latest:]:
            logger.info(f"Cleaning up old run: {old_run}")
            shutil.rmtree(old_run)
    
    def get_user_uploads_directory(self, create: bool = True) -> Path:
        """
        Get the user_uploads directory for this run
        
        Args:
            create: Whether to create directory if it doesn't exist
        
        Returns:
            Path to user_uploads directory
        """
        if self.run_dir is None:
            raise ValueError("Run directory not created. Call create_run_directory() first.")
        
        user_uploads_dir = self.run_dir / "user_uploads"
        if create:
            user_uploads_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created user_uploads directory: {user_uploads_dir}")
        
        return user_uploads_dir
    
    def get_catalog_directory(self, create: bool = True) -> Path:
        """
        Get the catalog directory for this run
        
        Args:
            create: Whether to create directory if it doesn't exist
        
        Returns:
            Path to catalog directory
        """
        if self.run_dir is None:
            raise ValueError("Run directory not created. Call create_run_directory() first.")
        
        catalog_dir = self.run_dir / "catalog"
        if create:
            catalog_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created catalog directory: {catalog_dir}")
        
        return catalog_dir
    
    def get_vectordb_directory(self, create: bool = True) -> Path:
        """
        Get the vectordb directory for this run
        
        Args:
            create: Whether to create directory if it doesn't exist
        
        Returns:
            Path to vectordb directory
        """
        if self.run_dir is None:
            raise ValueError("Run directory not created. Call create_run_directory() first.")
        
        vectordb_dir = self.run_dir / "vectordb"
        if create:
            vectordb_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created vectordb directory: {vectordb_dir}")
        
        return vectordb_dir
    
    def get_summary(self) -> Dict:
        """
        Get summary of current workspace structure
        
        Returns:
            Dictionary with workspace information
        """
        summary = {
            "run_directory": str(self.run_dir) if self.run_dir else None,
            "phase_directories": {k: str(v) for k, v in self.phase_dirs.items()},
            "task_directories": {k: str(v) for k, v in self.task_dirs.items()}
        }
        
        # Add new directories if run exists
        if self.run_dir:
            summary["user_uploads"] = str(self.run_dir / "user_uploads")
            summary["catalog"] = str(self.run_dir / "catalog")
            summary["vectordb"] = str(self.run_dir / "vectordb")
        
        return summary

