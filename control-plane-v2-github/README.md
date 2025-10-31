# Autonomous Agent Control Plane v2

A sophisticated multi-agent system for autonomous data processing, analysis, and workflow execution. The system uses GPT-5 and Claude 4.5 agents to collaboratively understand, plan, and execute complex data tasks.

## 🚀 Features

- **3-Phase Architecture**: Classification → Division → Execution
- **Dual AI Agents**: GPT-5 (Boss) and Claude 4.5 (Worker) with specialized roles
- **Autonomous Execution**: Self-healing, verification, and error recovery
- **Cross-Task Communication**: File catalog and vector store for knowledge sharing
- **Universal Workflows**: Adapts to any data processing task via manifest configuration
- **Robust Verification**: Multi-layer validation and quality assurance

## 📋 Requirements

- Python 3.8+
- Azure OpenAI API access
- AWS Bedrock access (for Claude)
- PostgreSQL or Azure SQL (for database tasks)

## 🛠️ Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd control-plane-v2
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   # Windows
   venv\Scripts\activate
   # Linux/Mac
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment**
   ```bash
   cp env_info.json.example env_info.json
   # Edit env_info.json with your API keys and database credentials
   ```

## 🎯 Quick Start

The system is designed to be **universal** - just provide a manifest file describing your task:

```bash
python -m control_plane_v2.run_control_plane --manifest path/to/your/manifest.json
```

### Example Manifests

**Data Migration (PostgreSQL → Azure SQL)**
```json
{
  "task_id": "data_migration",
  "description": "Migrate customer data from PostgreSQL to Azure SQL",
  "input_data": {
    "source_type": "database",
    "source_connection": "postgres://user:pass@host:5432/db"
  },
  "output_data": {
    "target_type": "database", 
    "target_connection": "azure_sql_connection_string"
  }
}
```

**Data Analysis (File-based)**
```json
{
  "task_id": "brca_analysis",
  "description": "Comprehensive analysis of BRCA TCGA dataset",
  "input_data": {
    "source_type": "compressed_archive",
    "source_path": "brca_tcga.tar.gz"
  }
}
```

## 🏗️ Architecture

### Phase 0: Task Classification
- **Claude Understander**: Analyzes task requirements and constraints
- **GPT-5 Overseer**: Reviews and validates the classification
- **Side Task Solver**: Handles connection validation, credential checks

### Phase 1: Task Division  
- **Collaborative Divider**: GPT-5 and Claude work together to break down complex tasks
- **Subtask Planning**: Creates detailed execution plans with dependencies
- **Resource Allocation**: Determines computational and data requirements

### Phase 2: Autonomous Execution
- **Boss Agent (GPT-5)**: Plans, delegates, and verifies worker outputs
- **Worker Agent (Claude 4.5)**: Executes code, generates outputs, self-verifies
- **File Catalog**: Tracks data artifacts across tasks
- **Vector Store**: Semantic search for task knowledge and context

## 🔧 Configuration

### Environment Setup (`env_info.json`)

```json
{
  "llm_config": {
    "azure": {
      "endpoint": "https://your-endpoint.openai.azure.com/",
      "api_key": "your-azure-openai-key",
      "gpt5_model": "gpt-5"
    },
    "bedrock": {
      "aws_access_key_id": "your-aws-key",
      "aws_secret_access_key": "your-aws-secret",
      "claude_4_5_model_id": "arn:aws:bedrock:..."
    }
  },
  "database_config": {
    "postgres": { "host": "...", "database": "..." },
    "azure_sql": { "server": "...", "database": "..." }
  }
}
```

### Manifest Structure

Key fields for any manifest:
- `task_id`: Unique identifier
- `description`: Human-readable task description  
- `input_data`: Source data specification
- `output_data`: Target data specification
- `transformation_config`: Processing preferences
- `worker_instructions`: Specific guidance for the Worker agent

## 📊 Supported Task Types

- **Database Migrations**: PostgreSQL → Azure SQL, MySQL → PostgreSQL, etc.
- **Data Analysis**: EDA, statistical analysis, machine learning workflows
- **ETL Pipelines**: Extract, transform, load operations
- **File Processing**: CSV, JSON, Parquet, compressed archives
- **API Integrations**: REST APIs, web scraping, data ingestion
- **Custom Workflows**: Any data processing task via manifest configuration

## 🛡️ Error Handling & Recovery

The system includes multiple layers of error handling:

1. **Worker Self-Verification**: Claude validates its own outputs before reporting success
2. **Boss Verification**: GPT-5 independently verifies worker outputs
3. **Automatic Retry**: Failed tasks are retried with different approaches
4. **Graceful Degradation**: System continues with partial results when possible
5. **Comprehensive Logging**: Detailed logs for debugging and monitoring

## 📁 Project Structure

```
control_plane_v2/
├── run_control_plane.py          # Main entry point
├── phase_0/                      # Task classification
│   ├── task_classifier.py
│   └── task_understanders/
├── phase_1/                      # Task division
│   └── collaborative_divider_v2.py
├── phase_2/                      # Autonomous execution
│   ├── boss_agent_autonomous.py
│   ├── worker_agent_autonomous.py
│   └── orchestrator_boss_worker.py
├── agent_generator/              # Agent creation and management
├── shared/                       # Common models and utilities
└── workspace_manager.py          # File and workspace management
```

## 🔍 Monitoring & Debugging

The system provides comprehensive logging at multiple levels:

- **Task-level**: High-level progress and completion status
- **Agent-level**: Individual agent decisions and actions  
- **Code-level**: Detailed execution traces and error information
- **Verification-level**: Step-by-step validation processes

Logs are written to the console and can be redirected to files for analysis.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📄 License

[Add your license information here]

## 🆘 Support

For issues and questions:
1. Check the logs for detailed error information
2. Verify your `env_info.json` configuration
3. Ensure all dependencies are installed
4. Create an issue with full error details and logs

## 🎯 Example Use Cases

- **Healthcare Data Analysis**: Process and analyze large genomic datasets
- **Financial Data Migration**: Migrate legacy databases to cloud platforms  
- **Research Data Processing**: Automate complex data analysis workflows
- **Business Intelligence**: Generate insights from multi-source data
- **Data Pipeline Automation**: End-to-end ETL with minimal human intervention

---

**Note**: This system is designed for production use with proper API key management and security considerations. Always keep your `env_info.json` file secure and never commit it to version control.
