"""
Orchestrator for Boss-Worker System
Reads execution plan from Phase 1 and delegates tasks to Boss-Worker pairs
"""

import asyncio
import logging
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from autogen_core import SingleThreadedAgentRuntime, TopicId
from control_plane_v2.agent_generator.model_clients import create_all_model_clients
from control_plane_v2.phase_2.task_agent_factory import TaskAgentFactory
from control_plane_v2.phase_2.task_agent_messages import TaskMessage, TaskCompletionMessage
from control_plane_v2.phase_2.orchestrator_phase2_v2 import FileCatalog, SimpleVectorStore, get_latest_run_path

logger = logging.getLogger(__name__)


class BossWorkerOrchestrator:
    """
    Orchestrator that manages task execution using Boss-Worker pairs.
    
    Workflow:
    1. Read execution plan from Phase 1
    2. For each task in plan:
       - Prepare resources (file paths, workspace)
       - Create/reuse Boss-Worker pair
       - Send TaskMessage to Boss
       - Wait for TaskCompletionMessage
       - Update catalog with results
       - Move to next task
    """
    
    def __init__(
        self,
        run_path: Path,
        execution_plan_path: Path,
        env_config: Dict[str, Any]
    ):
        """
        Initialize orchestrator.
        
        Args:
            run_path: Path to the run directory
            execution_plan_path: Path to the execution plan JSON
            env_config: Environment configuration with LLM credentials
        """
        self.run_path = run_path
        self.execution_plan_path = execution_plan_path
        self.env_config = env_config
        
        # Initialize directories
        self.phase2_dir = run_path / "phase2"
        self.phase2_dir.mkdir(parents=True, exist_ok=True)
        
        self.logs_dir = self.phase2_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize knowledge systems (in root run directory)
        catalog_path = run_path / "file_catalog.json"
        vector_store_path = run_path / "vector_store.pkl"
        
        self.catalog = FileCatalog(catalog_path)
        self.vector_store = SimpleVectorStore(vector_store_path)
        
        self.knowledge_systems = {
            "catalog": self.catalog,
            "vector_store": self.vector_store
        }
        
        # Runtime and factory
        self.runtime = None
        self.factory = None
        
        # Model clients
        self.gpt5_client = None
        self.claude_client = None
        
        # Execution state
        self.execution_plan = None
        self.current_task_idx = 0
        self.task_results = {}
        
        logger.info(f"Orchestrator initialized for run: {run_path}")
        logger.info(f"Execution plan: {execution_plan_path}")
    
    async def initialize(self):
        """Initialize runtime, clients, and factory"""
        logger.info("Initializing orchestrator...")
        
        # Create model clients
        clients = create_all_model_clients(self.env_config)
        # Boss uses GPT-5 High for complex planning and verification
        self.gpt5_client = clients.get('gpt-5-high', clients.get('gpt-5', clients.get('gpt-4.1', clients.get('gpt-4o'))))
        self.claude_client = clients.get('claude-4.5', clients.get('claude-3.5'))
        
        if not self.gpt5_client or not self.claude_client:
            raise RuntimeError("Required model clients not available!")
        
        logger.info(f"GPT-5 client: {self.gpt5_client}")
        logger.info(f"Claude client: {self.claude_client}")
        
        # Create runtime
        self.runtime = SingleThreadedAgentRuntime()
        
        # Create factory
        self.factory = TaskAgentFactory(self.runtime)
        
        # Start runtime
        self.runtime.start()
        logger.info("Runtime started")
        
        # Load execution plan
        with open(self.execution_plan_path, 'r') as f:
            self.execution_plan = json.load(f)
        
        # Extract tasks from plan (handle different formats)
        # Try new simple structure first: task_breakdown.tasks
        task_breakdown = self.execution_plan.get('task_breakdown', {})
        tasks = task_breakdown.get('tasks', [])
        
        if not tasks:
            # Fallback: Try old 4-category format
            sequential = task_breakdown.get('sequential_tasks', [])
            parallel = task_breakdown.get('parallel_tasks', [])
            merge = task_breakdown.get('merge_tasks', [])
            final = task_breakdown.get('final_tasks', [])
            tasks = sequential + parallel + merge + final
            
        if not tasks:
            # Last resort: Direct tasks array at root
            tasks = self.execution_plan.get('tasks', [])
        
        self.tasks = tasks
        logger.info(f"Loaded execution plan with {len(self.tasks)} tasks")
        if task_breakdown.get('tasks'):
            logger.info(f"  Using simple task list structure (all tasks with dependency-based execution)")
        else:
            logger.info(f"  Using legacy 4-category structure")
    
    async def execute_all_tasks(self):
        """Execute all tasks in the execution plan sequentially"""
        logger.info("=" * 80)
        logger.info("Starting task execution")
        logger.info("=" * 80)
        
        tasks = self.tasks
        
        if not tasks:
            logger.warning("No tasks found in execution plan!")
            return []
        
        for idx, task in enumerate(tasks):
            self.current_task_idx = idx
            task_id = task.get('task_id', task.get('id', 'unknown'))
            logger.info(f"\n{'=' * 80}")
            logger.info(f"Task {idx + 1}/{len(tasks)}: {task_id}")
            logger.info(f"{'=' * 80}")
            
            try:
                result = await self.execute_task(task)
                self.task_results[task_id] = result
                
                if result['status'] == 'success':
                    logger.info(f"[OK] Task {task_id} completed successfully")
                else:
                    logger.error(f"[FAIL] Task {task_id} failed: {result.get('error', 'Unknown error')}")
                    # Continue to next task even if one fails
            
            except Exception as e:
                logger.error(f"Error executing task {task_id}: {e}", exc_info=True)
                self.task_results[task_id] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        logger.info("\n" + "=" * 80)
        logger.info("All tasks completed")
        logger.info("=" * 80)
        
        # Return results as a list
        results = []
        for task_id, result in self.task_results.items():
            results.append({
                'task_id': task_id,
                'status': result.get('status', 'unknown'),
                'files_created': result.get('files_created', []),
                'error': result.get('error', None)
            })
        
        # Print summary
        self.print_summary()
        
        return results
    
    async def execute_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a single task using Boss-Worker pair.
        
        Args:
            task: Task definition from execution plan
        
        Returns:
            Task result dictionary
        """
        task_id = task.get('task_id', task.get('id', 'unknown'))
        task_description = task.get('description', '')
        
        # Extract input files (handle different formats)
        input_files = task.get('input_files', [])
        if not input_files:
            work_scope = task.get('work_scope', {})
            input_files = work_scope.get('inputs', [])
        
        logger.info(f"Executing task: {task_id}")
        logger.info(f"Description: {task_description}")
        logger.info(f"Input files: {input_files}")
        
        # 1. Prepare workspace
        task_workspace = self.phase2_dir / task_id
        task_workspace.mkdir(parents=True, exist_ok=True)
        logger.info(f"Task workspace: {task_workspace}")
        
        # 2. Extract input file names (Boss will resolve paths via catalog)
        input_file_names = []
        for file_item in input_files:
            # Handle both string and dict formats
            if isinstance(file_item, dict):
                file_name = file_item.get('path', '')
            else:
                file_name = file_item
            
            # Remove leading './' if present
            file_name = file_name.lstrip('./')
            if file_name:
                input_file_names.append(file_name)
        
        logger.info(f"Input files requested: {input_file_names}")
        logger.info("Boss will resolve file paths using the catalog")
        
        # 3. Create Boss-Worker pair
        logger.info("Creating Boss-Worker pair...")
        boss_topic, worker_topic = await self.factory.create_boss_worker_pair(
            run_id=task_id,
            workspace_path=task_workspace,
            knowledge_systems=self.knowledge_systems,
            gpt5_client=self.gpt5_client,
            claude_client=self.claude_client
        )
        
        logger.info(f"Boss-Worker pair created: {boss_topic}")
        
        # 4. Prepare task context with knowledge base instructions
        metadata = self.execution_plan.get('metadata', {})
        dependencies = task.get('dependencies', [])
        
        # Build knowledge base instructions
        kb_instructions = []
        if self.current_task_idx == 0:
            # First task: tell Boss to store learnings
            kb_instructions.append("IMPORTANT: After completing all subtasks, use the knowledge base tool to store key learnings, insights, data schemas, and statistical findings for future tasks.")
        elif dependencies:
            # Subsequent tasks with dependencies: tell Boss to query knowledge base
            kb_instructions.append(f"IMPORTANT: This task depends on previous task(s): {', '.join(dependencies)}.")
            kb_instructions.append("Use the knowledge base tool to retrieve relevant information about data schemas, distributions, patterns, and insights from previous tasks.")
            kb_instructions.append("Query the knowledge base BEFORE planning your subtasks to understand what information is available.")
        
        task_context = {
            'execution_plan': metadata.get('description', 'Task execution'),
            'task_index': self.current_task_idx + 1,
            'total_tasks': len(self.tasks),
            'previous_results': self.task_results,
            'work_scope': task.get('work_scope', {}),
            'dependencies': dependencies,
            'knowledge_base_instructions': kb_instructions,
            'additional_instructions': self.execution_plan.get('additional_instructions', '')  # General instructions from manifest
        }
        
        # 5. Extract expected outputs
        expected_outputs = task.get('expected_output_files', [])
        if not expected_outputs:
            work_scope = task.get('work_scope', {})
            outputs_desc = work_scope.get('outputs_description', '')
            # For now, use a generic list if not specified
            expected_outputs = ['task_files.json', 'output_files/']
        
        # 6. Send TaskMessage to Boss
        task_message = TaskMessage(
            task_id=task_id,
            task_description=task_description,
            input_files=input_file_names,  # Boss will resolve via catalog
            expected_outputs=expected_outputs,
            context=task_context,
            credentials=self.execution_plan.get('credentials', {})  # Pass credentials from execution plan
        )
        
        logger.info("Sending TaskMessage to Boss...")
        await self.runtime.publish_message(
            task_message,
            topic_id=TopicId(boss_topic, source="orchestrator")
        )
        
        # 7. Wait for TaskCompletionMessage
        logger.info("Waiting for task completion...")
        
        # For now, we'll use a simple polling mechanism
        # In production, this would be handled by a message handler
        completion_result = await self.wait_for_completion(task_id, timeout=3600)
        
        # 8. Update catalog with created files
        if completion_result['status'] == 'success':
            for file_item in completion_result.get('files_created', []):
                # Handle both dict format {"filename": ..., "absolute_path": ...} and string format
                if isinstance(file_item, dict):
                    file_name = file_item.get('filename', '')
                    absolute_path = file_item.get('absolute_path', '')
                else:
                    file_name = file_item
                    absolute_path = str(task_workspace / file_name)
                
                # Verify file exists before adding to catalog
                if Path(absolute_path).exists():
                    self.catalog.add_file(
                        relative_path=file_name,
                        absolute_path=absolute_path,
                        description=f"Created by task {task_id}"
                    )
                    logger.info(f"Added to catalog: {file_name} -> {absolute_path}")
        
        return completion_result
    
    async def wait_for_completion(self, task_id: str, timeout: int = 3600) -> Dict[str, Any]:
        """
        Wait for task completion.
        
        This is a simplified implementation. In production, this would be
        handled by subscribing to TaskCompletionMessage.
        
        Args:
            task_id: Task identifier
            timeout: Maximum wait time in seconds
        
        Returns:
            Completion result dictionary
        """
        # For now, we'll simulate waiting by checking for task_files.json
        task_workspace = self.phase2_dir / task_id
        task_files_path = task_workspace / "task_files.json"
        
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if task_files_path.exists():
                # Read task_files.json
                with open(task_files_path, 'r') as f:
                    task_files = json.load(f)
                
                return {
                    'status': 'success',
                    'files_created': task_files.get('output_files', []),
                    'summary': task_files.get('summary', 'Task completed'),
                    'task_files': task_files
                }
            
            # Wait a bit before checking again
            await asyncio.sleep(5)
        
        # Timeout
        return {
            'status': 'timeout',
            'error': f'Task {task_id} did not complete within {timeout} seconds'
        }
    
    def print_summary(self):
        """Print execution summary"""
        logger.info("\n" + "=" * 80)
        logger.info("EXECUTION SUMMARY")
        logger.info("=" * 80)
        
        total_tasks = len(self.task_results)
        successful = sum(1 for r in self.task_results.values() if r['status'] == 'success')
        failed = total_tasks - successful
        
        logger.info(f"Total tasks: {total_tasks}")
        logger.info(f"Successful: {successful}")
        logger.info(f"Failed: {failed}")
        logger.info("")
        
        for task_id, result in self.task_results.items():
            status_symbol = "[OK]" if result['status'] == 'success' else "[FAIL]"
            logger.info(f"{status_symbol} {task_id}: {result['status']}")
            if result['status'] == 'success':
                files_created = len(result.get('files_created', []))
                logger.info(f"   Files created: {files_created}")
        
        logger.info("=" * 80)
    
    async def cleanup(self):
        """Cleanup resources"""
        if self.runtime:
            await self.runtime.stop()
        logger.info("Orchestrator cleanup complete")


async def main():
    """Main entry point for orchestrator"""
    import sys
    
    # Add project root to path
    project_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(project_root))
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    
    # Get project root
    project_root = Path(__file__).parent.parent.parent
    
    # Load environment config
    env_info_path = project_root / "env_info.json"
    with open(env_info_path, 'r') as f:
        env_config = json.load(f)
    
    # Get latest run path
    run_path = get_latest_run_path()
    
    if not run_path:
        logger.error("No run directory found!")
        return
    
    # Get execution plan path
    execution_plan_path = run_path / "phase1" / "simple_eda_execution_plan.json"
    
    if not execution_plan_path.exists():
        logger.error(f"Execution plan not found: {execution_plan_path}")
        return
    
    # Create orchestrator
    orchestrator = BossWorkerOrchestrator(
        run_path=run_path,
        execution_plan_path=execution_plan_path,
        env_config=env_config
    )
    
    try:
        # Initialize
        await orchestrator.initialize()
        
        # Execute all tasks
        await orchestrator.execute_all_tasks()
    
    finally:
        # Cleanup
        await orchestrator.cleanup()


if __name__ == "__main__":
    asyncio.run(main())

