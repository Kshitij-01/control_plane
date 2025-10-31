"""
Side Task Solver - Executes verification tasks using Agent Generator
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime

from autogen_core.tools import FunctionTool

from ..agent_generator.factory import AgentFactory
from ..agent_generator.messages import AgentGenerationRequest, AgentExecutionRequest
from .models import ConnectionInfo

logger = logging.getLogger(__name__)


class SideTaskSolver:
    """
    Solves side tasks by generating specialized agents for each verification task.
    Side tasks run in parallel (max 3 concurrent) and save their results to individual JSON files.
    """
    
    def __init__(self, agent_factory: AgentFactory, workspace_dir: Path, max_concurrent: int = 3):
        """
        Initialize Side Task Solver
        
        Args:
            agent_factory: Factory for generating and executing agents
            workspace_dir: Directory to save side task results
            max_concurrent: Maximum number of concurrent agents (default: 3)
        """
        self._factory = agent_factory
        self._workspace = workspace_dir
        self._max_concurrent = max_concurrent
        self._workspace.mkdir(parents=True, exist_ok=True)
        logger.info(f"SideTaskSolver initialized with workspace: {self._workspace}")
        logger.info(f"Max concurrent agents: {self._max_concurrent}")
    
    async def solve_all_tasks(
        self,
        side_tasks: List[Dict[str, Any]],
        connections: List[ConnectionInfo],
        additional_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute all side tasks in parallel using generated agents
        
        Args:
            side_tasks: List of side task definitions from classifier
            connections: Database/API connections
            additional_context: Additional context from task manifest
            
        Returns:
            Summary of all side task results
        """
        logger.info("="*80)
        logger.info("SIDE TASK SOLVER - EXECUTING VERIFICATION TASKS")
        logger.info("="*80)
        logger.info(f"Total side tasks: {len(side_tasks)}")
        logger.info(f"Execution mode: PARALLEL")
        logger.info("")
        
        # Create agent generation requests for each side task
        requests = []
        for idx, task in enumerate(side_tasks, 1):
            request = self._create_agent_request(idx, task, connections, additional_context)
            requests.append((idx, task, request))
        
        # Execute all tasks with concurrency limit
        logger.info(f"[Stage 1/2] Generating {len(requests)} verification agents...")
        logger.info(f"Concurrency limit: {self._max_concurrent} agents at a time")
        start_time = datetime.now()
        
        # Use semaphore to limit concurrent execution
        semaphore = asyncio.Semaphore(self._max_concurrent)
        
        async def execute_with_semaphore(idx, task, request):
            async with semaphore:
                return await self._execute_side_task(idx, task, request)
        
        results = await asyncio.gather(
            *[execute_with_semaphore(idx, task, request) for idx, task, request in requests],
            return_exceptions=True
        )
        
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"[Stage 2/2] All tasks completed in {duration:.1f}s")
        logger.info("")
        
        # Summarize results
        summary = self._summarize_results(results, side_tasks)
        
        logger.info("="*80)
        logger.info("SIDE TASK RESULTS SUMMARY")
        logger.info("="*80)
        logger.info(f"Total: {summary['total']}")
        logger.info(f"Success: {summary['success']}")
        logger.info(f"Failed: {summary['failed']}")
        logger.info(f"Critical failures: {summary['critical_failures']}")
        logger.info("="*80)
        logger.info("")
        
        return summary
    
    def _create_agent_request(
        self,
        task_num: int,
        task: Dict[str, Any],
        connections: List[ConnectionInfo],
        additional_context: Dict[str, Any]
    ) -> AgentGenerationRequest:
        """Create agent generation request for a side task"""
        
        # Build context - pass through everything as-is, no assumptions
        # This is a GENERAL control plane - don't assume database connections,
        # REST APIs, file systems, or ANY specific structure
        context = {
            **additional_context,
            # Convert connections to raw dict format - let agent interpret the structure
            "available_resources": [conn.model_dump() for conn in connections] if connections else []
        }
        
        logger.debug(f"[Task {task_num}] Provided {len(connections)} resources to agent (no structural assumptions)")
        
        # Direct instructions - agent must generate code immediately
        request = AgentGenerationRequest(
            request_id=f"side_task_{task_num}",
            task_description=f"""
========================================
MANDATORY REQUIREMENT - CODE EXECUTION
========================================
You MUST write and execute Python code in your VERY FIRST response.
Do NOT explain, plan, or describe - START WITH CODE IMMEDIATELY.

TASK: {task['description']}

PRIORITY: {task.get('priority', 'unknown')}
ESTIMATED DURATION: {task.get('estimated_duration', 'unknown')}

You have full autonomy to accomplish this task using:
- Python code execution (USE THIS IMMEDIATELY)
- Web search for solutions
- Any available packages (install with pip if needed)
- All resources provided in the context

========================================
CRITICAL: TRY MULTIPLE METHODS IF ONE FAILS
========================================
If a connection method or library fails, TRY ALTERNATIVES:

For MySQL connections:
1. Try mysql-connector-python first
2. If that fails, try pymysql
3. Try different SSL/TLS configurations

For PostgreSQL connections:
1. Try psycopg2 first
2. If that fails, try psycopg2-binary
3. Try different sslmode settings (require, prefer, disable)

For SQL Server/Azure SQL connections:
1. Try pyodbc with ODBC Driver 17 for SQL Server
2. If that fails, try pymssql
3. Try different authentication methods

DO NOT give up after one failure - try at least 2-3 alternative approaches!

================================================================================
CRITICAL: SAVE YOUR RESULTS USING THE PROVIDED HELPER
================================================================================
After completing your verification, YOU MUST save results using task_helper.

MANDATORY - ADD THIS IMPORT AT THE TOP OF YOUR CODE:
```python
from task_helper import save_verification_result
```

THEN CALL IT AT THE END:
```python
# After your verification code succeeds:
save_verification_result(
    success=True,
    message="Database connection successful, table 'xyz' exists"
)

# Or if verification fails:
save_verification_result(
    success=False,
    message="Could not connect to database: connection timeout"
)
```

CRITICAL RULES:
- IMPORT: from task_helper import save_verification_result
- Call it with success=True if passed, success=False if failed
- Provide a clear message explaining what you checked
- This is your FINAL action after all verification code
""",
            goal=task['description'],
            context=context,
            success_criteria=f"Task accomplished: {task['description']}",
            max_iterations=7  # Increased for complex tasks (db connections, multiple fallbacks)
        )
        
        return request
    
    def _create_helper_module(self, agent_workspace: Path, task_num: int):
        """Create a helper Python module in agent's workspace
        
        LocalCommandLineCodeExecutor runs code in a subprocess, so we can't
        inject functions directly. Instead, we create a module file that
        agents can import.
        """
        helper_code = f'''"""Helper module for side task {task_num}"""
import json
from pathlib import Path

def save_verification_result(success, message):
    """Save the side task verification result
    
    Args:
        success: True if verification passed, False if it failed
        message: Description of what was verified and the result
        
    Returns:
        Confirmation message
    """
    result = {{
        "success": success,
        "message": message
    }}
    # Save to the side_tasks directory (grandparent.parent / side_tasks)
    # Structure: phase0/agents/agent_XXX/task_helper.py
    # Target:    phase0/side_tasks/side_task_N.json
    result_file = Path(__file__).parent.parent.parent / "side_tasks" / "side_task_{task_num}.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
    return f"Result saved successfully to {{result_file.name}}"
'''
        helper_file = agent_workspace / "task_helper.py"
        with open(helper_file, 'w', encoding='utf-8') as f:
            f.write(helper_code)
        
        logger.debug(f"Created helper module at {helper_file}")
    
    async def _execute_side_task(
        self,
        task_num: int,
        task: Dict[str, Any],
        request: AgentGenerationRequest
    ) -> Dict[str, Any]:
        """Execute a single side task"""
        task_id = task['id']
        logger.info(f"[Task {task_num}] Starting: {task_id}")
        logger.info(f"[Task {task_num}] {task['description'][:60]}...")
        
        try:
            # Generate agent
            gen_result = await self._factory.generate_agent(request)
            
            if gen_result.status != "success":
                logger.error(f"[Task {task_num}] Agent generation failed: {gen_result.error}")
                return {
                    "task_id": task_id,
                    "task_num": task_num,
                    "success": False,
                    "is_critical": task.get('blocking', False),
                    "message": f"Agent generation failed: {gen_result.error}"
                }
            
            # Create helper module in agent's workspace (so code can import it)
            agent_workspace = self._factory._agent_workspaces[gen_result.agent_id]
            self._create_helper_module(agent_workspace, task_num)
            
            # Execute agent
            result = await self._factory.execute_agent(
                agent_id=gen_result.agent_id,
                message=f"Execute verification task: {task['description']}",
                verify=False
            )
            
            # Check if result file was created - try multiple locations
            import shutil
            from pathlib import Path
            
            result_file = self._workspace / f"side_task_{task_num}.json"
            found = False
            
            # Location 1: Agent's designated workspace subdirectory
            agent_workspace = self._workspace / gen_result.agent_id
            agent_result_file = agent_workspace / f"side_task_{task_num}.json"
            
            if agent_result_file.exists():
                shutil.copy2(agent_result_file, result_file)
                logger.debug(f"[Task {task_num}] Copied result file from {agent_result_file}")
                found = True
            
            # Location 1.5: AgentFactory's base workspace (phase0/agents/{agent_id})
            elif (self._workspace.parent / "agents" / gen_result.agent_id / f"side_task_{task_num}.json").exists():
                agents_path = self._workspace.parent / "agents" / gen_result.agent_id / f"side_task_{task_num}.json"
                shutil.copy2(agents_path, result_file)
                logger.info(f"[Task {task_num}] Copied result file from AgentFactory workspace: {agents_path}")
                found = True
            
            # Location 2: Test results directory (where executor might save)
            elif (self._workspace.parent / gen_result.agent_id / f"side_task_{task_num}.json").exists():
                alt_path = self._workspace.parent / gen_result.agent_id / f"side_task_{task_num}.json"
                shutil.copy2(alt_path, result_file)
                logger.debug(f"[Task {task_num}] Copied result file from {alt_path}")
                found = True
            
            # Location 3: Search recursively in workspace area
            elif not found:
                # Search from phase directory (go up from side_tasks to phase0)
                search_root = self._workspace.parent
                logger.debug(f"[Task {task_num}] Searching for result file from: {search_root}")
                for json_file in search_root.rglob(f"side_task_{task_num}.json"):
                    if gen_result.agent_id in str(json_file):
                        shutil.copy2(json_file, result_file)
                        logger.info(f"[Task {task_num}] Found and copied result file from {json_file}")
                        found = True
                        break
            
            # Location 4: Look for ANY JSON file in agent's workspace with "success" field
            # (handles cases where agent used wrong filename like "verification_result.json")
            if not found:
                agent_dir = self._workspace.parent / "agents" / gen_result.agent_id
                if agent_dir.exists():
                    logger.debug(f"[Task {task_num}] Searching for any JSON file in agent workspace: {agent_dir}")
                    for json_file in agent_dir.glob("*.json"):
                        try:
                            with open(json_file, 'r') as f:
                                data = json.load(f)
                                # Check if it looks like a side task result (has "success" field)
                                if "success" in data:
                                    shutil.copy2(json_file, result_file)
                                    logger.warning(f"[Task {task_num}] Found result in incorrectly named file: {json_file.name} -> copying to {result_file.name}")
                                    found = True
                                    break
                        except (json.JSONDecodeError, IOError):
                            # Not a valid JSON file, skip it
                            continue
            
            if result_file.exists():
                with open(result_file, 'r') as f:
                    task_result = json.load(f)
                    
                    # Try to get success field, or infer it from other fields
                    if 'success' in task_result:
                        success = task_result['success']
                    else:
                        # Infer success from other fields if success field missing
                        success = self._infer_success(task_result)
                        logger.warning(f"[Task {task_num}] 'success' field missing, inferred as: {success}")
                        # Add inferred success to result for consistency
                        task_result['success'] = success
                    
                    if success:
                        logger.info(f"[Task {task_num}] SUCCESS")
                    else:
                        logger.warning(f"[Task {task_num}] FAILED: {task_result.get('message', 'No message')}")
                    
                    return {
                        'task_num': task_num,
                        'task_id': task_id,
                        'success': success,
                        'is_critical': task.get('blocking', False),
                        'result': task_result
                    }
            else:
                logger.error(f"[Task {task_num}] ERROR: Result file not created")
                return {
                    'task_num': task_num,
                    'task_id': task_id,
                    'success': False,
                    'is_critical': task.get('blocking', False),
                    'error': 'Result file not created'
                }
                
        except Exception as e:
            logger.error(f"[Task {task_num}] EXCEPTION: {str(e)}")
            return {
                'task_num': task_num,
                'task_id': task_id,
                'success': False,
                'is_critical': task.get('blocking', False),
                'error': str(e)
            }
    
    def _infer_success(self, task_result: Dict[str, Any]) -> bool:
        """
        Infer success status from task result when 'success' field is missing.
        
        Looks for indicators of success/failure in other fields.
        """
        # Check for explicit failure indicators
        failure_indicators = [
            ('error' in task_result and task_result.get('error')),
            ('errors' in task_result and bool(task_result.get('errors'))),  # Non-empty errors list
            ('failed' in task_result and task_result.get('failed')),
            ('status' in task_result and str(task_result.get('status')).lower() in ['failed', 'error', 'fail']),
            ('verification_status' in task_result and str(task_result.get('verification_status')).lower() in ['failed', 'error', 'fail']),
        ]
        
        if any(failure_indicators):
            return False
        
        # Check for explicit success indicators (case-insensitive)
        status_value = task_result.get('status', task_result.get('verification_status', ''))
        if status_value and str(status_value).lower() in ['success', 'passed', 'ok', 'pass', 'successful']:
            logger.info(f"Success inferred from status field: {status_value}")
            return True
        
        # Check for nested "checks" dict (e.g., {"checks": {"file_exists": true, "valid_json": true}})
        checks_dict = task_result.get('checks', {})
        if isinstance(checks_dict, dict):
            check_values = [v for v in checks_dict.values() if isinstance(v, bool)]
            if check_values and all(check_values):
                logger.info(f"Success inferred from checks dict: all {len(check_values)} checks passed")
                return True
        
        # Check for positive verification results at top level
        # e.g., {"file_exists": true, "valid_json": true, "file_readable": true}
        all_values = []
        for key, value in task_result.items():
            if key in ['message', 'details', 'timestamp', 'task_id', 'task', 'file_path', 'recommendations', 'json_content_preview']:
                continue  # Skip descriptive/metadata fields
            if isinstance(value, bool):
                all_values.append(value)
        
        # If we have boolean checks at top level, success = all are True
        if all_values and all(all_values):
            logger.info(f"Success inferred from top-level boolean fields: all {len(all_values)} checks passed")
            return True
        
        # Check for other explicit success indicators
        success_indicators = [
            ('connected' in task_result and task_result.get('connected')),
            ('verified' in task_result and task_result.get('verified')),
            ('valid' in task_result and task_result.get('valid')),
        ]
        
        if any(success_indicators):
            return True
        
        # Default to False if we can't determine (conservative approach)
        logger.warning("Could not infer success from result fields, defaulting to False")
        return False
    
    def _summarize_results(
        self,
        results: List[Dict[str, Any]],
        tasks: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Summarize side task results"""
        
        total = len(results)
        success_count = sum(1 for r in results if isinstance(r, dict) and r.get('success'))
        failed_count = total - success_count
        critical_failures = [
            r for r in results 
            if isinstance(r, dict) and not r.get('success') and r.get('is_critical')
        ]
        
        return {
            'total': total,
            'success': success_count,
            'failed': failed_count,
            'critical_failures': len(critical_failures),
            'critical_failure_details': critical_failures,
            'all_results': results
        }

