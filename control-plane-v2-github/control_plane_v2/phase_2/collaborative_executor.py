"""
Phase 2: Collaborative Subtask Executor

SIMPLIFIED ARCHITECTURE:
- Phase 2: Coding (Claude codes, GPT-5 reviews suggestions only)
- Phase 2c: Execution (Run code, retry on failure with Claude's fixes)

Engineers:
- Claude 4.5 (Lead Coder)
- GPT-5 High (Code Reviewer - flags work complete, gives suggestions)
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage
from autogen_core.code_executor import CodeBlock, CodeExecutor
from autogen_core import CancellationToken
from autogen_ext.code_executors import LocalCommandLineCodeExecutor

from pydantic import ValidationError

from ..phase_1.messages import SubtaskPackage
from .messages import (
    ClaudeCodeResponse,
    GPT5ReviewResponse,
    GPT5DebugResponse,
    TaskExecutionResult
)
from ..workspace_manager import WorkspaceManager
from ..knowledge_system import KnowledgeSystem

logger = logging.getLogger(__name__)


# ============================================================================
# TASK TYPE CLASSIFICATION - Centralized to avoid hardcoding duplication
# ============================================================================

# Task type keywords (configurable constants)
TASK_TYPE_KEYWORDS = {
    'extract': ['extract', 'load source', 'fetch', 'read from'],
    'transform': ['transform', 'convert', 'map', 'standardize', 'process'],
    'merge': ['merge', 'join', 'combine', 'union'],
    'load': ['load', 'insert', 'write to', 'append', 'save to', 'persist', 'commit'],
    'validation': ['validate', 'verify', 'check', 'test']
}

# File format patterns (configurable)
DATA_FILE_PATTERNS = ['*.json', '*.csv', '*.parquet', '*.txt']
METADATA_FILE_PATTERNS = ['_package.json', '_result.json', 'task_learnings.json', '*.log']


def infer_task_type(description: str) -> str:
    """
    Infer task type from description using keyword matching.
    Centralized function to avoid duplication and enable configuration.
    
    Args:
        description: Task description text
        
    Returns:
        Task type string ('extract', 'transform', 'merge', 'load', 'validation', 'other')
    """
    desc_lower = description.lower()
    
    for task_type, keywords in TASK_TYPE_KEYWORDS.items():
        if any(kw in desc_lower for kw in keywords):
            return task_type
    
    return 'other'


def is_load_task(description: str) -> bool:
    """
    Check if task is a load/insert operation requiring verification.
    
    Args:
        description: Task description text
        
    Returns:
        True if task is a load operation
    """
    return infer_task_type(description) == 'load'


# File validation removed - let tasks handle their own outputs


class CollaborativeSubtaskExecutor:
    """
    Two-phase collaborative execution:
    1. Coding: Claude codes (understands + implements), GPT-5 reviews and suggests
    2. Execution: Run code, retry on failure with Claude's fixes
    
    Claude LEADS - GPT-5 only reviews and flags completion
    """
    
    # Phase 2: Coding Prompts
    CLAUDE_CODING_PROMPT = """You are a Python developer implementing a task.
You work WITH GPT-5 (your senior reviewer). GPT-5 makes the final approval decision - listen to their instructions.

⏱️ **TAKE YOUR TIME - UNDERSTAND FIRST, THEN CODE:**
1. **READ the task description carefully** - what is the actual goal?
2. **EXAMINE the data provided** - what format, structure, schema?
3. **REVIEW past learnings and RAG context** - what patterns can you reuse?
4. **THINK about the approach** - what's the best way to solve this?
5. **THEN write code** - implementation comes after understanding

Don't rush to code - spend time understanding the problem deeply first.

YOUR TASK:
Read the package specs and write complete Python code to accomplish the task.

{expected_output_files_section}

THE PACKAGE CONTAINS EVERYTHING:
- Credentials (use them as-is)
- Data specifications (implement them exactly)
- Required inputs and outputs (follow strictly)
- Expected output files (if specified, create them EXACTLY as listed above)

APPROACH:
- Implement the package specs in whatever way works best
- Write code that solves the problem - your style, your choice
- Use whatever libraries and patterns you prefer
- **Choose file formats/extensions based on task and data requirements:**
  - Pick the format that best fits your data and processing needs
  - Could be CSV, JSON, Parquet, Delta, HDF5, or any other format
  - Your choice - you understand the data and task best!
- GPT-5 will review and may ask for changes - be ready to iterate

CRITICAL - DATA PRESERVATION:
- DO NOT delete, truncate, or drop existing data unless EXPLICITLY specified in manifest
- INSERT strategy means APPEND to existing data, not replace
- If you encounter duplicate key errors, handle them (skip duplicates, fail gracefully, etc.)
- NEVER use TRUNCATE, DELETE FROM, or DROP unless the manifest explicitly instructs it
- Preserve existing data integrity - only add new data

DYNAMIC & GENERAL:
- This system handles ANY type of task - be flexible and adaptive
- Read the task description carefully to understand what's needed
- Use your best judgment on implementation approach
- Don't make assumptions about data types or formats - discover them dynamically

⚙️ **CRITICAL - EXECUTION ENVIRONMENT LIMITATIONS** ⚙️

UNDERSTAND HOW YOUR CODE WILL BE EXECUTED:
- Your code is executed as: `python your_code.py` (NO command-line arguments)
- You CANNOT rely on CLI arguments like: `python script.py --arg1 val1 --arg2 val2`
- The execution system does NOT support passing CLI arguments to your code
- sys.argv will ONLY contain the script name, NO additional arguments

WRITE SELF-CONTAINED CODE THAT WORKS WITHOUT CLI ARGUMENTS:
✅ **DO THIS** - Code that auto-discovers inputs:
```python
import glob
from control_plane_v2.data_catalog import DataCatalog

# Find input files in workspace
spec_files = glob.glob('*_spec.json')
if spec_files:
    spec_file = spec_files[0]
else:
    # Or use Data Catalog to find files from dependencies
    catalog = DataCatalog(package.data.get('catalog_location'))
    files = catalog.get_files_by_task('dependency_task_id')
    spec_file = [f for f in files if 'spec' in f['name']][0]['path']
```

✅ **DO THIS** - Optional CLI support with graceful fallback:
```python
import sys
import glob

# Try CLI args if provided, otherwise auto-discover
if len(sys.argv) > 1 and sys.argv[1]:
    config_file = sys.argv[1]  # Will work if CLI args added later
else:
    config_file = glob.glob('config.json')[0]  # Fallback for execution system
```

❌ **DON'T DO THIS** - Code that REQUIRES CLI arguments:
```python
import sys
if len(sys.argv) < 2:
    print("Usage: python script.py --input file.json --output out.csv")
    sys.exit(1)  # This will ALWAYS fail in the execution environment!
```

KEY PRINCIPLE: Your code must work when executed with ZERO arguments.
- Find input files in the current working directory (task workspace)
- Use Data Catalog to find files from dependency tasks
- Use package.data dict for configuration (passed as JSON in workspace)
- Write output files to current directory (task workspace)

🔍 **CRITICAL - INSPECT, DON'T ASSUME** 🔍

When loading external data files (JSON configs, schemas, datasets):

1. **INSPECT THE STRUCTURE FIRST** 

2. **VALIDATE BEFORE USING** - Check types and structure immediately after loading

3. **ADAPT YOUR CODE TO THE DATA** - Don't try to convert data to fit your expectations
   - If file has structure X, work with structure X
   - If file is format Y, handle format Y
   - Don't write converters unless absolutely necessary

4. **NO HARDCODED ASSUMPTIONS** - Every assumption is a potential failure point
   - Don't assume specific key names exist
   - Don't assume specific data types
   - Don't assume specific file formats
   - Discover, validate, then process

LEVERAGE KNOWLEDGE SYSTEMS:
- ✅ **RAG Memory**: Past learnings from similar tasks are provided above - USE THEM!
- ✅ **Data Catalog**: Use it to find file locations if you can't locate input files
- ✅ **Accumulated Knowledge**: All prior task discoveries are provided - DON'T REDISCOVER
- These systems exist to make your job easier - leverage them actively!

WRITE COMPLETE CODE:

REQUIREMENTS:
1. **CREDENTIALS ARE PROVIDED BELOW** - Read them directly from the CREDENTIALS JSON.
2. **Include ALL necessary imports** at the top of your code
3. Handle errors gracefully  
4. Write efficient code - skip comments unless absolutely needed

🔒 **CRITICAL - FILE ACCESS & ISOLATION** 🔒

**Your working directory: {task_workspace}**

**ZERO-COPY ARCHITECTURE:**
This system uses a zero-copy architecture where input files are NOT copied to your directory.
Instead, you receive ABSOLUTE PATHS to input files that you must read directly.

**INPUT FILES (from user_uploads or dependencies):**
{input_files_section}

**FOR INPUT FILES:**
- ✅ Use the absolute paths provided above to READ input files
- ✅ Example: `pd.read_csv(r"{example_input_path}")` 
- ❌ DO NOT try to find files with `glob("*.csv")` - use provided paths
- ❌ DO NOT assume files are in current directory

**FOR OUTPUT FILES:**
- ✅ Write to current directory: `open("output.json", "w")`
- ✅ All outputs go in: {task_workspace}
- ❌ DO NOT write to parent directories or absolute paths outside your workspace

**FILE ACCESS RULES:**
- ✅ READ from absolute paths provided in package (input files)
- ✅ WRITE to current directory using relative paths (output files)
- ✅ List current dir for debugging: `os.listdir('.')`
- ❌ NO parent directory access: `../`, `../../`
- ❌ NO searching parent dirs: `glob("../../**/*.csv")`

**EXAMPLE - Reading input, writing output:**
```python
import pandas as pd
import os

# Read from absolute path (provided by orchestrator)
input_csv = r"{example_input_path}"
df = pd.read_csv(input_csv)

# Process data
result = df.describe()

# Write to current directory
output_file = "analysis_result.json"
result.to_json(output_file)
print(f"[OK] Wrote {{os.path.abspath(output_file)}}")
```

**WHY THIS MATTERS:**
- Zero-copy = no file duplication, faster execution
- Absolute paths = reliable access to input files
- Current dir outputs = isolated, reproducible results


HELPFUL TIPS - WINDOWS CONSOLE ENCODING:
- You are running on Windows with cp1252 encoding
- NEVER use Unicode symbols in print() or logging statements
- Use ASCII only: [OK], [ERROR], [WARN], +, -, *, etc.
- NO checkmarks, NO arrows, NO special symbols (no \\u2713, \\u2717, etc.)

TIP - Data Loading:
Validate data types after loading external files to avoid crashes from unexpected formats.

OUTPUT FORMAT (JSON):
{{
  "code": "Complete Python code as a string",
  "explanation": "What the code does (2-3 sentences)",
  "approach": "Key implementation decisions",
  "libraries_needed": ["list", "of", "packages"]
}}

CRITICAL FILE OUTPUTS (NON-NEGOTIABLE):

1. EXECUTION RESULT: {output_file}
   Save this at the end with execution status:
   {{
     "success": true/false,
     "message": "What happened",
     "output_data": {{"key": "value"}},
     "errors": []
   }}

2. TASK LEARNINGS: task_learnings.json
   ALWAYS save what future tasks should know:
   {{
     "discovered": {{"key": "What you found out"}},
     "best_practices": ["Pattern that worked", "Things to avoid"],
     "gotchas": ["Important warnings or edge cases"],
     "recommendations": "Advice for next tasks",
     "files_created": [
       {{
         "filename": "<your_chosen_name>",
         "full_path": "<absolute_path>",
         "description": "What this file contains",
         "file_type": "output|intermediate|passthrough",
         "purpose": "Brief explanation of why this file exists"
       }}
     ]
   }}
   
   CRITICAL - FILE METADATA:
   - file_type: "output" (primary result for downstream tasks), "intermediate" (temporary/debug), "passthrough" (copied from input unchanged)
   - This helps the Catalog and downstream tasks know which files to use
   - If you copied an input file unchanged, mark it as "passthrough"
   - Your main output files should be "output"
   
   Save ANY insights that help future tasks avoid errors or work faster
   
   ⚠️ CRITICAL - FILE PATHS (NON-NEGOTIABLE):
   - ALWAYS include "files_created" in learnings with FULL ABSOLUTE PATHS
   - Use os.path.abspath() to get the full path: os.path.abspath('output.json')
   - Store EVERY file you create, even temporary ones
   - The Data Catalog will register these paths for downstream tasks to query
   - Future tasks will CHECK THE CATALOG for your file paths - make sure they're correct!
   - Format: {{"filename": "name.ext", "full_path": "/full/absolute/path/name.ext", "file_type": "output", "purpose": "..."}}
   
   🔑 **WHY FULL PATHS ARE CRITICAL:**
   - The Data Catalog depends on full paths to track files across the system
   - Downstream tasks use Catalog to find your outputs dynamically
   - Without full paths, your files are invisible to future tasks
   - ALWAYS use os.path.abspath() for every file - no exceptions!
   - This is how the system stays dynamic and general - files are discovered, not hardcoded
   
   Example learnings with proper paths:
   {{
     "files_created": [
       {{"filename": "output.ext", "full_path": "/absolute/path/output.ext", "file_type": "output", "purpose": "Primary result file"}},
       {{"filename": "intermediate.ext", "full_path": "/absolute/path/intermediate.ext", "file_type": "intermediate", "purpose": "Temporary processing file"}}
     ]
   }}

3. DATA OUTPUT FILES: {output_files_str}
   ⚠️ CRITICAL: Your code MUST create EVERY file in this list ⚠️
   - These files are REQUIRED for downstream tasks
   - Use RELATIVE paths: open('<filename>', 'w')
   - Save in CURRENT WORKING DIRECTORY (NOT absolute paths)
   - Missing ANY file = AUTOMATIC TASK FAILURE
   - Verify each file exists after creating it with assert os.path.exists('<filename>')
  
  # Save task learnings (REQUIRED!)
  learnings = {{
      "discovered": {{"key": "value_you_found"}},
      "best_practices": ["Pattern that worked well"],
      "gotchas": ["Important edge case or limitation"],
      "files_created": [
          {{
              "filename": output_file,
              "full_path": os.path.abspath(output_file),
              "description": "Processed data output"
          }}
      ]
  }}
  with open('task_learnings.json', 'w') as f:
      json.dump(learnings, f)
  
  # Save execution result (REQUIRED!)
  with open('{output_file}', 'w') as f:
      json.dump({{"success": True, "message": "Done"}}, f)

Remember: GPT-5 is your senior reviewer and has FINAL APPROVAL AUTHORITY.
If GPT-5 rejects your code, you must fix the issues and resubmit.
Listen to GPT-5's feedback carefully - it's there to guide you to success.
"""

    GPT5_CODE_REVIEW_PROMPT = """You are the SENIOR CODE REVIEWER and have FINAL APPROVAL AUTHORITY.

TASK CONTEXT:
{task_description}

⏱️ **TAKE YOUR TIME - UNDERSTAND BEFORE JUDGING:**
1. **READ the task description** - what's the actual goal?
2. **EXAMINE the data context** - what inputs, what outputs?
3. **STUDY Claude's approach** - does it make sense for this specific task?
4. **VERIFY file creation** - are ALL required files being created?
5. **THEN make your decision** - approve or provide specific concerns

Don't rush your review - a thorough review prevents failures downstream.

YOUR ROLE:
- You are Claude's boss - your approval is REQUIRED before code can execute
- Your decision is FINAL - if you reject, Claude must fix and resubmit
- Be thorough but fair - guide Claude to success

CRITICAL REVIEW CHECKLIST (STRICTLY ENFORCE):

1. **OUTPUT FILES:**
   Create appropriate output files as specified in the task description

2. **Does code match the task description above?**
   - Verify the approach solves the actual problem
   - Check that all required operations are implemented

3. **NO HARDCODED ASSUMPTIONS - CRITICAL CHECK:**
   ⚠️ REJECT if Claude assumes data structure without inspecting first
   - Check: Does code load external file then immediately access specific keys?
   - WRONG: schema['distributions'] without checking if 'distributions' key exists
   - RIGHT: Check what keys exist, then adapt: if 'distributions' in schema...
   - Look for: Direct key access, assumed column names, expected formats
   - If code makes assumptions about structure/format -> REJECT with concern

4. **Basic error handling present?**
   - Code should handle common failure modes
   - At minimum: try/except around risky operations

5. **Code looks executable?**
   - All imports present
   - No obvious syntax errors
   - Variables are defined before use

OPTIONAL REVIEW (SUGGEST ONLY):
- Performance optimizations
- Better error handling
- Code style improvements
- Additional validations

OUTPUT FORMAT (JSON) - STRICT SCHEMA:
{{
  "approved": true/false,  // Is the code ready for execution?
  "confidence": 0.0-1.0,  // Float between 0 and 1
  "reasoning": "Detailed reasoning for approval/rejection (required, cannot be empty)",
  "concerns": [  // Critical issues that must be fixed
    "Code has logical errors",
    "Missing required functionality"
  ],
  "suggestions": [  // Optional improvements (non-blocking)
    "Could add better error handling",
    "Consider using pandas for better performance"
  ]
}}

YOUR DECISION CRITERIA:

**REJECT (approved=false) IF:**
- Code clearly won't accomplish the task
- Major logical errors that will cause failure

**APPROVE (approved=true) IF:**
- Code reasonably implements the task
- Basic error handling is present
- Code looks executable

YOUR AUTHORITY:
- approved=false BLOCKS execution - Claude must fix and resubmit
- concerns are MANDATORY for rejections - list ALL specific issues
- Trust Claude's implementation choices
- Your reasoning guides Claude's next iteration

Be thorough - you are the quality gatekeeper. But be constructive - guide Claude to success.
"""

    def __init__(
        self,
        claude_client: ChatCompletionClient,
        gpt5_client: ChatCompletionClient,
        code_executor: CodeExecutor,
        workspace_manager: WorkspaceManager,
        knowledge_system: Optional[KnowledgeSystem] = None,
        max_coding_iterations: int = 15,  # Increased for complex tasks
        max_execution_attempts: int = 15  # Increased retries
    ):
        self._claude_client = claude_client
        self._gpt5_client = gpt5_client
        self._code_executor = code_executor
        self._workspace_manager = workspace_manager
        self._knowledge_system = knowledge_system
        self._max_coding_iterations = max_coding_iterations
        self._max_execution_attempts = max_execution_attempts
        
        logger.info("CollaborativeSubtaskExecutor initialized")
        logger.info(f"  Max coding iterations: {max_coding_iterations}")
        logger.info(f"  Max execution attempts: {max_execution_attempts}")
        logger.info(f"  Knowledge System: {'ENABLED' if knowledge_system else 'DISABLED'}")
    
    async def execute_subtask(
        self,
        request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Main entry point - runs both phases
        
        Returns:
            Dict[str, Any] with success/failure and output
        """
        # Load subtask package
        package = self._load_package(request['package_path'])
        
        logger.info(f"Starting execution: {package.subtask_id}")
        logger.info(f"  Description: {package.description}")
        logger.info(f"  Dependencies: {package.dependencies if package.dependencies else 'None'}")
        
        # Create task-specific workspace directory
        task_dir = self._workspace_manager.get_task_directory('phase2', package.subtask_id, create=True)
        logger.info(f"  Task workspace: {task_dir}")
        
        # File materialization is handled by orchestrator based on execution_hints.materialize_mode
        # Executor should NOT copy files - that violates zero-copy architecture
        # Files are accessible via their full paths provided in input_files
        
        # =================================================================
        # TRUST ORCHESTRATOR - NO CONDITIONAL FILE DISCOVERY LOGIC
        # =================================================================
        # Orchestrator (GPT-5) has already resolved all file paths
        # We just log what was provided and let agents use them directly
        
        if package.input_file_paths:
            logger.info(f"  Input files provided by orchestrator: {len(package.input_file_paths)}")
            for file_path in package.input_file_paths:
                logger.info(f"    - {Path(file_path).name} (absolute path provided)")
        
        if package.execution_guidance:
            logger.info(f"  Execution guidance from orchestrator:")
            logger.info(f"    {package.execution_guidance}")
        
        # Create task-specific code executor
        task_executor = LocalCommandLineCodeExecutor(work_dir=str(task_dir))
        original_executor = self._code_executor
        self._code_executor = task_executor
        
        try:
            # Phase 2: Coding (Claude codes, GPT-5 reviews)
            logger.info("")
            logger.info("="*60)
            logger.info("PHASE 2: COLLABORATIVE CODING")
            logger.info("="*60)
            
            # NEW: Query Knowledge System for relevant context
            rag_context = {}
            if self._knowledge_system:
                logger.info("Querying Knowledge System for relevant context...")
                
                # Infer task_type using centralized function
                task_type = infer_task_type(package.description)
                
                # Get dependencies from package
                dependencies = package.dependencies if hasattr(package, 'dependencies') else []
                
                # Query with correct signature
                rag_context = self._knowledge_system.get_context_for_task(
                    task_description=package.description,
                    task_type=task_type,
                    dependencies=dependencies
                )
                
                if rag_context.get('similar_tasks'):
                    logger.info(f"  Found {len(rag_context['similar_tasks'])} similar past tasks")
                else:
                    logger.info("  No relevant past learnings found (this may be the first task)")
            
            # NEW: Pass accumulated learnings to coding phase
            learnings = request.get('accumulated_learnings', []) or []
            if learnings:
                logger.info(f"Using accumulated knowledge:")
                logger.info(f"  - {len(learnings)} learning(s) from prior tasks")
            
            code_result = await self._phase_2_coding(package, learnings, rag_context)
            
            if not code_result:
                logger.error("Coding phase failed - no code generated")
                return {
                    "subtask_id": package.subtask_id,
                    "success": False,
                    "understanding_phase_complete": False,
                    "code_approved": False,
                    "reasoning": "Failed to generate code"
                }
            
            logger.info("Code generation complete")
            
            # Phase 2c: Execution
            logger.info("")
            logger.info("="*60)
            logger.info("PHASE 2C: EXECUTION")
            logger.info("="*60)
            
            exec_result = await self._phase_2c_execution(
                package, code_result
            )
            
            # NEW: Extract learnings from execution
            learnings = self._extract_learnings(package, code_result, exec_result, request)
            
            # NEW: Register task completion with Knowledge System (SUCCESS CRITERIA!)
            if exec_result.get('success', False) and self._knowledge_system:
                logger.info("Registering task completion with Knowledge System...")
                try:
                    # AUTO-DETECT output files created by the task
                    output_file_paths = []
                    per_file_metadata = {}
                    
                    # Look for data files in multiple formats (configurable patterns)
                    import glob
                    data_files = []
                    for pattern in DATA_FILE_PATTERNS:
                        matched_files = glob.glob(str(task_dir / pattern))
                        data_files.extend(matched_files)
                    
                    # Filter out metadata files (configurable exclusions)
                    def is_metadata_file(file_path: str) -> bool:
                        """Check if file matches metadata patterns"""
                        for pattern in METADATA_FILE_PATTERNS:
                            if pattern.startswith('*'):
                                # Extension pattern like *.log
                                if file_path.endswith(pattern[1:]):
                                    return True
                            else:
                                # Substring pattern like _package.json
                                if pattern in file_path:
                                    return True
                        return False
                    
                    data_files = [f for f in data_files if not is_metadata_file(f)]
                    
                    for file_path_str in data_files:
                        file_path = Path(file_path_str).absolute()  # FIXED: Ensure absolute path
                        output_file_paths.append(str(file_path))
                        
                        # Get file size for metadata
                        file_size = file_path.stat().st_size if file_path.exists() else 0
                        
                        per_file_metadata[str(file_path)] = {
                            "file_type": "data",
                            "metadata": {
                                "task_description": package.description,
                                "exit_code": exec_result.get('exit_code', -1),
                                "file_size": file_size
                            }
                        }
                        logger.info(f"  Detected output file: {file_path.name} ({file_size} bytes)")
                    
                    if not output_file_paths:
                        logger.warning(f"  No output data files auto-detected in {task_dir}")
                    
                    # Infer task_type using centralized function
                    task_type = infer_task_type(package.description)
                    
                    # Register with Data Catalog and RAG Memory (CORRECT SIGNATURE!)
                    reg_result = self._knowledge_system.register_task_completion(
                        task_id=package.subtask_id,
                        task_type=task_type,
                        success=True,  # Only registering successful tasks
                        output_files=output_file_paths,
                        learnings=learnings,
                        execution_time=exec_result.get('execution_time', 0.0),
                        file_metadata=per_file_metadata
                    )
                    logger.info(f"[OK] Task registered in Knowledge System: {reg_result['files_registered']} files, learnings={reg_result['learnings_indexed']}")
                except Exception as e:
                    import traceback
                    logger.error(f"Failed to register with Knowledge System: {e}")
                    logger.error(f"Traceback: {traceback.format_exc()}")
                    # Don't fail the task, but log the error
            elif not exec_result.get('success', False):
                logger.info("Task failed - not registering with Knowledge System")
            
            # Contract validation removed - let tasks handle their own outputs
            files_created = []
            
            # Discover all files created by the task
            for file_path in task_dir.glob("**/*"):
                if file_path.is_file() and not file_path.name.startswith('.') and not file_path.name.endswith('.py'):
                    files_created.append(str(file_path.absolute()))
            
            # Save execution summary to task directory
            result_summary = {
                "subtask_id": package.subtask_id,
                "success": exec_result.get('success', False),
                "execution_time": exec_result.get('execution_time', 0.0),
                "exit_code": exec_result.get('exit_code', -1),
                "output_files": package.output_files,
                "files_created": files_created,  # NEW: Actual files created
                "task_workspace": str(task_dir),
                "learnings": learnings,  # NEW: Include learnings
                "files_created": files_created
            }
            summary_file = task_dir / "result.json"
            with open(summary_file, 'w') as f:
                json.dump(result_summary, f, indent=2)
            logger.info(f"  Result summary saved: {summary_file}")
            
            # ==== NEW: CREATE COMPREHENSIVE TASK SUMMARY ====
            # This summary provides rich metadata for the orchestrator to intelligently route files
            if exec_result.get('success', False):
                logger.info("[TASK SUMMARY] Creating comprehensive task summary...")
                
                # Build detailed file metadata
                output_files_metadata = []
                
                # Try to load agent learnings for file descriptions
                agent_file_metadata = {}
                if learnings.get('agent_learnings') and 'files_created' in learnings['agent_learnings']:
                    # Agent provided file metadata in task_learnings.json
                    for file_info in learnings['agent_learnings']['files_created']:
                        filename = file_info.get('filename', '')
                        agent_file_metadata[filename] = {
                            'description': file_info.get('description', file_info.get('purpose', 'No description')),
                            'file_type': file_info.get('file_type', 'output'),
                            'purpose': file_info.get('purpose', '')
                        }
                
                # Process each created file
                for file_path_str in files_created:
                    file_path = Path(file_path_str)
                    if not file_path.exists():
                        continue
                    
                    filename = file_path.name
                    
                    # Get agent-provided metadata if available
                    agent_meta = agent_file_metadata.get(filename, {})
                    
                    # Infer file type from extension if not provided by agent
                    file_type = agent_meta.get('file_type', 'output')
                    ext = file_path.suffix.lower()
                    if not agent_meta.get('file_type'):
                        if ext in ['.json']:
                            file_type = 'manifest' if 'manifest' in filename else 'metadata'
                        elif ext in ['.parquet', '.csv']:
                            file_type = 'data'
                        elif ext in ['.npz', '.npy', '.pkl', '.pickle']:
                            file_type = 'model_weights'
                        elif ext in ['.txt', '.log']:
                            file_type = 'log'
                        elif ext in ['.png', '.jpg', '.jpeg', '.pdf']:
                            file_type = 'visualization'
                    
                    # Build file metadata entry
                    file_metadata = {
                        'filename': filename,
                        'absolute_path': str(file_path.absolute()),
                        'relative_path': filename,  # Relative to task directory
                        'file_type': file_type,
                        'content_description': agent_meta.get('description', f'{file_type.replace("_", " ").title()} file'),
                        'size_bytes': file_path.stat().st_size,
                        'purpose': agent_meta.get('purpose', f'Output from {package.subtask_id}')
                    }
                    output_files_metadata.append(file_metadata)
                
                # Extract learnings summary
                learnings_summary = "No summary provided"
                if learnings.get('agent_learnings'):
                    agent_learnings = learnings['agent_learnings']
                    if 'recommendations' in agent_learnings:
                        learnings_summary = agent_learnings['recommendations']
                    elif 'best_practices' in agent_learnings and agent_learnings['best_practices']:
                        learnings_summary = '; '.join(agent_learnings['best_practices'][:2])
                
                # Build comprehensive task summary
                task_summary = {
                    'task_id': package.subtask_id,
                    'status': 'completed',
                    'timestamp': datetime.now().isoformat(),
                    'output_files': output_files_metadata,
                    'dependencies_used': package.dependencies if hasattr(package, 'dependencies') else [],
                    'learnings_summary': learnings_summary,
                    'execution_time': exec_result.get('execution_time', 0.0),
                    'task_description': package.description if hasattr(package, 'description') else ''
                }
                
                # Save task summary
                task_summary_file = task_dir / "task_summary.json"
                with open(task_summary_file, 'w') as f:
                    json.dump(task_summary, f, indent=2)
                logger.info(f"  [TASK SUMMARY] Saved comprehensive summary: {task_summary_file}")
                logger.info(f"  [TASK SUMMARY] {len(output_files_metadata)} file(s) with metadata")
                
                # NEW: Register task summary with catalog for global file discovery
                if self._knowledge_system and self._knowledge_system.catalog:
                    try:
                        self._knowledge_system.catalog.register_task_summary(
                            task_id=package.subtask_id,
                            summary=task_summary
                        )
                    except Exception as e:
                        logger.warning(f"  [CATALOG] Could not register task summary: {e}")
            
            return {
                "subtask_id": package.subtask_id,
                "success": exec_result.get('success', False),
                "understanding_phase_complete": True,
                "code_approved": True,
                "execution_attempts": 1,  # TODO: track actual attempts
                "final_code": code_result['code'],
                "execution_result": exec_result,
                "reasoning": f"Task {'completed' if exec_result.get('success', False) else 'failed'}",
                "output_data": {"execution_time": exec_result.get('execution_time', 0.0), "task_workspace": str(task_dir)},
                "learnings": learnings,  # NEW: Return learnings to orchestrator
                "files_created": files_created,  # NEW: Actual files created
                "files_created": files_created
            }
        finally:
            # Restore original executor
            self._code_executor = original_executor
    
    async def _phase_2_coding(
        self,
        package: SubtaskPackage,
        accumulated_learnings: List[Dict[str, Any]] = None,
        rag_context: Dict[str, Any] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Phase 2: Claude codes, GPT-5 reviews and suggests
        GPT-5's suggestions are OPTIONAL - Claude decides
        """
        output_file = f"{package.subtask_id}_result.json"
        
        current_code = None
        gpt5_suggestions = []
        gpt5_examples = []  # Store GPT-5's working code examples
        
        for iteration in range(1, self._max_coding_iterations + 1):
            logger.info(f"Coding iteration {iteration}/{self._max_coding_iterations}")
            
            # Claude generates code (receives GPT-5's working examples)
            logger.info("  Claude writing code...")
            code_gen = await self._get_claude_code(
                package, output_file, gpt5_suggestions, accumulated_learnings, rag_context, gpt5_examples
            )
            
            if not code_gen or not code_gen.get('code'):
                logger.error("  Claude failed to generate code")
                continue
            
            current_code = code_gen
            logger.info(f"  Code generated: {len(code_gen['code'])} characters")
            logger.info(f"  Approach: {code_gen['approach'][:80]}...")
            
            # GPT-5 reviews code
            logger.info("  GPT-5 reviewing code...")
            review = await self._get_gpt5_code_review(package, code_gen)
            
            if not review:
                logger.error("  GPT-5 failed to review code")
                # Continue anyway, Claude's code is what matters
                return code_gen
            
            logger.info(f"  Review confidence: {review.get('confidence', 0.0)}")
            
            # Parse GPT-5's response
            approved = review.get("approved", False)
            concerns = review.get("concerns", [])
            suggestions = review.get("suggestions", [])
            
            # SAFETY CHECK: Validate consistency
            if approved and concerns:
                logger.warning(f"  [INCONSISTENT] GPT-5 approved=True but raised {len(concerns)} concerns - overriding to rejected")
                approved = False  # Safety override
            
            if not approved and not concerns and not suggestions:
                logger.warning(f"  [INCONSISTENT] GPT-5 rejected but provided no feedback - treating as approved")
                approved = True  # Safety override
            
            # Decision logic
            if approved:
                logger.info(f"  [APPROVED] GPT-5 approved code after {iteration} iteration(s)")
                if suggestions:
                    logger.info(f"  [SUGGESTIONS] {len(suggestions)} optional improvement(s) provided (non-blocking)")
                return code_gen
            
            # Code was rejected - handle feedback
            feedback = concerns if concerns else suggestions
            feedback_type = "CONCERNS" if concerns else "SUGGESTIONS"
            
            if feedback:
                logger.info(f"  [{feedback_type}] {len(feedback)} issue(s) identified")
                for i, issue in enumerate(feedback[:3], 1):
                    logger.debug(f"    {i}. {issue[:60]}...")
                gpt5_suggestions = feedback
                
                # GPT-5 writes and executes ACTUAL FIXES (direct contribution)
                logger.info("  [GPT-5] Writing actual code fixes and executing them...")
                task_dir = self._workspace_manager.get_task_directory('phase2', package.subtask_id, create=False)
                gpt5_fixes = await self._get_gpt5_executable_examples(
                    package, code_gen, feedback, task_dir
                )
                if gpt5_fixes:
                    gpt5_examples = gpt5_fixes
                    working_fixes = [f for f in gpt5_fixes if f.get('success')]
                    if working_fixes:
                        logger.info(f"  [GPT-5] ✓ {len(working_fixes)} working fix(es) - direct contributions ready for Claude!")
                    else:
                        logger.info(f"  [GPT-5] Attempted {len(gpt5_fixes)} fix(es) - results shared with Claude")
            else:
                # Rejected but no feedback - generic retry
                logger.warning(f"  [REJECTED] GPT-5 rejected code but provided no specific feedback")
                gpt5_suggestions = ["Code rejected by GPT-5 - please review and improve"]
        
        # Max iterations reached
        logger.warning("Max coding iterations reached")
        if current_code:
            logger.info("Using last generated code")
            return current_code
        
        return None
    
    async def _phase_2c_execution(
        self,
        package: SubtaskPackage,
        code_gen: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Phase 2c: Execute the code, retry on failure with COLLABORATIVE Claude + GPT-5 debugging
        """
        current_code = code_gen['code']
        
        for attempt in range(1, self._max_execution_attempts + 1):
            logger.info(f"Execution attempt {attempt}/{self._max_execution_attempts}")
            
            try:
                start_time = time.time()
                
                # Execute code
                code_block = CodeBlock(code=current_code, language="python")
                cancellation_token = CancellationToken()
                result = await self._code_executor.execute_code_blocks(
                    code_blocks=[code_block],
                    cancellation_token=cancellation_token
                )
                
                execution_time = time.time() - start_time
                
                # Parse result
                if result.exit_code == 0:
                    logger.info(f"  [SUCCESS] Execution completed in {execution_time:.2f}s")
                    
                    # GENERAL VERIFICATION: Check agent's own result JSON for business logic failures
                    task_dir = self._workspace_manager.get_task_directory('phase2', package.subtask_id, create=False)
                    
                    # Look for agent's result JSON (pattern: {subtask_id}_result.json)
                    agent_result_json = task_dir / f"{package.subtask_id}_result.json"
                    
                    if agent_result_json.exists():
                        try:
                            with open(agent_result_json, 'r') as f:
                                agent_result = json.load(f)
                            
                            # Check if agent reported failure
                            if not agent_result.get('success', True):
                                failure_reason = agent_result.get('message', 'Agent reported task failure')
                                errors = agent_result.get('errors', [])
                                error_details = '\n'.join(errors) if errors else 'No error details provided'
                                
                                logger.error(f"  [AGENT VERIFICATION FAILED] {failure_reason}")
                                logger.error(f"  Errors: {error_details}")
                                
                                # If not last attempt, trigger collaborative debugging
                                if attempt < self._max_execution_attempts:
                                    logger.info("  [COLLABORATIVE DEBUG] Analyzing agent-reported failure...")
                                    fixed_code = await self._get_collaborative_fix(
                                        package, 
                                        current_code, 
                                        f"Agent verification failed:\n{json.dumps(agent_result, indent=2)}\n\nReason: {failure_reason}\nErrors: {error_details}\n\nThe code executed without Python errors but the agent's own verification detected business logic issues. Please debug and fix.", 
                                        0
                                    )
                                    if fixed_code:
                                        current_code = fixed_code
                                        logger.info("  Collaborative fix generated, retrying...")
                                        continue
                                
                                return {
                                    "success": False,
                                    "exit_code": 0,
                                    "stdout": result.output,
                                    "error_message": f"Agent verification failed: {failure_reason}",
                                    "execution_time": execution_time
                                }
                            
                            # MANDATORY OUTPUT FILE VERIFICATION
                            # Always check package.output_files (the task's expected outputs)
                            if package.output_files:
                                logger.info(f"  [VERIFICATION] Checking for {len(package.output_files)} expected output files...")
                                missing_files = []
                                found_files = []
                                
                                for file_name in package.output_files:
                                    file_path = task_dir / file_name
                                    if not file_path.exists():
                                        missing_files.append(file_name)
                                    else:
                                        file_size = file_path.stat().st_size
                                        found_files.append(f"{file_name} ({file_size} bytes)")
                                
                                if found_files:
                                    logger.info(f"  [VERIFICATION] Found: {', '.join(found_files)}")
                                
                                if missing_files:
                                    logger.error(f"  [VERIFICATION FAILED] Missing required files: {missing_files}")
                                    
                                    # If not last attempt, trigger collaborative debugging
                                    if attempt < self._max_execution_attempts:
                                        logger.info("  [COLLABORATIVE DEBUG] Fixing missing output files...")
                                        
                                        # File validation removed
                                        
                                        fixed_code = await self._get_collaborative_fix(
                                            package, 
                                            current_code, 
                                            f"OUTPUT FILE VERIFICATION FAILED:\n\nExpected: {package.output_files}\nMissing: {missing_files}\nFound: {found_files or 'None'}\n\nThe code exited with code 0 but did NOT create required output files.\n\nCOMMON CAUSES:\n1. Code relies on DB/file fallbacks that fail silently\n2. Path issues - writing to wrong directory\n3. No explicit file creation at end\n\nFIX:\n1. Create ALL output files in current working directory\n2. Use: open('filename.json', 'w') NOT absolute paths\n3. If data source fails, create sample/empty file to satisfy contract\n4. Add: assert os.path.exists('filename.json') before exit\n5. If assertion fails, exit with code 1", 
                                            0
                                        )
                                        if fixed_code:
                                            current_code = fixed_code
                                            logger.info("  Collaborative fix generated, retrying...")
                                            continue
                                    
                                    return {
                                        "success": False,
                                        "exit_code": 0,
                                        "stdout": result.output,
                                        "error_message": f"OUTPUT VERIFICATION FAILED: Missing {missing_files}. Task MUST create these files.",
                                        "execution_time": execution_time
                                    }
                                else:
                                    logger.info(f"  [VERIFICATION PASSED] All {len(package.output_files)} output files created")
                        
                        except Exception as e:
                            logger.warning(f"  [WARNING] Could not verify agent result JSON: {e}")
                    
                    # For load tasks, verify the result.json to check if data was actually loaded
                    is_load_task_flag = is_load_task(package.description)
                    if is_load_task_flag:
                        # Reuse task_dir from general verification above
                        result_json_path = task_dir / "result.json"
                        
                        if result_json_path.exists():
                            try:
                                with open(result_json_path, 'r') as f:
                                    task_result = json.load(f)
                                
                                # Check for failure indicators in the result
                                failed = False
                                failure_reason = ""
                                
                                if not task_result.get('success', True):
                                    failed = True
                                    failure_reason = task_result.get('error', 'Task marked as failed in result.json')
                                elif 'records_inserted' in task_result and task_result['records_inserted'] == 0:
                                    failed = True
                                    failure_reason = f"No records inserted: {task_result.get('message', 'Unknown reason')}"
                                elif 'error' in task_result and task_result['error']:
                                    failed = True
                                    failure_reason = task_result['error']
                                
                                if failed:
                                    logger.error(f"  [LOAD VERIFICATION FAILED] {failure_reason}")
                                    
                                    # If not last attempt, trigger collaborative debugging
                                    if attempt < self._max_execution_attempts:
                                        logger.info("  [COLLABORATIVE DEBUG] Analyzing load failure...")
                                        fixed_code = await self._get_collaborative_fix(
                                            package, 
                                            current_code, 
                                            f"Load task verification failed:\n{json.dumps(task_result, indent=2)}\n\nReason: {failure_reason}\n\nThe code executed without Python errors but failed to complete the data load task. Please debug and fix the business logic.", 
                                            0  # exit_code was 0, but task failed
                                        )
                                        if fixed_code:
                                            current_code = fixed_code
                                            logger.info("  Collaborative fix generated, retrying...")
                                            continue
                                    
                                    return {
                                        "success": False,
                                        "exit_code": 0,
                                        "stdout": result.output,
                                        "error_message": f"Load verification failed: {failure_reason}",
                                        "execution_time": execution_time
                                    }
                                else:
                                    logger.info(f"  [LOAD VERIFIED] Task completed successfully")
                            except Exception as e:
                                logger.warning(f"  [WARNING] Could not parse result.json: {e}")
                    
                    return {
                        "success": True,
                        "exit_code": result.exit_code,
                        "stdout": result.output,
                        "execution_time": execution_time
                    }
                else:
                    logger.error(f"  [FAILED] Exit code: {result.exit_code}")
                    logger.error(f"  Output: {result.output[:200]}...")
                    
                    # If not last attempt, use COLLABORATIVE debugging (Claude + GPT-5)
                    if attempt < self._max_execution_attempts:
                        logger.info("  [COLLABORATIVE DEBUG] Claude + GPT-5 analyzing error...")
                        fixed_code = await self._get_collaborative_fix(
                            package, current_code, result.output, result.exit_code
                        )
                        if fixed_code:
                            current_code = fixed_code
                            logger.info("  Collaborative fix generated, retrying...")
                            continue
                    
                    return {
                        "success": False,
                        "exit_code": result.exit_code,
                        "stdout": result.output,
                        "error_message": f"Exit code: {result.exit_code}",
                        "execution_time": execution_time
                    }
            
            except Exception as e:
                logger.error(f"  [EXCEPTION] {str(e)}")
                
                # If not last attempt, use COLLABORATIVE debugging
                if attempt < self._max_execution_attempts:
                    logger.info("  [COLLABORATIVE DEBUG] Claude + GPT-5 analyzing exception...")
                    fixed_code = await self._get_collaborative_fix(
                        package, current_code, str(e), -1
                    )
                    if fixed_code:
                        current_code = fixed_code
                        logger.info("  Collaborative fix generated, retrying...")
                        continue
                
                if attempt == self._max_execution_attempts:
                    return {
                        "success": False,
                        "exit_code": -1,
                        "error_message": str(e)
                    }
        
        return {
            "success": False,
            "exit_code": -1,
            "error_message": "Max execution attempts reached"
        }
    
    async def _get_claude_code(
        self,
        package: SubtaskPackage,
        output_file: str,
        previous_suggestions: list,
        accumulated_learnings: List[Dict[str, Any]] = None,
        rag_context: Dict[str, Any] = None,
        gpt5_examples: List[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """Get Claude's code implementation (with GPT-5's working examples if available)"""
        
        # Format output files as a clear list
        if package.output_files:
            output_files_str = "\n   ".join([f"- {f}" for f in package.output_files])
        else:
            output_files_str = "None (only save execution result)"
        
        # NEW: Build expected_output_files section for Claude's prompt
        # CRITICAL FIX: Read from top-level field, not buried in data dict
        expected_files = package.expected_output_files if hasattr(package, 'expected_output_files') else []
        
        # Fallback to data dict for backward compatibility
        if not expected_files and isinstance(package.data, dict):
            expected_files = package.data.get('expected_output_files', [])
        
        if expected_files:
            # File validation removed - let tasks handle their own outputs
            expected_output_files_section = ""
        else:
            expected_output_files_section = """
**OUTPUT FILES - YOUR CHOICE:**

Phase 1 did not specify exact filenames.
You have full freedom to choose:
- File formats (CSV, JSON, Parquet, Delta, HDF5, etc.)
- File naming conventions
- Number of output files

**Choose the format that best fits your task and data:**
- Consider the data characteristics
- Consider the processing requirements
- Consider downstream usage
- Use whatever format makes the most sense!

Document all files in task_learnings.json with full paths.
"""
        
        # Check if this is a load/insert task using centralized function
        is_load_task_flag = is_load_task(package.description)
        
        prompt_parts = []
        prompt_parts.append(f"TASK: {package.description}")
        
        # NEW: Include RAG context from Knowledge System (semantic search over past learnings)
        if rag_context and rag_context.get('similar_tasks'):
            prompt_parts.append(f"\n**✨ RELEVANT PAST LEARNINGS (FROM RAG MEMORY) ✨**")
            prompt_parts.append("🔍 **READ THESE FIRST!** Similar tasks have already solved problems you might face.")
            prompt_parts.append("💡 These learnings can save you time and prevent errors - use them actively!")
            for i, learning_item in enumerate(rag_context['similar_tasks'][:3], 1):  # Top 3 most relevant
                prompt_parts.append(f"\nLearning {i} (from task {learning_item['task_id']}, similarity: {learning_item.get('similarity', 'N/A')}):")
                prompt_parts.append("```json")
                prompt_parts.append(json.dumps(learning_item.get('learnings', {}), indent=2))
                prompt_parts.append("```")
            prompt_parts.append("✅ **ACTION REQUIRED**: Apply these patterns to your implementation!")
            prompt_parts.append("✅ Avoid errors that were already encountered and fixed!")
            prompt_parts.append("✅ Reuse successful approaches from similar tasks!")
        
        # SIMPLIFIED: Just dump EVERYTHING we know from prior tasks
        if accumulated_learnings:
            prompt_parts.append(f"\n**📚 ACCUMULATED KNOWLEDGE FROM ALL PRIOR TASKS 📚**")
            prompt_parts.append("```json")
            prompt_parts.append(json.dumps(accumulated_learnings, indent=2))
            prompt_parts.append("```")
            prompt_parts.append("⚠️ **CRITICAL**: This knowledge is GOLD - USE IT!")
            prompt_parts.append("✅ Table names, column names, schemas - already discovered for you")
            prompt_parts.append("✅ Connection strings, drivers, credentials - ready to use")
            prompt_parts.append("✅ Patterns that worked, issues that were fixed - learn from them")
            prompt_parts.append("🚀 **DON'T WASTE TIME REDISCOVERING** - build on what's already known!")
        
        # CONDITIONAL CREDENTIAL INJECTION
        if package.credentials:
            prompt_parts.append(f"\n**CREDENTIALS (USE THESE DIRECTLY - DO NOT CREATE LOADING FUNCTIONS):**")
            prompt_parts.append("```json")
            prompt_parts.append(json.dumps(package.credentials, indent=2))
            prompt_parts.append("```")
            prompt_parts.append("These credentials are ready to use. Access them like: creds['source']['host'], creds['target']['database'], etc.")
            prompt_parts.append("DO NOT look for credential files or environment variables - use the JSON above directly.")
        else:
            prompt_parts.append(f"\n**NO CREDENTIALS PROVIDED** - This task doesn't require database/API connections.")
            prompt_parts.append("This is a pure data transformation or analysis task. Work with provided data only.")
        
        # NEW: Provide explicit source file paths for initial tasks
        source_file_paths = package.data.get('source_file_paths', [])
        if source_file_paths:
            prompt_parts.append(f"\n**📁 SOURCE DATA FILES (Ready to Use):**")
            prompt_parts.append(f"Your task needs to work with source data. Absolute paths are provided:")
            for source_path in source_file_paths:
                file_name = Path(source_path).name
                prompt_parts.append(f"  ✓ {file_name}")
                prompt_parts.append(f"    Path: {source_path}")
            prompt_parts.append(f"")
            prompt_parts.append(f"🎯 **Use these paths directly - no file discovery needed!**")
            prompt_parts.append(f"```python")
            prompt_parts.append(f"import pandas as pd")
            prompt_parts.append(f"")
            prompt_parts.append(f"# Source file paths are provided in package.data")
            prompt_parts.append(f"source_paths = package.data.get('source_file_paths', [])")
            prompt_parts.append(f"if source_paths:")
            prompt_parts.append(f"    df = pd.read_csv(source_paths[0])  # Use the provided path directly")
            prompt_parts.append(f"```")
            prompt_parts.append(f"")
        
        # NEW: Show orchestrator-provided file paths with rich metadata (HIGHEST PRIORITY)
        if package.input_file_paths:
            prompt_parts.append(f"\n{'='*60}")
            prompt_parts.append(f"ORCHESTRATOR-PROVIDED INPUT FILES (USE THESE FIRST)")
            prompt_parts.append(f"{'='*60}")
            prompt_parts.append(f"The orchestrator has intelligently resolved input files for you:")
            prompt_parts.append(f"")
            
            # Check if we have rich metadata
            has_metadata = hasattr(package, 'input_file_metadata') and package.input_file_metadata
            
            for idx, file_path in enumerate(package.input_file_paths, 1):
                file_name = Path(file_path).name
                prompt_parts.append(f"  {idx}. {file_name}")
                prompt_parts.append(f"     Path: {file_path}")
                
                # Add rich metadata if available
                if has_metadata and idx <= len(package.input_file_metadata):
                    metadata = package.input_file_metadata[idx - 1]
                    prompt_parts.append(f"     Description: {metadata.get('description', 'No description')}")
                    prompt_parts.append(f"     File type: {metadata.get('type', 'unknown')}")
                    prompt_parts.append(f"     From task: {metadata.get('source_task', 'unknown')}")
                    size_kb = metadata.get('size_bytes', 0) / 1024
                    prompt_parts.append(f"     Size: {size_kb:.1f} KB")
                
                prompt_parts.append(f"")
            
            prompt_parts.append(f"✅ **THESE PATHS ARE ABSOLUTE AND READY TO USE**")
            prompt_parts.append(f"✅ **No file discovery needed** - orchestrator already found them")
            prompt_parts.append(f"✅ **Simply use these paths directly in your code**")
            prompt_parts.append(f"")
            prompt_parts.append(f"Example:")
            prompt_parts.append(f"```python")
            prompt_parts.append(f"import pandas as pd")
            prompt_parts.append(f"")
            prompt_parts.append(f"# Use orchestrator-provided paths directly")
            if len(package.input_file_paths) > 0:
                first_file = package.input_file_paths[0]
                ext = Path(first_file).suffix.lower()
                if ext == '.csv':
                    prompt_parts.append(f"df = pd.read_csv(r'{first_file}')")
                elif ext == '.json':
                    prompt_parts.append(f"with open(r'{first_file}', 'r') as f:")
                    prompt_parts.append(f"    data = json.load(f)")
                elif ext in ['.parquet', '.pq']:
                    prompt_parts.append(f"df = pd.read_parquet(r'{first_file}')")
                else:
                    prompt_parts.append(f"# Read from: {first_file}")
            prompt_parts.append(f"```")
            prompt_parts.append(f"")
        
        if package.execution_guidance:
            prompt_parts.append(f"**EXECUTION GUIDANCE FROM ORCHESTRATOR:**")
            prompt_parts.append(f"{package.execution_guidance}")
            prompt_parts.append(f"")
        
        # Tell Claude about dependencies and encourage Catalog usage
        if package.input_files:
            prompt_parts.append(f"\n**📂 INPUT FILES FROM DEPENDENCIES:**")
            prompt_parts.append(f"Your task depends on outputs from {len(package.input_files)} upstream task(s):")
            
            for dep_id, file_paths in package.input_files.items():
                # Handle both single file (str) and multiple files (list)
                if isinstance(file_paths, str):
                    file_paths = [file_paths]
                
                prompt_parts.append(f"  - Dependency: {dep_id}")
                for file_path in file_paths:
                    file_name = Path(file_path).name
                    prompt_parts.append(f"    File: {file_name}")
            
            prompt_parts.append(f"\n**🔍 HOW TO ACCESS FILES - USE THE DATA CATALOG:**")
            prompt_parts.append(f"```python")
            prompt_parts.append(f"from control_plane_v2.data_catalog import DataCatalog")
            prompt_parts.append(f"")
            prompt_parts.append(f"catalog_location = package.data.get('catalog_location')")
            prompt_parts.append(f"catalog = DataCatalog(catalog_location)")
            prompt_parts.append(f"")
            prompt_parts.append(f"# Search for files by name pattern")
            prompt_parts.append(f"files = catalog.search_files(name_pattern='*.csv')")
            prompt_parts.append(f"# Files come with full absolute paths - ready to use!")
            prompt_parts.append(f"")
            prompt_parts.append(f"# Or search by task that created them")
            prompt_parts.append(f"files = catalog.get_files_by_task('dependency_task_id')")
            prompt_parts.append(f"```")
            prompt_parts.append(f"")
            prompt_parts.append(f"✅ **The Catalog tracks ALL files with full paths** - use it to find what you need")
            prompt_parts.append(f"✅ **No hardcoding, no guessing** - catalog knows where everything is")
            prompt_parts.append(f"✅ **Dynamic file discovery** - works regardless of file locations")
            
            # Special guidance for merge operations
            is_merge = infer_task_type(package.description) == 'merge'
            if is_merge and len(package.input_files) > 1:
                prompt_parts.append(f"\n**💡 MERGE TASK TIP - Use Catalog for Dynamic Discovery:**")
                prompt_parts.append(f"```python")
                prompt_parts.append(f"from control_plane_v2.data_catalog import DataCatalog")
                prompt_parts.append(f"import pandas as pd  # or whatever library you need")
                prompt_parts.append(f"")
                prompt_parts.append(f"catalog = DataCatalog(package.data.get('catalog_location'))")
                prompt_parts.append(f"")
                prompt_parts.append(f"# Find all files from your dependencies dynamically")
                prompt_parts.append(f"# Option 1: By pattern")
                prompt_parts.append(f"data_files = catalog.search_files(name_pattern='*batch*.csv')")
                prompt_parts.append(f"")
                prompt_parts.append(f"# Option 2: By specific tasks")
                prompt_parts.append(f"# data_files = []")
                prompt_parts.append(f"# for dep_task in ['task1', 'task2', 'task3']:")
                prompt_parts.append(f"#     files = catalog.get_files_by_task(dep_task)")
                prompt_parts.append(f"#     data_files.extend(files)")
                prompt_parts.append(f"")
                prompt_parts.append(f"# Load and merge dynamically")
                prompt_parts.append(f"all_data = []")
                prompt_parts.append(f"for file_info in data_files:")
                prompt_parts.append(f"    df = pd.read_csv(file_info['path'])  # Use 'path' from catalog")
                prompt_parts.append(f"    all_data.append(df)")
                prompt_parts.append(f"")
                prompt_parts.append(f"merged = pd.concat(all_data, ignore_index=True)")
                prompt_parts.append(f"```")
                prompt_parts.append("🚀 Let the Catalog find files - no hardcoding, fully dynamic!")
        
        # DYNAMIC: List ALL files actually present in the task workspace
        # This ensures Claude knows about source files from user_uploads AND dependency files
        workspace_files = []
        try:
            task_dir = self._workspace_manager.get_task_directory('phase2', package.subtask_id, create=False)
            if task_dir and task_dir.exists():
                for file_path in task_dir.glob("*"):
                    if file_path.is_file() and not file_path.name.startswith('.') and file_path.suffix not in ['.py', '.json', '.txt', '.log']:
                        workspace_files.append({
                            'name': file_path.name,
                            'path': str(file_path.absolute()),
                            'size': file_path.stat().st_size
                        })
        except Exception as e:
            logger.warning(f"Could not scan workspace for files: {e}")
        
        if workspace_files:
            prompt_parts.append(f"\n**📁 FILES AVAILABLE IN YOUR WORKSPACE (READY TO USE):**")
            prompt_parts.append(f"The following {len(workspace_files)} file(s) are already in your task directory:")
            for wf in workspace_files:
                size_kb = wf['size'] / 1024
                prompt_parts.append(f"  ✅ {wf['name']} ({size_kb:.1f} KB)")
            prompt_parts.append(f"\n**HOW TO USE THESE FILES:**")
            prompt_parts.append(f"Simply reference by filename: '{workspace_files[0]['name']}' (it's in your current directory)")
            prompt_parts.append(f"Or use absolute path if needed: r'{workspace_files[0]['path']}'")
            prompt_parts.append(f"⚠️ NO NEED to search for these files - they're already here!")
        
        prompt_parts.append(f"\nDATA:")
        prompt_parts.append(json.dumps(package.data, indent=2))
        
        # Add execution hints from manifest (LLM will use what's relevant)
        if package.execution_hints:
            prompt_parts.append(f"\nEXECUTION HINTS:")
            # Convert Pydantic model to dict for JSON serialization
            hints_dict = package.execution_hints.dict() if hasattr(package.execution_hints, 'dict') else package.execution_hints.model_dump()
            prompt_parts.append(json.dumps(hints_dict, indent=2))
        
        if package.columns_needed:
            prompt_parts.append(f"\nCOLUMNS NEEDED: {', '.join(package.columns_needed)}")
        
        if previous_suggestions:
            prompt_parts.append(f"\nGPT-5'S SUGGESTIONS (consider them if useful):")
            for sugg in previous_suggestions:
                prompt_parts.append(f"  - {sugg}")
        
        # Show GPT-5's actual code fixes if provided
        if gpt5_examples:
            prompt_parts.append(f"\n{'='*60}")
            prompt_parts.append(f"GPT-5 CODE CONTRIBUTIONS (Direct Fixes)")
            prompt_parts.append(f"{'='*60}")
            prompt_parts.append(f"GPT-5 wrote and executed actual fixes in your workspace:")
            
            working_fixes = [ex for ex in gpt5_examples if ex.get('success')]
            failed_fixes = [ex for ex in gpt5_examples if not ex.get('success')]
            
            if working_fixes:
                prompt_parts.append(f"\n*** WORKING FIXES (Verified) ***")
                for idx, fix in enumerate(working_fixes, 1):
                    prompt_parts.append(f"\n--- Fix {idx}: {fix.get('purpose', 'Solution')} ---")
                    prompt_parts.append(f"```python")
                    prompt_parts.append(fix.get('code', ''))
                    prompt_parts.append(f"```")
                    prompt_parts.append(f"✓ EXECUTED SUCCESSFULLY")
                    if fix.get('output'):
                        prompt_parts.append(f"Output:")
                        prompt_parts.append(f"```")
                        prompt_parts.append(fix.get('output', ''))
                        prompt_parts.append(f"```")
                    if fix.get('explanation'):
                        prompt_parts.append(f"GPT-5's explanation: {fix.get('explanation')}")
                    prompt_parts.append(f"\n→ This is a WORKING solution you can adapt or use directly!")
            
            if failed_fixes:
                prompt_parts.append(f"\n*** Attempted Fixes (Had issues) ***")
                for idx, fix in enumerate(failed_fixes, 1):
                    prompt_parts.append(f"\n--- Attempt {idx}: {fix.get('purpose', 'Fix')} ---")
                    prompt_parts.append(f"```python")
                    prompt_parts.append(fix.get('code', ''))
                    prompt_parts.append(f"```")
                    prompt_parts.append(f"✗ Had execution errors:")
                    prompt_parts.append(f"```")
                    prompt_parts.append(fix.get('output', ''))
                    prompt_parts.append(f"```")
            
            prompt_parts.append(f"{'='*60}")
            prompt_parts.append(f"GPT-5 is actively contributing - learn from or use these fixes!")
            prompt_parts.append(f"")
        
        # Add verification requirement for load tasks
        if is_load_task_flag:
            prompt_parts.append(f"\n**CRITICAL - VERIFICATION REQUIRED FOR LOAD TASK:**")
            prompt_parts.append(f"After loading/inserting data, you MUST verify the operation was successful:")
            prompt_parts.append(f"1. Query the target table to count rows BEFORE and AFTER the insert")
            prompt_parts.append(f"2. Calculate actual records_inserted = count_after - count_before")
            prompt_parts.append(f"3. Compare records_inserted with expected count from input data")
            prompt_parts.append(f"4. Sample a few rows to confirm column values are correct")
            prompt_parts.append(f"5. Save verification result to 'result.json' with this structure:")
            prompt_parts.append(f"   {{")
            prompt_parts.append(f"     \"success\": true/false,")
            prompt_parts.append(f"     \"records_inserted\": <number>,")
            prompt_parts.append(f"     \"records_expected\": <number>,")
            prompt_parts.append(f"     \"error\": \"error message if failed, empty string if success\",")
            prompt_parts.append(f"     \"message\": \"detailed verification message\"")
            prompt_parts.append(f"   }}")
            prompt_parts.append(f"6. Set success=False if: records_inserted != records_expected OR any verification check fails")
            prompt_parts.append(f"7. IMPORTANT: If load fails due to column mismatch, check if input data has source columns that should be mapped to target columns")
        
        prompt_parts.append(f"\nWrite complete, executable Python code.")
        
        prompt = "\n".join(prompt_parts)
        
        # Get task workspace for isolation message
        task_workspace = getattr(self._code_executor, 'work_dir', 'current directory')
        
        # Build input files section for system prompt with rich metadata
        input_files_section = ""
        example_input_path = "C:/path/to/input.csv"
        
        if package.input_file_paths:
            lines = []
            
            # Check if we have rich metadata for files
            has_metadata = hasattr(package, 'input_file_metadata') and package.input_file_metadata
            
            for idx, fp in enumerate(package.input_file_paths, 1):
                lines.append(f"  {idx}. {Path(fp).name}")
                lines.append(f"     Full path: {fp}")
                
                # NEW: Add rich metadata if available
                if has_metadata and idx <= len(package.input_file_metadata):
                    metadata = package.input_file_metadata[idx - 1]
                    lines.append(f"     Description: {metadata.get('description', 'No description')}")
                    lines.append(f"     File type: {metadata.get('type', 'unknown')}")
                    lines.append(f"     From task: {metadata.get('source_task', 'unknown')}")
                    size_kb = metadata.get('size_bytes', 0) / 1024
                    lines.append(f"     Size: {size_kb:.1f} KB")
                
                lines.append("")  # Blank line between files
            
            input_files_section = "\n".join(lines)
            example_input_path = package.input_file_paths[0]
        else:
            input_files_section = "  No input files provided for this task."
        
        coding_prompt = self.CLAUDE_CODING_PROMPT.format(
            task_workspace=task_workspace,
            expected_output_files_section=expected_output_files_section,
            output_file=output_file,
            output_files_str=output_files_str,
            task_description=package.description,
            input_files_section=input_files_section,
            example_input_path=example_input_path
        )
        
        messages = [
            SystemMessage(content=coding_prompt),
            UserMessage(content=prompt, source="user")
        ]
        
        try:
            response = await self._claude_client.create(messages=messages)
            
            content = response.content
            if isinstance(content, list):
                content = content[0] if content else ""
            
            result = self._parse_json_response(str(content), ClaudeCodeResponse)
            
            if not result:
                logger.error("  Claude failed to generate code")
                # DEBUG: Show Claude's raw response
                logger.error(f"  [CLAUDE RAW RESPONSE] First 1000 chars:\n{str(content)[:1000]}...")
                return None
            
            # Return a dict for backwards compatibility with existing code
            return {
                "code": result.code,
                "explanation": result.explanation,
                "approach": result.approach
            }
        
        except Exception as e:
            logger.error(f"Claude code generation failed: {e}")
            return None
    
    async def _get_claude_fix(
        self,
        package: SubtaskPackage,
        failed_code: str,
        error_output: str
    ) -> Optional[str]:
        """Ask Claude to fix failed code"""
        
        prompt = f"""Your code failed. Please fix it.

ORIGINAL TASK: {package.description}

YOUR CODE:
```python
{failed_code}
```

ERROR OUTPUT:
{error_output}

CRITICAL - DATA PRESERVATION:
- DO NOT delete, truncate, or drop existing data unless EXPLICITLY specified in manifest
- INSERT strategy means APPEND to existing data, not replace
- If you encounter duplicate key errors, handle them (skip duplicates, fail gracefully, etc.)
- NEVER use TRUNCATE, DELETE FROM, or DROP unless the manifest explicitly instructs it
- Preserve existing data integrity - only add new data

CRITICAL - WINDOWS CONSOLE ENCODING:
- You are running on Windows with cp1252 encoding
- NEVER use Unicode symbols in print() or logging statements
- Use ASCII only: [OK], [ERROR], [WARN], +, -, *, etc.
- NO checkmarks, NO arrows, NO special symbols (no \\u2713, \\u2717, etc.)

Please provide the FIXED code in JSON format:
{{
  "code": "fixed Python code as a string"
}}
"""
        
        messages = [
            SystemMessage(content="You are a Python developer fixing a bug in your code."),
            UserMessage(content=prompt, source="user")
        ]
        
        try:
            response = await self._claude_client.create(messages=messages)
            
            content = response.content
            if isinstance(content, list):
                content = content[0] if content else ""
            
            result = self._parse_json_response(str(content), ClaudeCodeResponse)
            
            return result.code if result else None
        
        except Exception as e:
            logger.error(f"Claude fix failed: {e}")
            return None
    
    async def _get_collaborative_fix(
        self,
        package: SubtaskPackage,
        failed_code: str,
        error_output: str,
        exit_code: int
    ) -> Optional[str]:
        """
        Collaborative debugging: GPT-5 analyzes root cause, Claude fixes based on analysis
        This implements the "debugging instructions" requested by Phase 1
        """
        
        # Step 1: Query RAG for similar error patterns
        similar_errors_context = ""
        if self._knowledge_system:
            try:
                similar_errors = self._knowledge_system.search_solutions_for_error(
                    error_output
                )
                if similar_errors:
                    logger.info(f"    [RAG] Found {len(similar_errors)} similar past errors")
                    similar_errors_context = "\n\nSIMILAR ERRORS SOLVED BEFORE:\n"
                    for i, err in enumerate(similar_errors, 1):
                        similar_errors_context += f"\n{i}. Task: {err.get('task_id', 'unknown')}\n"
                        similar_errors_context += f"   Error: {err.get('error_snippet', 'N/A')}\n"
                        similar_errors_context += f"   Solution: {err.get('solution', 'N/A')}\n"
                        similar_errors_context += f"   Key lesson: {err.get('key_lesson', 'N/A')}\n"
                    similar_errors_context += "\nUse these past solutions to avoid repeating the same debugging cycle!\n"
                else:
                    logger.info("    [RAG] No similar past errors found")
            except Exception as e:
                logger.warning(f"    [RAG] Failed to query similar errors: {e}")
        
        # Step 2: GPT-5 analyzes the error and provides root cause analysis
        logger.info("    [GPT-5] Analyzing root cause...")
        
        gpt5_prompt = f"""You are a debugging expert. Analyze this error and identify the ROOT CAUSE WITH SPATIAL AWARENESS.

TASK: {package.description}

AVAILABLE DATA/CREDENTIALS:
{json.dumps(package.credentials, indent=2)}

DATA STRUCTURE:
{json.dumps(package.data, indent=2) if package.data else "No data provided"}

FAILED CODE:
```python
{failed_code}
```

ERROR (Exit Code: {exit_code}):
{error_output}

CRITICAL - EXECUTION ORDER ANALYSIS:
1. Identify the EXACT line number that crashes (from traceback above)
2. Search the failed code for validation/fixes (isinstance, try-except, type checks)
3. If fixes exist, check if they come BEFORE or AFTER the crash line
4. If fixes come AFTER the crash line:
   - State: "Line X crashes, but validation on line Y comes too late"
   - Suggest: "Move validation to BEFORE line X - immediately after data loading"
5. Pay SPECIAL attention to:
   - Print statements with .get(), len(), indexing between load and validation
   - F-strings that assume data structure before it's validated
   - Operations in try block before isinstance checks
   - Exception handlers that mask the real error

Your spatial analysis should:
- Identify the exact crash line number
- Check if validation exists but comes too late
- Recommend where to place the fix relative to the crash line

DEBUGGING INSTRUCTIONS:
When encountering errors with data:
1. FIRST: Identify crash line number from traceback
2. SECOND: Check if validation exists in code but comes too late
3. THIRD: Check what data is ACTUALLY available vs. what's expected
4. FOURTH: Identify schema mismatches, data type issues, or missing columns
5. FIFTH: Look for fundamental design issues, not just syntax errors
6. THEN: Provide fix with EXACT line placement guidance
{similar_errors_context}

Provide your analysis in JSON format (STRICT SCHEMA):
{{
  "root_cause": "What is the actual underlying problem? Include crash line number. (required, cannot be empty)",
  "fix_suggestions": [
    "Specific fix suggestion 1 with line numbers",
    "Specific fix suggestion 2 with line numbers"
  ],  // Array of strings (required, must have at least one suggestion)
  "spatial_analysis": "Line-by-line analysis of where the crash occurs and where validation should be. (optional)",
  "similar_patterns": "Reference to similar errors from RAG if provided above. (optional)"
}}

CRITICAL:
- root_cause MUST be a detailed string explaining the problem (cannot be empty)
- fix_suggestions MUST be an array with at least one suggestion (cannot be empty array)
- Be specific about line numbers and exact code changes needed
"""
        
        gpt5_messages = [
            SystemMessage(content="You are an expert debugger who identifies root causes, not just symptoms."),
            UserMessage(content=gpt5_prompt, source="user")
        ]
        
        try:
            gpt5_response = await self._gpt5_client.create(messages=gpt5_messages)
            gpt5_content = gpt5_response.content
            if isinstance(gpt5_content, list):
                gpt5_content = gpt5_content[0] if gpt5_content else ""
            
            analysis = self._parse_json_response(str(gpt5_content), GPT5DebugResponse)
            
            if not analysis:
                logger.warning("    [GPT-5] Failed to parse analysis, falling back to Claude-only fix")
                return await self._get_claude_fix(package, failed_code, error_output)
            
            logger.debug(f"    [GPT-5] Root cause: {analysis.root_cause[:80]}...")
            if analysis.spatial_analysis:
                logger.debug(f"    [GPT-5] Spatial analysis: {analysis.spatial_analysis[:80]}...")
            if analysis.fix_suggestions:
                logger.info(f"    [GPT-5] Identified {len(analysis.fix_suggestions)} fix suggestion(s)")
            
            # NEW: GPT-5 writes and executes actual fixes (not just suggestions)
            logger.info("    [GPT-5] Writing actual code fixes and executing them...")
            task_dir = self._workspace_manager.get_task_directory('phase2', package.subtask_id, create=False)
            gpt5_fixes = await self._get_gpt5_executable_examples(
                package, {'code': failed_code}, analysis.fix_suggestions, task_dir
            )
            
            gpt5_examples = []
            if gpt5_fixes:
                gpt5_examples = gpt5_fixes
                working_fixes = [f for f in gpt5_fixes if f.get('success')]
                if working_fixes:
                    logger.info(f"    [GPT-5] ✓ {len(working_fixes)} working fix(es) - direct contributions ready for Claude!")
                else:
                    logger.info(f"    [GPT-5] Attempted {len(gpt5_fixes)} fix(es) - results shared with Claude")
            
            # Step 2: Claude fixes the code based on GPT-5's analysis AND working examples
            logger.info("    [CLAUDE] Implementing fix based on GPT-5's analysis...")
            
            claude_prompt = f"""GPT-5 has analyzed the error. Use their insights to fix the code properly.

ORIGINAL TASK: {package.description}

YOUR FAILED CODE:
```python
{failed_code}
```

ERROR OUTPUT:
{error_output}

GPT-5'S ROOT CAUSE ANALYSIS:
- Root Cause: {analysis.root_cause}
- Spatial Analysis: {analysis.spatial_analysis or 'Not provided'}
- Fix Suggestions:
{chr(10).join(f'  {i+1}. {s}' for i, s in enumerate(analysis.fix_suggestions))}
- Similar Patterns: {analysis.similar_patterns or 'None found'}

{'='*60}
GPT-5 CODE CONTRIBUTIONS (Working Fixes):
{'='*60}
{self._format_gpt5_examples_for_claude(gpt5_examples) if gpt5_examples else 'GPT-5 did not provide executable code examples.'}

INSTRUCTIONS:
1. Read GPT-5's analysis carefully - they've identified the ROOT CAUSE
2. Don't just fix syntax - address the fundamental issue they identified
3. If there's a data/schema mismatch, adjust your strategy accordingly
4. Implement the suggested approach

CRITICAL - DATA PRESERVATION:
- DO NOT delete, truncate, or drop existing data unless EXPLICITLY specified in manifest
- INSERT strategy means APPEND to existing data, not replace
- If you encounter duplicate key errors, handle them (skip duplicates, fail gracefully, etc.)
- NEVER use TRUNCATE, DELETE FROM, or DROP unless the manifest explicitly instructs it
- Preserve existing data integrity - only add new data

CRITICAL - WINDOWS CONSOLE ENCODING:
- You are running on Windows with cp1252 encoding
- NEVER use Unicode symbols in print() or logging statements
- Use ASCII only: [OK], [ERROR], [WARN], +, -, *, etc.
- NO checkmarks, NO arrows, NO special symbols (no \\u2713, \\u2717, etc.)

Provide the FIXED code in JSON format:
{{
  "code": "fixed Python code as a string",
  "explanation": "How you addressed GPT-5's identified root cause"
}}
"""
            
            claude_messages = [
                SystemMessage(content="You are a Python developer who fixes bugs by addressing root causes, not symptoms."),
                UserMessage(content=claude_prompt, source="user")
            ]
            
            claude_response = await self._claude_client.create(messages=claude_messages)
            claude_content = claude_response.content
            if isinstance(claude_content, list):
                claude_content = claude_content[0] if claude_content else ""
            
            result = self._parse_json_response(str(claude_content), ClaudeCodeResponse)
            
            if result:
                logger.info(f"    [CLAUDE] Fix explanation: {result.explanation[:80]}...")
                return result.code
            
            logger.warning("    [CLAUDE] Failed to generate fix, trying solo fix")
            return await self._get_claude_fix(package, failed_code, error_output)
        
        except Exception as e:
            logger.error(f"    Collaborative fix failed: {e}")
            logger.info("    Falling back to Claude-only fix")
            return await self._get_claude_fix(package, failed_code, error_output)
    
    async def _get_gpt5_code_review(
        self,
        package: SubtaskPackage,
        code_gen: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Get GPT-5's review of Claude's code"""
        
        # Format output files as a clear list
        if package.output_files:
            output_files_str = "\n   ".join([f"- {f}" for f in package.output_files])
        else:
            output_files_str = "None (only save execution result)"
        
        prompt = f"""TASK: {package.description}

REQUIRED OUTPUT FILES: {output_files_str}

CLAUDE'S CODE:
```python
{code_gen['code']}
```

CLAUDE'S EXPLANATION:
{code_gen['explanation']}

APPROACH:
{code_gen['approach']}

Review this code for correctness and completeness.
"""
        
        review_prompt = self.GPT5_CODE_REVIEW_PROMPT.format(
            task_description=package.description,
            output_files_str=output_files_str
        )
        
        messages = [
            SystemMessage(content=review_prompt),
            UserMessage(content=prompt, source="user")
        ]
        
        try:
            response = await self._gpt5_client.create(messages=messages)
            
            content = response.content
            if isinstance(content, list):
                content = content[0] if content else ""
            
            result = self._parse_json_response(str(content), GPT5ReviewResponse)
            
            # Convert to dict for backwards compatibility
            if result:
                return {
                    "approved": result.approved,
                    "confidence": result.confidence,
                    "reasoning": result.reasoning,
                    "concerns": result.concerns,
                    "suggestions": result.suggestions
                }
            return None
        
        except Exception as e:
            logger.error(f"GPT-5 code review failed: {e}")
            return None
    
    def _extract_learnings(
        self,
        package: SubtaskPackage,
        code_result: Dict[str, Any],
        exec_result: Dict[str, Any],
        request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        AGENT-DRIVEN LEARNING: Read the task_learnings.json file that Claude creates.
        No complex extraction - the agent tells us what it learned!
        """
        learnings = {
            'task_id': package.subtask_id,
            'success': exec_result.get('success', False),
            'execution_time': exec_result.get('execution_time', 0.0),
        }
        
        # Read the learnings file that Claude created
        learnings_file = self._workspace_manager.base_dir / package.subtask_id / 'task_learnings.json'
        if learnings_file.exists():
            try:
                with open(learnings_file, 'r') as f:
                    agent_learnings = json.load(f)
                
                # Merge agent's explicit learnings
                learnings['agent_learnings'] = agent_learnings
                
                logger.info(f"[{package.subtask_id}] Agent provided learnings: {list(agent_learnings.keys())}")
            except Exception as e:
                logger.warning(f"[{package.subtask_id}] Could not read task_learnings.json: {e}")
        else:
            logger.warning(f"[{package.subtask_id}] No task_learnings.json found - agent didn't provide learnings")
        
        return learnings
    
    async def _get_gpt5_executable_examples(
        self,
        package: SubtaskPackage,
        claude_code: Dict[str, Any],
        concerns: List[str],
        task_workspace: Path
    ) -> List[Dict[str, Any]]:
        """
        GPT-5 writes and executes ACTUAL fixes (not just examples)
        
        This enables direct contribution:
        - GPT-5 writes the FIXED CODE that solves the issues
        - GPT-5 executes it to verify it works
        - Results are shared with Claude
        - Both agents actively contribute to the solution
        
        Returns: List of {code, output, purpose, explanation}
        """
        # Build comprehensive context (same as Claude gets)
        prompt_parts = []
        prompt_parts.append("You identified issues in Claude's code. Please provide an improved version that addresses these issues.\n")
        prompt_parts.append(f"**TASK:** {package.description}\n")
        
        # Show workspace files (same as Claude)
        workspace_files = []
        try:
            task_dir = self._workspace_manager.get_task_directory('phase2', package.subtask_id, create=False)
            if task_dir and task_dir.exists():
                for file_path in task_dir.glob("*"):
                    if file_path.is_file() and not file_path.name.startswith('.') and file_path.suffix not in ['.py', '.json', '.txt', '.log']:
                        workspace_files.append({
                            'name': file_path.name,
                            'path': str(file_path.absolute()),
                            'size': file_path.stat().st_size
                        })
        except Exception as e:
            logger.warning(f"Could not scan workspace for files: {e}")
        
        if workspace_files:
            prompt_parts.append("**FILES AVAILABLE IN WORKSPACE (READY TO USE):**")
            for wf in workspace_files:
                size_kb = wf['size'] / 1024
                prompt_parts.append(f"  - {wf['name']} ({size_kb:.1f} KB)")
                prompt_parts.append(f"    Path: {wf['path']}")
            prompt_parts.append("")
        
        # NEW: Show orchestrator-provided file paths with rich metadata (same as Claude)
        if package.input_file_paths:
            prompt_parts.append("="*60)
            prompt_parts.append("ORCHESTRATOR-PROVIDED INPUT FILES")
            prompt_parts.append("="*60)
            prompt_parts.append("The orchestrator has intelligently resolved input files:")
            prompt_parts.append("")
            
            # Check if we have rich metadata
            has_metadata = hasattr(package, 'input_file_metadata') and package.input_file_metadata
            
            for idx, file_path in enumerate(package.input_file_paths, 1):
                file_name = Path(file_path).name
                prompt_parts.append(f"  {idx}. {file_name}")
                prompt_parts.append(f"     Path: {file_path}")
                
                # Add rich metadata if available
                if has_metadata and idx <= len(package.input_file_metadata):
                    metadata = package.input_file_metadata[idx - 1]
                    prompt_parts.append(f"     Description: {metadata.get('description', 'No description')}")
                    prompt_parts.append(f"     File type: {metadata.get('type', 'unknown')}")
                    prompt_parts.append(f"     From task: {metadata.get('source_task', 'unknown')}")
                    size_kb = metadata.get('size_bytes', 0) / 1024
                    prompt_parts.append(f"     Size: {size_kb:.1f} KB")
                
                prompt_parts.append("")
            
            prompt_parts.append("These paths are absolute and ready to use - no discovery needed!")
            prompt_parts.append("")
        
        if package.execution_guidance:
            prompt_parts.append("**EXECUTION GUIDANCE FROM ORCHESTRATOR:**")
            prompt_parts.append(package.execution_guidance)
            prompt_parts.append("")
        
        # Show package data (credentials, connections, etc.) - same as Claude
        if package.data:
            prompt_parts.append("**PACKAGE DATA (Credentials, Connections, Config):**")
            prompt_parts.append("```json")
            prompt_parts.append(json.dumps(package.data, indent=2))
            prompt_parts.append("```\n")
        
        # Show input files from dependencies - same as Claude
        if package.input_files:
            prompt_parts.append("**INPUT FILES FROM DEPENDENCIES:**")
            for dep_id, file_paths in package.input_files.items():
                if isinstance(file_paths, str):
                    file_paths = [file_paths]
                prompt_parts.append(f"  Dependency: {dep_id}")
                for file_path in file_paths:
                    prompt_parts.append(f"    - {Path(file_path).name} ({file_path})")
            prompt_parts.append("")
        
        # Show expected output files
        if package.output_files:
            prompt_parts.append("**REQUIRED OUTPUT FILES:**")
            for outfile in package.output_files:
                prompt_parts.append(f"  - {outfile} (MUST be created)")
            prompt_parts.append("")
        
        prompt_parts.append("**CLAUDE'S CODE (with issues):**")
        prompt_parts.append("```python")
        prompt_parts.append(claude_code.get('code', '')[:3000])
        if len(claude_code.get('code', '')) > 3000:
            prompt_parts.append("... (truncated)")
        prompt_parts.append("```\n")
        
        prompt_parts.append("**ISSUES YOU IDENTIFIED:**")
        for i, concern in enumerate(concerns, 1):
            prompt_parts.append(f"{i}. {concern}")
        prompt_parts.append("")
        
        prompt_parts.append("""⚙️ **EXECUTION ENVIRONMENT - IMPORTANT:**
Your code will be executed as: `python script.py` (NO command-line arguments)
- sys.argv contains ONLY the script name
- Code MUST work without CLI arguments
- Find input files using glob, Data Catalog, or by checking workspace
- Example: If code expects --spec file.json, make it auto-discover file.json instead

✅ CORRECT Pattern:
```python
import glob
# Auto-discover files in workspace
spec_files = glob.glob('*_spec.json')
spec_file = spec_files[0] if spec_files else None
```

❌ WRONG Pattern:
```python
import sys
if len(sys.argv) < 2:
    sys.exit(1)  # Will ALWAYS fail!
```

**YOUR TASK:**
Please provide improved code that addresses the issues you identified.

**Requirements:**
- Address the issues mentioned above
- Use the files, credentials, and data from the workspace context
- Include necessary imports, error handling, and file I/O operations
- Ensure the code is ready for production use
- Provide a solution that Claude can learn from

**Approach Options:**
- Option 1: Provide a complete solution if feasible
- Option 2: Provide 1-3 focused improvements for key issues:
  * Data loading improvements
  * File path resolution
  * Schema handling

**Response Format (JSON):**
{
  "examples": [
    {
      "purpose": "Description of what this code addresses",
      "code": "# Python code here\\nimport pandas as pd\\n...",
      "explanation": "How this improves the solution"
    }
  ]
}

Note: The code should be functional and testable in the workspace environment described above.
""")
        
        prompt = "\n".join(prompt_parts)

        try:
            messages = [
                SystemMessage(content="You are GPT-5, an expert developer collaborating with Claude. You provide code improvements and working examples. You're a collaborative partner in the development process."),
                UserMessage(content=prompt, source="user")
            ]
            
            response = await self._gpt5_client.create(messages=messages)
            content = response.content
            if isinstance(content, list):
                content = content[0] if content else ""
            
            # Parse response using FIXED method (handles dict properly)
            data = self._parse_json_response(str(content), dict)
            if not data or not data.get('examples'):
                logger.info("  [GPT-5] Chose not to write fix code")
                # DEBUG: Show GPT-5's response
                logger.warning(f"  [GPT-5 RAW RESPONSE] First 1000 chars:\n{str(content)[:1000]}...")
                logger.warning(f"  [GPT-5 PARSED DATA] {data}")
                return []
            
            examples = data.get('examples', [])
            logger.info(f"  [GPT-5] Writing {len(examples)} fix(es) - will execute to verify")
            # DEBUG: Show examples structure
            logger.warning(f"  [GPT-5 EXAMPLES] Count: {len(examples)}, Keys in first: {examples[0].keys() if examples else 'N/A'}")
            
            # Execute each fix and capture output
            executed_fixes = []
            for idx, example in enumerate(examples[:2], 1):  # Limit to 2 complete fixes
                code = example.get('code', '')
                if not code:
                    logger.warning(f"  [GPT-5] Example {idx} has no code!")
                    continue
                
                purpose = example.get('purpose', 'Fix')
                logger.info(f"  [GPT-5] Executing fix {idx}: {purpose[:60]}...")
                
                # DEBUG: Log the actual code being executed
                logger.warning(f"  [GPT-5 CODE] First 500 chars:\n{code[:500]}...")
                
                # Execute in task workspace (same as Claude's workspace)
                code_block = CodeBlock(code=code, language="python")
                cancellation_token = CancellationToken()
                exec_result = await self._code_executor.execute_code_blocks(
                    code_blocks=[code_block],
                    cancellation_token=cancellation_token
                )
                
                # CommandLineCodeResult has .exit_code, .output, etc. (not a dict)
                if exec_result.exit_code == 0:
                    output = exec_result.output if hasattr(exec_result, 'output') else ''
                    logger.info(f"  [GPT-5] ✓ Fix {idx} WORKS - Solution verified!")
                    # DEBUG: Show full output
                    logger.warning(f"  [GPT-5 OUTPUT] {output[:1000]}")
                    executed_fixes.append({
                        'purpose': purpose,
                        'code': code,
                        'output': output[:1000],  # More output for full solutions
                        'explanation': example.get('explanation', ''),
                        'success': True
                    })
                else:
                    error = exec_result.output if hasattr(exec_result, 'output') else 'Unknown error'
                    logger.warning(f"  [GPT-5] ✗ Fix {idx} failed: {error[:100]}")
                    # DEBUG: Show full error
                    logger.warning(f"  [GPT-5 FULL ERROR] {error[:2000]}")
                    executed_fixes.append({
                        'purpose': purpose,
                        'code': code,
                        'output': f"ERROR: {error[:300]}",
                        'explanation': example.get('explanation', ''),
                        'success': False
                    })
            
            return executed_fixes
            
        except Exception as e:
            logger.error(f"  [GPT-5] Failed to write/execute fixes: {e}")
            return []
    
    def _load_package(self, package_path: str) -> SubtaskPackage:
        """Load subtask package from JSON file"""
        with open(package_path, 'r') as f:
            data = json.load(f)
        return SubtaskPackage(**data)
    
    def _parse_json_response(self, text: str, model_class: type) -> Optional[Any]:
        """
        Parse JSON from LLM response using Pydantic validation or raw JSON parsing.
        
        Args:
            text: Raw text from LLM
            model_class: Pydantic model class to validate against, or dict for raw JSON
            
        Returns:
            Validated Pydantic model instance or dict, or None if parsing fails
        """
        # Try to find JSON in the text (LLMs sometimes add markdown)
        start = text.find('{')
        end = text.rfind('}') + 1
        
        if start >= 0 and end > start:
            json_str = text[start:end]
            try:
                # CRITICAL FIX: Parse as dict first, clean code blocks, then validate with Pydantic
                parsed_dict = json.loads(json_str)
                
                # Strip markdown code blocks from 'code' field BEFORE Pydantic validation
                if isinstance(parsed_dict, dict) and 'code' in parsed_dict:
                    code = parsed_dict['code']
                    if isinstance(code, str):
                        # Remove markdown code block wrappers (```python ... ``` or ``` ... ```)
                        code = code.strip()
                        if code.startswith('```'):
                            # Find the first newline after the opening ```
                            first_newline = code.find('\n')
                            if first_newline != -1:
                                code = code[first_newline+1:]
                        if code.endswith('```'):
                            # Remove the closing ```
                            code = code[:-3].rstrip()
                        parsed_dict['code'] = code
                
                # Now validate with Pydantic if needed
                if model_class != dict:
                    parsed = model_class.model_validate(parsed_dict)
                else:
                    parsed = parsed_dict
                
                return parsed
                
            except ValidationError as e:
                logger.error(f"Pydantic validation failed for {model_class.__name__}:")
                for error in e.errors():
                    field = '.'.join(str(loc) for loc in error['loc'])
                    logger.error(f"  Field '{field}': {error['msg']}")
                logger.error(f"  Response excerpt: {text[:500]}...")
                logger.error(f"  [CLAUDE RAW RESPONSE] First 1000 chars:")
                logger.error(text[:1000] + "...")
                return None
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                logger.error(f"  Response excerpt: {text[:500]}...")
                return None
        
        # Try parsing the whole text
        try:
            parsed_dict = json.loads(text)
            
            # Strip markdown code blocks from 'code' field BEFORE Pydantic validation
            if isinstance(parsed_dict, dict) and 'code' in parsed_dict:
                code = parsed_dict['code']
                if isinstance(code, str):
                    # Remove markdown code block wrappers
                    code = code.strip()
                    if code.startswith('```'):
                        first_newline = code.find('\n')
                        if first_newline != -1:
                            code = code[first_newline+1:]
                    if code.endswith('```'):
                        code = code[:-3].rstrip()
                    parsed_dict['code'] = code
            
            # Now validate with Pydantic if needed
            if model_class != dict:
                parsed = model_class.model_validate(parsed_dict)
            else:
                parsed = parsed_dict
            
            return parsed
            
        except (ValidationError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse from response: {e}")
            logger.error(f"  Response excerpt: {text[:500]}...")
            return None
    
    def _format_gpt5_examples_for_claude(self, gpt5_examples: List[Dict[str, Any]]) -> str:
        """Format GPT-5's code examples for display in Claude's prompt."""
        if not gpt5_examples:
            return "No examples provided."
        
        parts = []
        working_fixes = [ex for ex in gpt5_examples if ex.get('success')]
        failed_fixes = [ex for ex in gpt5_examples if not ex.get('success')]
        
        if working_fixes:
            parts.append("\n*** WORKING FIXES (Verified) ***")
            for idx, fix in enumerate(working_fixes, 1):
                parts.append(f"\n--- Fix {idx}: {fix.get('purpose', 'Solution')} ---")
                parts.append("```python")
                parts.append(fix.get('code', ''))
                parts.append("```")
                parts.append("[OK] EXECUTED SUCCESSFULLY")
                if fix.get('output'):
                    parts.append("Output:")
                    parts.append("```")
                    parts.append(fix.get('output', ''))
                    parts.append("```")
                if fix.get('explanation'):
                    parts.append(f"GPT-5's explanation: {fix.get('explanation')}")
                parts.append("\n-> This is a WORKING solution you can adapt or use directly!")
        
        if failed_fixes:
            parts.append("\n*** Attempted Fixes (Had issues) ***")
            for idx, fix in enumerate(failed_fixes, 1):
                parts.append(f"\n--- Attempt {idx}: {fix.get('purpose', 'Fix')} ---")
                parts.append("```python")
                parts.append(fix.get('code', ''))
                parts.append("```")
                parts.append("[X] Had execution errors:")
                parts.append("```")
                parts.append(fix.get('output', ''))
                parts.append("```")
        
        return "\n".join(parts)
