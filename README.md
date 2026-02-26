# Control Plane

Multi-agent orchestration for data analysis and workflows. Uses **GPT-5.1** (Boss) and **Claude Sonnet** (Worker) to classify tasks, split them into steps, and run them with verification and retries.

---

## Features

- **3-phase pipeline**: Classification → Division → Execution
- **Dual agents**: GPT-5.1 for planning and review, Claude Sonnet for execution
- **Azure + Anthropic**: Azure OpenAI (GPT) and Azure Anthropic (Claude); optional AWS Bedrock
- **Manifest-driven**: Describe the task in a JSON manifest; no code changes needed
- **Self-verification**: Worker checks outputs; Boss verifies before accepting
- **File catalog & vector store**: Shared artifacts and context across tasks

---

## Requirements

- **Python** 3.8+
- **Azure OpenAI** (for GPT-5.1) and/or **Azure Anthropic** (for Claude Sonnet)
- Optional: AWS Bedrock (for Claude if not using Azure Anthropic)

---

## Installation

```bash
# Clone (or use existing folder)
git clone https://github.com/Kshitij-01/control_plane.git
cd control_plane

# Virtual environment
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
# source venv/bin/activate

# Dependencies
pip install -r requirements.txt
```

---

## Configuration

1. Copy the example env file and add your keys:

   ```bash
   cp env_info.json.example env_info.json
   ```

2. Edit **`env_info.json`**:

   - **`llm_config.azure`** – Azure OpenAI endpoint, API key, deployment names (e.g. `gpt5_model`, `gpt41_deployment`). Use **`chat_endpoint`** and **`chat_api_key`** if chat models are on a different resource.
   - **`llm_config.anthropic_azure`** – Azure Anthropic (Claude): `endpoint`, `api_key`, `sonnet_deployment` (e.g. `claude-sonnet-4-5`). Used for the Worker when **`use_azure_for_claude`** is true under `azure`.
   - **`llm_config.bedrock`** – Optional; only needed if you want Claude via AWS Bedrock instead of Azure Anthropic.

Do not commit `env_info.json`; it is listed in `.gitignore`.

---

## Quick Start

Put your input file under **`data/raw/`** (or another path you reference in the manifest). Then run:

```bash
python -m control_plane_v2.run_control_plane --manifest manifest_amazon_analysis.json
```

The manifest defines the task, inputs, and outputs. Example (excerpt):

```json
{
  "task_id": "amazon_csv_analysis",
  "skip_side_tasks": true,
  "task_type": "exploratory_data_analysis",
  "description": "Run EDA on the Amazon dataset...",
  "user_uploads": [
    { "source": "data/raw/amazon.csv.zip", "filename": "amazon.csv.zip" }
  ],
  "transformation_config": { "skip_side_tasks": true }
}
```

- **`user_uploads`**: Files to copy into the run (paths relative to project root).
- **`skip_side_tasks`**: Skip connection/validation side tasks when `true`.

---

## Project Structure

```
control plane/
├── control_plane_v2/           # Main package
│   ├── run_control_plane.py    # Entry point
│   ├── phase_0/                # Task classification
│   ├── phase_1/                # Task division (execution plan)
│   ├── phase_2/                # Boss–Worker execution
│   ├── agent_generator/        # Side-task agents
│   ├── workspace_manager.py
│   ├── azure_anthropic_client.py
│   ├── bedrock_client.py
│   └── ...
├── data/
│   └── raw/                    # Put input files here (e.g. amazon.csv.zip)
├── manifest_amazon_analysis.json
├── env_info.json.example
├── requirements.txt
└── README.md
```

After a run, outputs appear under **`runs/run_YYYYMMDD_HHMMSS/`** (phase0, phase1, phase2, logs, file_catalog, etc.).

---

## Architecture (short)

| Phase | Role   | Model        | Purpose                          |
|-------|--------|-------------|----------------------------------|
| 0     | Claude | Sonnet      | Initial task analysis             |
| 0     | GPT-5  | GPT-5.1     | Review and overseer               |
| 1     | Claude + GPT-5 | Both | Divide task into subtasks        |
| 2     | Boss   | GPT-5.1     | Plan subtasks, verify results     |
| 2     | Worker | Claude Sonnet | Run code, self-verify          |

Claude can be Azure Anthropic (recommended) or AWS Bedrock. GPT uses Azure OpenAI; set **`chat_endpoint`** to the resource where your GPT deployments live if it differs from the default `endpoint`.

---

## Supported Tasks

- Exploratory data analysis (CSV, Parquet, archives)
- ETL and file processing
- Database migrations (with DB config in env)
- Custom workflows described in the manifest

---

## Security

- Keep **`env_info.json`** local and never commit it.
- Review `.gitignore`; it already excludes `env_info.json`, `runs/`, and large data files.

---

## Troubleshooting

- **404 DeploymentNotFound**: Your `endpoint` or `chat_endpoint` does not have the deployment name in the config. Point it to the Azure OpenAI resource that hosts that deployment.
- **Claude/Bedrock errors**: Use **Azure Anthropic** (set `llm_config.anthropic_azure` and **`use_azure_for_claude`** in `azure`) to avoid Bedrock.
- Logs: console plus **`runs/run_*/phase2/logs/`** for execution detail.
