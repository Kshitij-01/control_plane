# Autonomous Agent System - Setup Instructions

**Version:** 1.0  
**Date:** 2025-10-20

---

## Package Contents

This package contains all core files needed to run the autonomous multi-agent system.

### Included Files (45 total)

**Documentation:**
- `SYSTEM_CORE_FILES.md` - Complete file reference and architecture
- `SYSTEM_HOW_IT_WORKS.md` - Detailed workflow and code explanations
- `SETUP_INSTRUCTIONS.md` - This file

**Main Entry Point:**
- `control_plane_v2/run_control_plane.py` - System entry point

**Phase 0 (Classification):**
- `control_plane_v2/phase_0/` - 10 files

**Phase 1 (Division):**
- `control_plane_v2/phase_1/` - 5 files

**Phase 2 (Execution):**
- `control_plane_v2/phase_2/` - 8 files

**Agent Generation:**
- `control_plane_v2/agent_generator/` - 8 files

**Knowledge Systems:**
- `control_plane_v2/knowledge_system.py`
- `control_plane_v2/data_catalog.py`
- `control_plane_v2/azure_openai_rag_memory.py`

**Infrastructure:**
- `control_plane_v2/workspace_manager.py`
- `control_plane_v2/shared/` - 2 files
- `control_plane_v2/utils/` - 1 file

**Example Manifests:**
- `manifest_genomics_deep_analysis.json`
- `manifest_5m_simple.json`

---

## Prerequisites

### 1. Python Environment
- Python 3.10 or higher
- Virtual environment recommended

### 2. Required Python Packages

```bash
pip install autogen-core autogen-ext autogen-agentchat
pip install openai anthropic
pip install chromadb
pip install pydantic
pip install azure-identity azure-openai
```

Or use requirements file (create this):
```txt
autogen-core>=0.4.0
autogen-ext>=0.4.0
autogen-agentchat>=0.4.0
openai>=1.0.0
anthropic>=0.25.0
chromadb>=0.4.0
pydantic>=2.0.0
azure-identity>=1.15.0
```

### 3. API Keys Required

You need access to:
- **Azure OpenAI** (for GPT-5, GPT-4, embeddings)
- **Anthropic Claude** (for Claude 4.5 Sonnet)

---

## Installation Steps

### Step 1: Extract Package

```bash
# Extract the zip file to your desired location
unzip autonomous_agent_system.zip -d /path/to/project
cd /path/to/project
```

### Step 2: Create Virtual Environment

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate
```

### Step 3: Install Dependencies

```bash
pip install autogen-core autogen-ext autogen-agentchat
pip install openai anthropic chromadb pydantic azure-identity
```

### Step 4: Create Configuration File

Create `env_info.json` in the project root:

```json
{
  "azure_openai": {
    "endpoint": "https://your-endpoint.openai.azure.com/",
    "api_key": "your-azure-openai-api-key",
    "api_version": "2024-02-15-preview",
    "deployments": {
      "gpt4": "gpt-4-turbo",
      "gpt5": "o1-preview",
      "claude_sonnet": "claude-sonnet-4-5"
    }
  },
  "anthropic": {
    "api_key": "your-anthropic-api-key"
  }
}
```

**Important:** Keep `env_info.json` secure and never commit it to version control!

### Step 5: Create Required Directories

```bash
# Create runs directory
mkdir runs

# Create template user_uploads (optional)
mkdir -p runs/template/user_uploads
```

---

## Running the System

### Basic Usage

```bash
python -m control_plane_v2.run_control_plane --manifest path/to/manifest.json
```

### Example: Run Genomics Analysis

```bash
# Using included example manifest
python -m control_plane_v2.run_control_plane --manifest manifest_genomics_deep_analysis.json
```

### Example: Run EDA Task

```bash
# Using included EDA manifest
python -m control_plane_v2.run_control_plane --manifest manifest_5m_simple.json
```

---

## Creating Your Own Manifest

### Minimal Manifest Template

```json
{
  "task_name": "Your Task Name",
  "task_description": "Detailed description of what you want to accomplish",
  "input_data": {
    "primary_file": "path/to/input/file"
  },
  "transformation_config": {
    "skip_side_tasks": false
  },
  "user_uploads": [
    {
      "source": "path/to/source/file",
      "filename": "target_filename_in_workspace"
    }
  ],
  "output_requirements": {
    "format": "json",
    "quality_level": "high"
  }
}
```

### Manifest Fields Explained

- **task_name**: Short identifier for your task
- **task_description**: Detailed description (the more detail, the better)
- **input_data.primary_file**: Main input file path
- **transformation_config.skip_side_tasks**: Set to `true` to skip prerequisite checks
- **user_uploads**: Array of files to copy to workspace
  - **source**: Path relative to project root
  - **filename**: Name in the workspace
- **output_requirements**: Desired output format and quality

---

## Directory Structure After First Run

```
project_root/
  ├── control_plane_v2/          # System code
  ├── env_info.json              # Your API keys (create this)
  ├── manifest_*.json            # Task manifests
  ├── SYSTEM_CORE_FILES.md       # Documentation
  ├── SYSTEM_HOW_IT_WORKS.md     # Documentation
  └── runs/                      # Execution outputs
      └── run_YYYYMMDD_HHMMSS/   # Each run gets timestamped directory
          ├── phase0/            # Classification results
          ├── phase1/            # Task division plan
          ├── phase2/            # Task execution outputs
          │   ├── task_1/
          │   │   └── outputs/
          │   ├── task_2/
          │   │   └── outputs/
          │   └── ...
          ├── file_catalog.json  # File metadata
          └── vectordb/          # RAG memory
```

---

## Troubleshooting

### Issue: "env_info.json not found"

**Solution:** Create `env_info.json` in the project root with your API keys.

### Issue: "Module not found: autogen_core"

**Solution:** Install required packages:
```bash
pip install autogen-core autogen-ext autogen-agentchat
```

### Issue: "ChromaDB not available"

**Solution:** Install ChromaDB:
```bash
pip install chromadb
```

### Issue: Code execution timeout

**Solution:** Increase timeout in `control_plane_v2/phase_2/worker_agent_autonomous.py` line 47:
```python
code_executor = LocalCommandLineCodeExecutor(
    work_dir=str(workspace_path),
    timeout=3600  # Increase to 60 minutes
)
```

### Issue: "API rate limit exceeded"

**Solution:** 
- Wait and retry
- Use lower-tier models for testing
- Reduce task complexity

### Issue: Worker claiming success prematurely

**Solution:** Check Boss's `expected_outputs` in the execution plan. Ensure they're specific and complete.

---

## System Requirements

### Minimum:
- CPU: 4 cores
- RAM: 8 GB
- Disk: 10 GB free space
- Internet: Stable connection for API calls

### Recommended:
- CPU: 8+ cores
- RAM: 16 GB
- Disk: 50 GB free space (for large datasets)
- Internet: High-speed connection

---

## Cost Considerations

### API Costs

The system makes multiple LLM API calls:
- **Phase 0**: ~5-10 calls (Claude + GPT-5)
- **Phase 1**: ~10-20 calls (Claude + GPT-5)
- **Phase 2**: ~50-200 calls per task (depends on complexity)

**Estimated cost per run:**
- Simple task (5 subtasks): $5-$15
- Medium task (10 subtasks): $15-$40
- Complex task (20+ subtasks): $40-$100+

**Cost optimization tips:**
1. Use `skip_side_tasks: true` when possible
2. Combine related work into fewer tasks in Phase 1
3. Provide clear, detailed instructions to reduce retries
4. Use GPT-4 instead of GPT-5 for less critical operations

---

## Advanced Configuration

### Custom Model Selection

Edit `control_plane_v2/agent_generator/model_clients.py` to change model assignments:

```python
# Default configuration:
# - Boss: GPT-5 (o1-preview)
# - Worker: Claude 4.5 Sonnet
# - Phase 0/1: Claude + GPT-5 collaboration

# To use different models, modify the create_all_model_clients() function
```

### Adjust Retry Limits

**Worker retries** (default: 15):
Edit `control_plane_v2/phase_2/worker_agent_autonomous.py` line 273

**Boss re-delegation** (default: unlimited):
Edit `control_plane_v2/phase_2/boss_agent_autonomous.py` verification logic

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

---

## Getting Help

### Documentation Files

1. **SYSTEM_CORE_FILES.md** - Complete file reference, architecture, dependencies
2. **SYSTEM_HOW_IT_WORKS.md** - Detailed workflow, code examples, execution flow

### Common Questions

**Q: How do I add a new data source?**
A: Add it to the manifest's `user_uploads` array with source and target filename.

**Q: Can I run tasks in parallel?**
A: Yes! Phase 1 automatically identifies parallel tasks. They execute sequentially but are designed for parallelization.

**Q: How do I debug a failed task?**
A: Check `runs/run_YYYYMMDD_HHMMSS/phase2/task_name/` for logs and outputs.

**Q: Can I resume a failed run?**
A: Not currently. The system starts fresh each run. Consider breaking large tasks into smaller manifests.

**Q: How do I customize the output format?**
A: Specify in manifest's `output_requirements` section. The system adapts to your requirements.

---

## Security Notes

1. **Never commit `env_info.json`** - Contains sensitive API keys
2. **Secure your runs directory** - May contain sensitive data
3. **Review generated code** - Worker generates code; review for sensitive operations
4. **API key rotation** - Rotate keys regularly
5. **Network security** - System makes external API calls

---

## License & Attribution

This autonomous agent system uses:
- **AutoGen** (Microsoft) - Agent framework
- **Azure OpenAI** - GPT models
- **Anthropic Claude** - Claude models
- **ChromaDB** - Vector database

---

## Version History

**v1.0 (2025-10-20)**
- Initial release
- 45 core files
- Complete Phase 0, 1, 2 implementation
- Boss-Worker autonomous execution
- Deep validation and quality control
- RAG-based knowledge system

---

## Next Steps

1. ✅ Extract package
2. ✅ Install dependencies
3. ✅ Create `env_info.json`
4. ✅ Run example manifest
5. ✅ Create your own manifest
6. ✅ Review outputs in `runs/` directory

**Ready to start? Run:**
```bash
python -m control_plane_v2.run_control_plane --manifest manifest_5m_simple.json
```

---

**End of Setup Instructions**

