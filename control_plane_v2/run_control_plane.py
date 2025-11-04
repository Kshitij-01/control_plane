"""
Universal Control Plane Entry Point

This is the ONLY script you need to run. Just provide a manifest file.
The system automatically adapts to:
- Data migration tasks (DB to DB)
- Synthetic data generation (file-based analysis)
- ETL transformations
- Any other data workflow

Usage:
    python -m control_plane_v2.run_control_plane --manifest path/to/manifest.json
"""

import asyncio
import json
import logging
import sys
import argparse
from pathlib import Path
from datetime import datetime

# CRITICAL: Set Windows event loop policy for AutoGen code execution
# This is required for LocalCommandLineCodeExecutor to work properly on Windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from autogen_core import SingleThreadedAgentRuntime
from autogen_ext.code_executors import LocalCommandLineCodeExecutor

# Phase 0 imports
from control_plane_v2.phase_0.task_classifier import TaskClassifier
from control_plane_v2.phase_0.messages import TaskAnalysisRequest
from control_plane_v2.phase_0.models import FileInfo, ConnectionInfo
from control_plane_v2.phase_0.side_task_solver import SideTaskSolver
from control_plane_v2.phase_0.side_task_verifier import SideTaskVerifier

# Phase 1 imports
from control_plane_v2.phase_1.collaborative_divider_v2 import CollaborativeTaskDivider
from control_plane_v2.phase_1.messages import TaskDivisionRequest

# Agent generation imports
from control_plane_v2.agent_generator.model_clients import create_all_model_clients
from control_plane_v2.agent_generator.factory import AgentFactory
from control_plane_v2.agent_generator.generator import AgentGeneratorAgent
from control_plane_v2.workspace_manager import WorkspaceManager

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def clean_manifest_for_llms(manifest):
    """
    Remove instruction fields from manifest before passing to LLMs.
    Keep DATA (connections, descriptions, paths), remove INSTRUCTIONS (hints, configs).
    This prevents confusion from layered instructions across phases.
    """
    cleaned = manifest.copy()
    
    # Remove instruction fields that are for control plane, not LLMs
    instruction_fields = [
        'instructions',  # Explicit instruction arrays
        'execution_hints',  # Phase-specific hints
        'metadata'  # Internal metadata
    ]
    
    for field in instruction_fields:
        cleaned.pop(field, None)
    
    # Clean nested objects
    if 'generation_strategy' in cleaned and isinstance(cleaned['generation_strategy'], dict):
        strategy = cleaned['generation_strategy'].copy()
        strategy.pop('instructions', None)
        cleaned['generation_strategy'] = strategy
    
    if 'transformation_config' in cleaned and isinstance(cleaned['transformation_config'], dict):
        # Keep ONLY data fields (mapping_plan_path), remove control flags
        config = cleaned['transformation_config'].copy()
        control_flags = ['skip_side_tasks', 'max_independent_tasks', 'file_format', 'use_csv']
        for flag in control_flags:
            config.pop(flag, None)
        cleaned['transformation_config'] = config if config else {}
    
    if 'quality_requirements' in cleaned and isinstance(cleaned['quality_requirements'], dict):
        quality = cleaned['quality_requirements'].copy()
        quality.pop('instructions', None)
        cleaned['quality_requirements'] = quality
    
    return cleaned


def parse_manifest_connections(manifest, project_root):
    """
    Extract connections from manifest (if present).
    Handles both formats:
    - Top-level 'connections' array (legacy)
    - Nested source/target structure (current)
    Returns list of ConnectionInfo objects.
    """
    connections = []
    
    # Try top-level 'connections' array (legacy format)
    connections_data = manifest.get('connections', [])
    for conn in connections_data:
        connections.append(ConnectionInfo(
            id=conn.get('name', conn.get('id', f"conn_{len(connections)}")),
            type=conn.get('type', 'unknown'),
            host=conn.get('host'),
            port=conn.get('port'),
            database=conn.get('database'),
            credentials={
                'username': conn.get('username'),
                'password': conn.get('password'),
                'sslmode': conn.get('sslmode'),
                'ssl': conn.get('ssl'),
                'driver': conn.get('driver'),
                'encrypt': conn.get('encrypt'),
                'trust_server_certificate': conn.get('trust_server_certificate')
            },
            description=f"{conn.get('type', 'unknown')} connection: {conn.get('host', 'N/A')}"
        ))
    
    # Try nested source/target structure (current format)
    if 'source' in manifest and 'connection' in manifest['source']:
        source_conn = manifest['source']['connection']
        source_type = manifest['source'].get('type', 'unknown')
        connections.append(ConnectionInfo(
            id='source',
            type=source_type,
            host=source_conn.get('host', source_conn.get('server')),
            port=source_conn.get('port'),
            database=source_conn.get('database'),
            credentials={
                'username': source_conn.get('username'),
                'password': source_conn.get('password'),
                'sslmode': source_conn.get('sslmode'),
                'ssl': source_conn.get('ssl'),
                'schema': source_conn.get('schema'),
                'table': source_conn.get('table')
            },
            description=f"Source {source_type} connection: {source_conn.get('host', source_conn.get('server', 'N/A'))}"
        ))
    
    if 'target' in manifest and 'connection' in manifest['target']:
        target_conn = manifest['target']['connection']
        target_type = manifest['target'].get('type', 'unknown')
        connections.append(ConnectionInfo(
            id='target',
            type=target_type,
            host=target_conn.get('host', target_conn.get('server')),
            port=target_conn.get('port'),
            database=target_conn.get('database'),
            credentials={
                'username': target_conn.get('username'),
                'password': target_conn.get('password'),
                'driver': target_conn.get('driver'),
                'encrypt': target_conn.get('encrypt'),
                'trust_server_certificate': target_conn.get('trust_server_certificate'),
                'table': target_conn.get('table')
            },
            description=f"Target {target_type} connection: {target_conn.get('host', target_conn.get('server', 'N/A'))}"
        ))
    
    return connections


def parse_manifest_files(manifest, project_root):
    """
    Extract file references from manifest.
    Returns list of FileInfo objects.
    Handles various manifest structures:
    - mapping_plan_path (for migrations)
    - source.file_info (for file-based tasks)
    - files[] array (for explicit file lists)
    """
    files = []
    
    # Check for mapping_plan_path (migration tasks)
    if 'mapping_plan_path' in manifest:
        mapping_plan_path = Path(manifest['mapping_plan_path'])
        mapping_plan_absolute = (project_root / mapping_plan_path).resolve()
        files.append(FileInfo(
            path=str(mapping_plan_absolute),
            size_mb=0.001,
            file_type="json",
            description="Transformation mapping plan"
        ))
    
    # Check for source.file_info (synthetic generation, file analysis)
    if 'source' in manifest and 'file_info' in manifest['source']:
        source_info = manifest['source']['file_info']
        source_path = Path(source_info['path'])
        source_absolute = (project_root / source_path).resolve()
        files.append(FileInfo(
            path=str(source_absolute),
            size_mb=source_info.get('size_mb', 0.1),
            file_type=source_info.get('format', 'csv'),
            description=source_info.get('description', f"Source data: {source_info.get('total_rows', 'N/A')} rows")
        ))
    
    # Check for explicit files array
    if 'files' in manifest:
        for file_data in manifest['files']:
            file_path = Path(file_data['path'])
            file_absolute = (project_root / file_path).resolve()
            files.append(FileInfo(
                path=str(file_absolute),
                size_mb=file_data.get('size_mb', 0.1),
                file_type=file_data.get('type', 'unknown'),
                description=file_data.get('description', 'Input file')
            ))
    
    return files


def build_additional_context(manifest, project_root, files):
    """
    Build additional_context dict for Phase 0.
    Extracts ALL relevant information from manifest.
    """
    context = {
        "manifest": manifest,
        "project_root": str(project_root)
    }
    
    # Add file paths
    for file_info in files:
        if 'mapping' in file_info.description.lower():
            context["mapping_plan_absolute_path"] = file_info.path
        elif 'source' in file_info.description.lower():
            context["source_file_absolute_path"] = file_info.path
    
    # Migration-specific fields
    if 'source_table' in manifest:
        context["source_table"] = manifest['source_table']
    if 'target_table' in manifest:
        context["target_table"] = manifest['target_table']
    if 'transformation_config' in manifest:
        context["transformation_config"] = manifest['transformation_config']
    
    # Synthetic generation fields
    if 'generation_strategy' in manifest:
        context["generation_strategy"] = manifest['generation_strategy']
    if 'source' in manifest and 'columns' in manifest['source']:
        context["source_columns"] = manifest['source']['columns']
    if 'generation_strategy' in manifest and 'target_rows' in manifest['generation_strategy']:
        context["target_rows"] = manifest['generation_strategy']['target_rows']
    if 'output_requirements' in manifest:
        context["output_requirements"] = manifest['output_requirements']
    if 'quality_requirements' in manifest:
        context["quality_requirements"] = manifest['quality_requirements']
    
    return context


async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Universal Control Plane - Run any data workflow')
    parser.add_argument('--manifest', type=str, required=True, help='Path to manifest JSON file')
    args = parser.parse_args()
    
    logger.info("="*80)
    logger.info(" "*20 + "CONTROL PLANE - UNIVERSAL ENTRY POINT")
    logger.info("="*80)
    logger.info(f"\n  Manifest: {args.manifest}")
    logger.info("  The system will automatically adapt to your task type\n")
    logger.info("="*80)
    
    # ==================================================
    # SETUP
    # ==================================================
    logger.info("\n[1/12] Loading manifest and environment config...")
    project_root = Path.cwd()
    
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        logger.error(f"Manifest file not found: {manifest_path}")
        sys.exit(1)
    
    with open(manifest_path, 'r') as f:
        manifest = json.load(f)
    
    # Look for env_info.json in the project root (parent of control_plane_v2)
    env_info_path = Path(__file__).parent.parent / "env_info.json"
    if not env_info_path.exists():
        logger.error(f"env_info.json not found at: {env_info_path}")
        logger.error("Please create env_info.json in the project root with API credentials")
        sys.exit(1)
    
    with open(env_info_path, 'r') as f:
        env_config = json.load(f)
    
    import os
    full_env_config = {
        **env_config,
        'AWS_ACCESS_KEY_ID': os.getenv('AWS_ACCESS_KEY_ID'),
        'AWS_SECRET_ACCESS_KEY': os.getenv('AWS_SECRET_ACCESS_KEY'),
        'TAVILY_API_KEY': os.getenv('TAVILY_API_KEY')
    }
    
    # Detect task type
    task_id = manifest.get('task_id', manifest.get('task_name', 'unknown_task'))
    task_type = manifest.get('task_type', 'data_workflow')
    description = manifest.get('description', manifest.get('task_description', 'Data processing task'))
    
    logger.info(f"  Task ID: {task_id}")
    logger.info(f"  Task Type: {task_type}")
    logger.info(f"  Description: {description[:80]}...")
    
    # [2/12] Create workspace manager
    logger.info("\n[2/12] Creating run-specific workspace...")
    workspace_manager = WorkspaceManager()
    run_dir = workspace_manager.create_run_directory()
    logger.info(f"  Run directory: {run_dir}")
    
    # Copy user uploads from template to run directory
    import shutil
    template_uploads = Path(__file__).parent.parent / "runs" / "template" / "user_uploads"
    run_uploads = workspace_manager.get_user_uploads_directory(create=True)
    
    if template_uploads.exists():
        # Copy all files from template (flat structure)
        file_count = 0
        for file_path in template_uploads.glob("*"):
            if file_path.is_file():
                shutil.copy2(file_path, run_uploads / file_path.name)
                file_count += 1
        logger.info(f"  Copied {file_count} file(s) from template to user_uploads/")
    else:
        logger.warning(f"  Template user_uploads not found: {template_uploads}")
        logger.warning("  Run will start with empty user_uploads/")
    
    # Copy source files from manifest to user_uploads
    project_root = Path(__file__).parent.parent
    
    # Handle user_uploads array (new format)
    if "user_uploads" in manifest:
        for upload_item in manifest["user_uploads"]:
            source_path_str = upload_item.get("source", "")
            target_filename = upload_item.get("filename", "")
            if source_path_str and target_filename:
                source_path = project_root / source_path_str
                if source_path.exists() and source_path.is_file():
                    shutil.copy2(source_path, run_uploads / target_filename)
                    logger.info(f"  Copied user upload: {target_filename} ({source_path.stat().st_size / (1024*1024):.2f} MB)")
                else:
                    logger.warning(f"  User upload file not found: {source_path}")
    
    # Handle old source.file_info format (for backward compatibility)
    if "source" in manifest and "file_info" in manifest["source"]:
        source_path_str = manifest["source"]["file_info"].get("path", "")
        if source_path_str:
            source_path = project_root / source_path_str
            if source_path.exists() and source_path.is_file():
                shutil.copy2(source_path, run_uploads / source_path.name)
                logger.info(f"  Copied source file from manifest: {source_path.name}")
            else:
                logger.warning(f"  Source file not found: {source_path}")
    
    # Resolve template paths in manifest to run-specific paths
    def resolve_manifest_paths(obj, run_dir):
        """Recursively resolve 'runs/template/' paths to run-specific paths"""
        template_prefix = "runs/template/user_uploads/"
        run_uploads_str = str(run_dir / "user_uploads").replace('\\', '/')
        
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, str) and template_prefix in value:
                    # Replace template path with run-specific path
                    obj[key] = value.replace(template_prefix, f"{run_uploads_str}/")
                elif isinstance(value, (dict, list)):
                    resolve_manifest_paths(value, run_dir)
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    resolve_manifest_paths(item, run_dir)
        
        return obj
    
    manifest = resolve_manifest_paths(manifest, run_dir)
    logger.info(f"  Resolved template paths to run directory")
    
    # [3/12] Create model clients
    logger.info("\n[3/12] Creating model clients...")
    clients = create_all_model_clients(full_env_config)
    logger.info("  Model clients ready")
    
    # [4/12] Create runtime and register AgentGeneratorAgent
    logger.info("\n[4/12] Setting up agent infrastructure...")
    runtime = SingleThreadedAgentRuntime()
    
    await AgentGeneratorAgent.register(
        runtime,
        "agent_generator",
        lambda: AgentGeneratorAgent(claude_client=clients['claude-4.5'])
    )
    
    runtime.start()
    logger.info("  Agent infrastructure ready")
    
    # ==================================================
    # PHASE 0: CLASSIFICATION & SIDE TASKS
    # ==================================================
    logger.info("\n" + "="*80)
    logger.info(" "*25 + "PHASE 0: CLASSIFICATION")
    logger.info("="*80)
    
    # [5/12] Create Phase 0 request (pass full manifest, let LLMs parse what they need)
    logger.info("\n[5/12] Creating classification request...")
    
    # Clean manifest to remove instruction fields (avoid layered confusion)
    cleaned_manifest = clean_manifest_for_llms(manifest)
    
    # Build context with cleaned manifest - LLMs will intelligently extract what they need
    # Extract transformation_config and merge top-level skip_side_tasks if present
    transformation_config = cleaned_manifest.get('transformation_config', {}).copy()
    if 'skip_side_tasks' in cleaned_manifest:
        transformation_config['skip_side_tasks'] = cleaned_manifest['skip_side_tasks']
    
    additional_context = {
        "manifest": cleaned_manifest,
        "project_root": str(project_root),
        "user_uploads_dir": str(workspace_manager.get_user_uploads_directory(create=False)),
        "transformation_config": transformation_config
    }
    
    logger.info(f"  Task Type: {task_type}")
    
    phase0_request = TaskAnalysisRequest(
        task_id=task_id,
        task_description=description,
        files=[],  # LLMs will extract file info from manifest in additional_context
        connections=[],  # LLMs will extract connections from manifest in additional_context
        additional_context=additional_context
    )
    logger.info(f"  Task: {description[:80]}...")
    
    # [6/12] Run classification OR skip to Phase 1
    if manifest.get('skip_phase_0', False):
        logger.info("\n[6/12] SKIPPING Phase 0 - skip_phase_0=true in manifest")
        logger.info("  Creating synthetic classification result...")
        
        # Create a synthetic classification result with one core task
        from control_plane_v2.phase_0.messages import TaskClassification, CoreTask
        
        classification_result = TaskClassification(
            task_id=task_id,
            core_tasks=[
                CoreTask(
                    id="core_1",
                    description=description,
                    can_be_divided=True,
                    estimated_duration="varies",
                    dependencies=[]
                )
            ],
            side_tasks=[],
            execution_order=["core_1"],
            confidence=1.0,
            negotiation_summary="Phase 0 skipped per manifest configuration"
        )
        
        logger.info("  Synthetic core task created")
        logger.info("  Proceeding directly to Phase 1...")
    else:
        logger.info("\n[6/12] Running task classification (Claude + GPT-5 + Overseer)...")
        classifier = TaskClassifier(
            claude_client=clients['claude-4.5'],
            gpt5_client=clients['gpt-5-low'],
            runtime=runtime,
            overseer_client=clients['gpt-5-medium'],
            max_negotiation_iterations=3,
            max_overseer_iterations=5  # Increased from default 2 to give more chances
        )
        
        classification_result = await classifier.classify_task(phase0_request)
        
        logger.info("\n[PHASE 0 COMPLETE]")
        logger.info(f"  Core tasks identified: {len(classification_result.core_tasks)}")
        logger.info(f"  Side tasks identified: {len(classification_result.side_tasks)}")
    
    # [7/12] Execute side tasks (if not skipped)
    logger.info("\n[7/12] Handling side tasks...")
    
    if manifest.get('skip_phase_0', False) or manifest.get('skip_side_tasks', False) or manifest.get('transformation_config', {}).get('skip_side_tasks', False):
        logger.info("  [SKIPPED] Phase 0 or side tasks skipped by manifest")
        logger.info("  Proceeding directly to Phase 1...")
    elif not classification_result.side_tasks:
        logger.info("  [SKIPPED] No side tasks identified")
    else:
        logger.info(f"  Executing {len(classification_result.side_tasks)} side tasks...")
        
        # Create AgentFactory for Phase 0 side tasks using WorkspaceManager
        phase0_workspace = workspace_manager.get_phase_directory('phase0', create=True)
        
        factory = AgentFactory(
            generator_client=clients['claude-4.5'],
            executor_clients=clients,
            verifier_client=clients['claude-4.5'],
            runtime=runtime,
            base_work_dir=phase0_workspace / "agents"
        )
        
        solver = SideTaskSolver(
            agent_factory=factory,
            workspace_dir=phase0_workspace,
            max_concurrent=3
        )
        
        # Extract connections from manifest (if any)
        connections = parse_manifest_connections(manifest, project_root)
        
        await solver.solve_all_tasks(
            classification_result.side_tasks,
            connections,
            additional_context
        )
        
        # Verify using the same workspace as the solver
        verifier = SideTaskVerifier(workspace_dir=phase0_workspace)
        decision = verifier.verify_and_decide(classification_result.side_tasks)
        
        logger.info(f"\n[SIDE TASKS COMPLETE]")
        logger.info(f"  Decision: {'PROCEED' if decision['proceed'] else 'HALT'}")
        logger.info(f"  Reason: {decision['reason']}")
        
        if not decision['proceed']:
            logger.error("Side tasks verification failed. Halting execution.")
            sys.exit(1)
    
    # ==================================================
    # PHASE 1: TASK DIVISION
    # ==================================================
    logger.info("\n" + "="*80)
    logger.info(" "*25 + "PHASE 1: TASK DIVISION")
    logger.info("="*80)
    
    logger.info("\n[8/12] Dividing task into subtasks (Claude + GPT-5 collaboration)...")
    
    # Create code executors for Phase 1
    # CRITICAL: Work directory should be phase1_dir itself, not subdirectories
    # This ensures structure_analysis.json is saved to the correct location
    phase1_dir = workspace_manager.get_phase_directory('phase1', create=True)
    claude_executor = LocalCommandLineCodeExecutor(
        work_dir=str(phase1_dir),
        timeout=120
    )
    gpt5_executor = LocalCommandLineCodeExecutor(
        work_dir=str(phase1_dir),
        timeout=120
    )
    
    # CRITICAL: Start the code executors before use
    # This is required for LocalCommandLineCodeExecutor to work properly
    await claude_executor.start()
    await gpt5_executor.start()
    
    divider = CollaborativeTaskDivider(
        claude_client=clients['claude-4.5'],
        gpt5_client=clients['gpt-5-medium'],
        claude_executor=claude_executor,
        gpt5_executor=gpt5_executor,
        workspace_manager=workspace_manager,
        max_iterations=15  # Increased for complex tasks
    )
    
    # Build a comprehensive task description from all core tasks
    if len(classification_result.core_tasks) == 1:
        core_task_description = classification_result.core_tasks[0].description
    else:
        # Multiple core tasks - combine their descriptions
        task_summaries = [f"{i+1}. {task.description}" for i, task in enumerate(classification_result.core_tasks)]
        core_task_description = f"{description}\n\nCore tasks breakdown:\n" + "\n".join(task_summaries)
    
    # Add core tasks to additional context for reference
    additional_context['core_tasks'] = [
        {
            'id': task.id,
            'description': task.description,
            'estimated_duration': task.estimated_duration,
            'can_be_divided': task.can_be_divided,
            'dependencies': task.dependencies
        } for task in classification_result.core_tasks
    ]
    
    phase1_request = TaskDivisionRequest(
        task_id=task_id,
        core_task_description=core_task_description,
        plan_content=cleaned_manifest,  # Cleaned manifest - LLMs will extract connections intelligently
        connections=[],  # Not needed - manifest has all info
        additional_context=additional_context,
        success_criteria=manifest.get('quality_requirements', {}).get('statistical_validation', 'Complete the task successfully')
    )
    
    # Phase 1 creates the execution plan
    completion = await divider.divide_task(phase1_request, runtime, output_dir=None)
    
    logger.info("\n[PHASE 1 COMPLETE]")
    logger.info(f"  Status: {completion.overall_status}")
    logger.info(f"  Execution plan created")
    
    # ==================================================
    # PHASE 2: BOSS-WORKER EXECUTION
    # ==================================================
    logger.info("\n" + "="*80)
    logger.info(" "*25 + "PHASE 2: TASK EXECUTION")
    logger.info("="*80)
    
    logger.info("\n[9/12] Launching Boss-Worker orchestrator...")
    
    # Import Phase 2 orchestrator
    from control_plane_v2.phase_2.orchestrator_boss_worker import BossWorkerOrchestrator
    from control_plane_v2.phase_2.orchestrator_phase2_v2 import FileCatalog, SimpleVectorStore
    
    # Find the execution plan created by Phase 1
    # It should be in phase1_dir as execution_plan.json
    execution_plan_path = phase1_dir / "execution_plan.json"
    if not execution_plan_path.exists():
        logger.error(f"No execution plan found at: {execution_plan_path}")
        sys.exit(1)
    logger.info(f"  Found execution plan: {execution_plan_path.name}")
    
    # Create Phase 2 workspace
    phase2_dir = workspace_manager.get_phase_directory('phase2', create=True)
    phase2_logs_dir = phase2_dir / "logs"
    phase2_logs_dir.mkdir(exist_ok=True)
    
    # Add file handlers for Phase 2 logs
    root_logger = logging.getLogger()
    phase2_handler = logging.FileHandler(phase2_logs_dir / 'phase2_execution.log', mode='w')
    phase2_handler.setLevel(logging.INFO)
    phase2_handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
    root_logger.addHandler(phase2_handler)
    
    # Add worker detail logger
    worker_detail_logger = logging.getLogger("worker_detail")
    worker_detail_logger.setLevel(logging.DEBUG)
    worker_handler = logging.FileHandler(phase2_logs_dir / 'worker_detail.log', mode='w')
    worker_handler.setFormatter(logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))
    worker_detail_logger.addHandler(worker_handler)
    
    logger.info(f"  Phase 2 logs directory: {phase2_logs_dir}")
    
    # Create FileCatalog and populate with user uploads
    logger.info("\n  Creating file catalog...")
    catalog_path = run_dir / "file_catalog.json"
    catalog = FileCatalog(catalog_path=catalog_path)
    
    # Add all user uploads to catalog
    user_uploads_dir = workspace_manager.get_user_uploads_directory(create=False)
    if user_uploads_dir.exists():
        file_count = 0
        for file_path in user_uploads_dir.glob("*"):
            if file_path.is_file():
                catalog.add_file(
                    relative_path=file_path.name,
                    absolute_path=str(file_path),
                    description="User uploaded file for task execution"
                )
                file_count += 1
        logger.info(f"  Added {file_count} files to catalog")
    
    # Initialize vector store
    vector_store = SimpleVectorStore(store_path=run_dir / "vector_store.pkl")
    
    # Create orchestrator
    orchestrator = BossWorkerOrchestrator(
        run_path=run_dir,
        execution_plan_path=execution_plan_path,
        env_config=full_env_config
    )
    
    # Initialize and execute
    await orchestrator.initialize()
    phase2_results = await orchestrator.execute_all_tasks()
    await orchestrator.cleanup()
    
    logger.info("\n[PHASE 2 COMPLETE]")
    logger.info(f"  Total tasks: {len(phase2_results)}")
    logger.info(f"  Successful: {sum(1 for r in phase2_results if r['status'] == 'success')}")
    logger.info(f"  Failed: {sum(1 for r in phase2_results if r['status'] != 'success')}")
    
    # Log Phase 2 task summaries
    if phase2_results:
        logger.info("\n  Task summaries:")
        for result in phase2_results:
            status = "[SUCCESS]" if result['status'] == 'success' else "[FAILED]"
            logger.info(f"    {status} {result['task_id']}")
            logger.info(f"      Files: {len(result.get('files_created', []))}")
    
    # ==================================================
    # SUMMARY
    # ==================================================
    logger.info("\n" + "="*80)
    logger.info(" "*30 + "E2E TEST RESULTS")
    logger.info("="*80)
    
    logger.info(f"\nPhase 0 - Classification:")
    if manifest.get('skip_phase_0', False):
        logger.info(f"  Status: SKIPPED (skip_phase_0=true)")
    else:
        logger.info(f"  Core tasks: {len(classification_result.core_tasks)}")
    
    logger.info(f"\nPhase 1 - Planning:")
    logger.info(f"  Status: {completion.overall_status}")
    logger.info(f"  Execution plan created")
    
    logger.info(f"\nPhase 2 - Boss-Worker Execution:")
    logger.info(f"  Total tasks: {len(phase2_results)}")
    successful_phase2 = sum(1 for r in phase2_results if r['status'] == 'success')
    failed_phase2 = sum(1 for r in phase2_results if r['status'] != 'success')
    logger.info(f"  Successful: {successful_phase2}")
    logger.info(f"  Failed: {failed_phase2}")
    logger.info(f"  Success rate: {(successful_phase2/len(phase2_results)*100 if phase2_results else 0):.1f}%")
    
    # Save summary
    summary = {
        'timestamp': datetime.now().isoformat(),
        'manifest': args.manifest,
        'task_id': task_id,
        'task_type': task_type,
        'phase0': {
            'skipped': manifest.get('skip_phase_0', False),
            'core_tasks': len(classification_result.core_tasks),
            'side_tasks': len(classification_result.side_tasks)
        },
        'phase1': {
            'status': completion.overall_status,
            'execution_plan_created': True
        },
        'phase2': {
            'total_tasks': len(phase2_results),
            'successful': successful_phase2,
            'failed': failed_phase2,
            'success_rate': (successful_phase2/len(phase2_results)*100 if phase2_results else 0),
            'task_results': phase2_results
        }
    }
    
    summary_file = run_dir / "e2e_summary.json"
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)
    
    logger.info(f"\nSummary saved to: {summary_file}")
    
    # Cleanup: Stop the code executors
    await claude_executor.stop()
    await gpt5_executor.stop()
    
    logger.info("\n" + "="*80)
    logger.info(" "*30 + "COMPLETE")
    logger.info("="*80 + "\n")
    
    if failed_phase2 > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

