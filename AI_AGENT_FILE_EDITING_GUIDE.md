# 🔧 AI AGENTS: FILE EDITING CAPABILITIES

**Research Date:** November 1, 2025  
**Focus:** How AI agents can edit files directly (HTML reports, code, etc.)

---

## 📊 RESEARCH SUMMARY

Based on web research and analysis of modern AI coding tools (Aider, Cursor, AutoGen), here are the proven approaches for AI agents to edit files.

---

## 🎯 THE CHALLENGE

**Your Question:** Can we give AI agents the option to edit files directly (e.g., edit a specific line in an HTML report)?

**Why This Matters:**
- Generated HTML reports may need minor tweaks
- LLMs can't regenerate entire file for small changes (token limits!)
- Line-specific edits are more efficient
- Users might request: "Change line 45 to use color #3498db"

---

## 🏆 BEST APPROACHES (Ranked)

### **Approach 1: Search & Replace Tool** ⭐⭐⭐⭐⭐ **BEST FOR AI AGENTS**

**How It Works:**
- Agent searches for specific text pattern
- Replaces with new text
- Similar to Cursor's "search_replace" tool

**Why This Is Best:**
- ✅ **Precise** - Finds exact text to replace
- ✅ **Safe** - No line number confusion
- ✅ **Context-aware** - Agent understands what to change
- ✅ **Works with edits** - Doesn't break on file changes
- ✅ **LLM-friendly** - Easy for AI to use

**Implementation:**

```python
from autogen_core.tools import FunctionTool
from typing_extensions import Annotated

def search_replace_in_file(
    file_path: Annotated[str, "Path to file to edit"],
    search_text: Annotated[str, "Exact text to search for"],
    replace_text: Annotated[str, "Text to replace it with"],
    replace_all: Annotated[bool, "Replace all occurrences"] = False
) -> str:
    """
    Search and replace text in a file
    
    Args:
        file_path: Path to file to edit
        search_text: Exact text to find (must match exactly, including whitespace)
        replace_text: Text to replace with
        replace_all: If True, replace all occurrences. If False, replace only first.
    
    Returns:
        JSON string with success status, number of replacements, and message
    """
    try:
        from pathlib import Path
        import json
        
        file = Path(file_path)
        if not file.exists():
            return json.dumps({
                "success": False,
                "message": f"File not found: {file_path}",
                "replacements": 0
            })
        
        # Read file content
        content = file.read_text(encoding='utf-8')
        
        # Check if search text exists
        if search_text not in content:
            return json.dumps({
                "success": False,
                "message": f"Search text not found in file",
                "replacements": 0,
                "hint": "Make sure to copy the exact text including whitespace and indentation"
            })
        
        # Count occurrences
        count = content.count(search_text)
        
        # Perform replacement
        if replace_all:
            new_content = content.replace(search_text, replace_text)
            replacements = count
        else:
            # Replace only first occurrence
            new_content = content.replace(search_text, replace_text, 1)
            replacements = 1
        
        # Write back to file
        file.write_text(new_content, encoding='utf-8')
        
        return json.dumps({
            "success": True,
            "message": f"Successfully replaced {replacements} occurrence(s)",
            "replacements": replacements,
            "total_occurrences": count
        })
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "message": f"Error: {str(e)}",
            "replacements": 0
        })


# Create FunctionTool for AutoGen
search_replace_tool = FunctionTool(
    search_replace_in_file,
    description="Search for exact text in a file and replace it with new text"
)
```

**Usage by AI Agent:**

```python
# Agent wants to change color in HTML report

# Bad approach (line numbers):
# "Change line 45 from #2c3e50 to #3498db"  ❌ Error-prone!

# Good approach (search & replace):
result = search_replace_in_file(
    file_path="outputs/report.html",
    search_text='--primary-color: #2c3e50;',
    replace_text='--primary-color: #3498db;',
    replace_all=False
)

# Agent gets: {"success": true, "replacements": 1}
```

---

### **Approach 2: Append to File Tool** ⭐⭐⭐⭐ **GOOD FOR ADDING CONTENT**

**How It Works:**
- Agent can append content to end of file
- Useful for adding new sections to reports

**Implementation:**

```python
def append_to_file(
    file_path: Annotated[str, "Path to file"],
    content: Annotated[str, "Content to append"],
    add_newline: Annotated[bool, "Add newline before content"] = True
) -> str:
    """
    Append content to the end of a file
    
    Args:
        file_path: Path to file
        content: Content to append
        add_newline: Add newline before content
    
    Returns:
        JSON string with success status and message
    """
    try:
        from pathlib import Path
        import json
        
        file = Path(file_path)
        
        # Read existing content
        if file.exists():
            existing = file.read_text(encoding='utf-8')
        else:
            existing = ""
        
        # Append new content
        if add_newline and existing and not existing.endswith('\n'):
            existing += '\n'
        
        new_content = existing + content
        
        # Write back
        file.write_text(new_content, encoding='utf-8')
        
        return json.dumps({
            "success": True,
            "message": f"Appended {len(content)} characters to {file_path}"
        })
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "message": f"Error: {str(e)}"
        })
```

---

### **Approach 3: Insert at Marker Tool** ⭐⭐⭐⭐ **GOOD FOR STRUCTURED EDITS**

**How It Works:**
- Agent inserts content before/after a marker comment
- Useful for adding sections to HTML reports

**Implementation:**

```python
def insert_at_marker(
    file_path: Annotated[str, "Path to file"],
    marker: Annotated[str, "Marker text to find"],
    content: Annotated[str, "Content to insert"],
    position: Annotated[str, "'before' or 'after' marker"] = "after"
) -> str:
    """
    Insert content before or after a marker in a file
    
    Args:
        file_path: Path to file
        marker: Marker text to find (e.g., "<!-- INSERT_CHARTS_HERE -->")
        content: Content to insert
        position: 'before' or 'after' the marker
    
    Returns:
        JSON string with success status
    """
    try:
        from pathlib import Path
        import json
        
        file = Path(file_path)
        if not file.exists():
            return json.dumps({"success": False, "message": "File not found"})
        
        content_text = file.read_text(encoding='utf-8')
        
        if marker not in content_text:
            return json.dumps({
                "success": False,
                "message": f"Marker '{marker}' not found in file"
            })
        
        # Insert content
        if position == "before":
            new_content = content_text.replace(marker, f"{content}\n{marker}")
        else:  # after
            new_content = content_text.replace(marker, f"{marker}\n{content}")
        
        file.write_text(new_content, encoding='utf-8')
        
        return json.dumps({
            "success": True,
            "message": f"Inserted content {position} marker '{marker}'"
        })
        
    except Exception as e:
        return json.dumps({"success": False, "message": str(e)})
```

**Usage in HTML Template:**

```html
<section id="charts">
    <h2>Cost Visualizations</h2>
    <!-- INSERT_CHARTS_HERE -->
</section>

<section id="insights">
    <h2>Key Insights</h2>
    <!-- INSERT_INSIGHTS_HERE -->
</section>
```

**Agent Usage:**

```python
# Agent adds chart
insert_at_marker(
    file_path="report.html",
    marker="<!-- INSERT_CHARTS_HERE -->",
    content='<svg>...</svg>',
    position="after"
)
```

---

### **Approach 4: Line-Based Editing** ⭐⭐ **AVOID FOR AI AGENTS**

**How It Works:**
- Edit specific line numbers
- Used by some tools

**Why This Is BAD for AI:**
- ❌ **Fragile** - Line numbers change with edits
- ❌ **Error-prone** - Agent may have outdated line numbers
- ❌ **Confusing** - Agent doesn't see file like humans do
- ❌ **Breaks easily** - File modifications invalidate line numbers

**Example (Don't Do This):**

```python
# ❌ BAD: Line-based editing
def edit_line(file_path, line_number, new_content):
    lines = open(file_path).readlines()
    lines[line_number] = new_content + '\n'
    open(file_path, 'w').writelines(lines)

# Problems:
# - What if file changed since agent saw it?
# - What if agent counted lines wrong?
# - What if there are multiple similar lines?
```

---

### **Approach 5: Full File Replacement** ⭐⭐⭐ **OK FOR SMALL FILES**

**How It Works:**
- Agent generates entire new file content
- Replaces whole file

**When To Use:**
- ✅ Small files (< 1000 tokens)
- ✅ Complete regeneration needed
- ✅ File is template-based

**When NOT to Use:**
- ❌ Large files (HTML reports > 4K tokens)
- ❌ Minor edits (search & replace better)
- ❌ Partial updates

**Implementation:**

```python
def write_file(
    file_path: Annotated[str, "Path to file"],
    content: Annotated[str, "Complete file content"],
    create_backup: Annotated[bool, "Create backup of existing file"] = True
) -> str:
    """
    Write complete content to file (replaces existing)
    
    Args:
        file_path: Path to file
        content: Complete new file content
        create_backup: Create .bak backup of existing file
    
    Returns:
        JSON string with success status
    """
    try:
        from pathlib import Path
        import json
        import shutil
        
        file = Path(file_path)
        
        # Create backup if file exists
        if file.exists() and create_backup:
            backup_path = file.with_suffix(file.suffix + '.bak')
            shutil.copy2(file, backup_path)
        
        # Write new content
        file.write_text(content, encoding='utf-8')
        
        return json.dumps({
            "success": True,
            "message": f"Wrote {len(content)} characters to {file_path}",
            "backup_created": file.exists() and create_backup
        })
        
    except Exception as e:
        return json.dumps({"success": False, "message": str(e)})
```

---

## 🛠️ RECOMMENDED TOOLKIT FOR YOUR WORKER AGENT

### **File Editing Tools Suite:**

```python
# control_plane_v2/tools/file_editing_tools.py

from autogen_core.tools import FunctionTool
from typing_extensions import Annotated
from pathlib import Path
import json

class FileEditingTools:
    """Complete file editing toolkit for AI agents"""
    
    @staticmethod
    def search_replace_in_file(
        file_path: Annotated[str, "Path to file to edit"],
        search_text: Annotated[str, "Exact text to search for (including whitespace)"],
        replace_text: Annotated[str, "Text to replace with"],
        replace_all: Annotated[bool, "Replace all occurrences (default: False)"] = False
    ) -> str:
        """Search and replace text in a file"""
        # Implementation from above...
        pass
    
    @staticmethod
    def insert_at_marker(
        file_path: Annotated[str, "Path to file"],
        marker: Annotated[str, "Marker comment (e.g., '<!-- INSERT_HERE -->')"],
        content: Annotated[str, "Content to insert"],
        position: Annotated[str, "'before' or 'after' marker"] = "after"
    ) -> str:
        """Insert content before/after a marker"""
        # Implementation from above...
        pass
    
    @staticmethod
    def append_to_file(
        file_path: Annotated[str, "Path to file"],
        content: Annotated[str, "Content to append"],
        add_newline: Annotated[bool, "Add newline before content"] = True
    ) -> str:
        """Append content to end of file"""
        # Implementation from above...
        pass
    
    @staticmethod
    def read_file_section(
        file_path: Annotated[str, "Path to file"],
        search_pattern: Annotated[str, "Pattern to find section"],
        lines_before: Annotated[int, "Lines to include before match"] = 5,
        lines_after: Annotated[int, "Lines to include after match"] = 5
    ) -> str:
        """Read a section of file around a search pattern"""
        try:
            file = Path(file_path)
            lines = file.read_text(encoding='utf-8').splitlines()
            
            # Find matching line
            match_idx = None
            for i, line in enumerate(lines):
                if search_pattern in line:
                    match_idx = i
                    break
            
            if match_idx is None:
                return json.dumps({
                    "success": False,
                    "message": "Pattern not found"
                })
            
            # Extract section
            start = max(0, match_idx - lines_before)
            end = min(len(lines), match_idx + lines_after + 1)
            section = lines[start:end]
            
            return json.dumps({
                "success": True,
                "content": '\n'.join(section),
                "line_number": match_idx + 1,
                "total_lines": len(lines)
            })
            
        except Exception as e:
            return json.dumps({"success": False, "message": str(e)})
    
    @classmethod
    def get_tools(cls):
        """Get all file editing tools as FunctionTool list"""
        return [
            FunctionTool(
                cls.search_replace_in_file,
                description="Search for exact text in file and replace it"
            ),
            FunctionTool(
                cls.insert_at_marker,
                description="Insert content before/after a marker comment"
            ),
            FunctionTool(
                cls.append_to_file,
                description="Append content to end of file"
            ),
            FunctionTool(
                cls.read_file_section,
                description="Read a section of file around a search pattern"
            )
        ]
```

---

## 🎯 INTEGRATION WITH WORKER AGENT

### **Add File Editing to Worker:**

```python
# control_plane_v2/phase_2/worker_agent_autonomous.py

from control_plane_v2.tools.file_editing_tools import FileEditingTools

class WorkerAgent(RoutedAgent):
    def __init__(self, ...):
        # Existing tools
        self.todo_tool = FunctionTool(todo_write_function, ...)
        
        # NEW: Add file editing tools
        self.file_editing_tools = FileEditingTools.get_tools()
        
        # Combine all tools
        self.all_tools = [
            self.todo_tool,
            *self.file_editing_tools
        ]
    
    async def handle_subtask(self, message, ctx):
        # Worker now has access to file editing!
        response = await self.model_client.create(
            messages=conversation_history,
            tools=self.all_tools  # Includes file editing
        )
```

---

## 💡 USAGE EXAMPLES

### **Example 1: Fix Color in HTML Report**

**User Request:** "Change the primary color in report.html from #2c3e50 to #3498db"

**Agent Response:**

```python
# Agent calls search_replace_in_file
result = search_replace_in_file(
    file_path="outputs/reports/drilling_report_2025-11-01.html",
    search_text="--primary-color: #2c3e50;",
    replace_text="--primary-color: #3498db;",
    replace_all=True
)

# Result: {"success": true, "replacements": 1}
```

**Agent Message:**
> "✅ I've updated the primary color to #3498db. The change was applied successfully."

---

### **Example 2: Add Missing Chart to Report**

**User Request:** "Add the cost trend chart to section #charts in the report"

**Agent Response:**

```python
# Agent generates SVG chart
chart_svg = await llm.generate_svg_chart(cost_data)

# Agent inserts chart using marker
result = insert_at_marker(
    file_path="outputs/report.html",
    marker="<!-- INSERT_CHARTS_HERE -->",
    content=chart_svg,
    position="after"
)
```

**Agent Message:**
> "✅ I've added the cost trend chart to the Charts section of the report."

---

### **Example 3: Update Activity Description**

**User Request:** "The activity at hour 15 should say 'Drilling' instead of 'Circulating'"

**Agent Response:**

```python
# First, read the section to find exact text
section = read_file_section(
    file_path="outputs/report.html",
    search_pattern="<tr>.*15.*Circulating",
    lines_before=2,
    lines_after=2
)

# Then search & replace
result = search_replace_in_file(
    file_path="outputs/report.html",
    search_text="<td>15</td><td>Circulating</td>",
    replace_text="<td>15</td><td>Drilling</td>",
    replace_all=False
)
```

**Agent Message:**
> "✅ I've updated hour 15's activity from 'Circulating' to 'Drilling'."

---

## 🚨 IMPORTANT CONSIDERATIONS

### **1. Validation & Safety**

```python
def search_replace_in_file(...):
    # ✅ Always validate inputs
    if not search_text or not replace_text:
        return {"success": False, "message": "Empty search/replace text"}
    
    # ✅ Check file exists before editing
    if not Path(file_path).exists():
        return {"success": False, "message": "File not found"}
    
    # ✅ Create backup before major edits
    if create_backup:
        shutil.copy2(file, file.with_suffix('.bak'))
    
    # ✅ Verify search text exists
    if search_text not in content:
        return {"success": False, "message": "Search text not found"}
```

---

### **2. Error Handling**

```python
# Always return structured JSON responses
{
    "success": bool,
    "message": str,
    "replacements": int,  # optional
    "details": dict  # optional
}

# Agent can check success and act accordingly
if result["success"]:
    report_success()
else:
    retry_with_different_approach()
```

---

### **3. Provide Context to Agent**

**Good Prompt:**
```
You have access to file editing tools:

1. search_replace_in_file - Replace exact text in a file
   - Use this for precise edits (colors, values, words)
   - Must provide EXACT text including whitespace
   - Can replace all or just first occurrence

2. insert_at_marker - Insert content at marker comments
   - Use for adding new sections to HTML reports
   - Markers look like: <!-- INSERT_HERE -->

3. append_to_file - Add content to end of file
   - Use for adding new sections at end

4. read_file_section - Read part of file around pattern
   - Use to verify exact text before editing

Always:
- Read the section first to get exact text
- Use search & replace (not line numbers!)
- Verify the edit succeeded
```

---

## 📊 COMPARISON: EDITING APPROACHES

| Approach | Precision | Safety | LLM-Friendly | Use Case |
|----------|-----------|--------|--------------|----------|
| **Search & Replace** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **Precise edits** |
| **Insert at Marker** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | **Adding sections** |
| **Append** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **Add to end** |
| **Line Numbers** | ⭐⭐ | ⭐⭐ | ⭐ | **Avoid!** |
| **Full Replacement** | ⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | **Small files only** |

---

## ✅ RECOMMENDED IMPLEMENTATION

### **For Your Halliburton Project:**

```python
# 1. Create file editing tools
file_tools = FileEditingTools.get_tools()

# 2. Add to Worker agent
class WorkerAgent:
    def __init__(self):
        self.tools = [
            todo_tool,
            *file_tools,  # File editing capability!
            *pdf_tools
        ]

# 3. Worker can now:
# - Generate HTML report
# - Edit specific parts if needed
# - Fix colors, add sections, update data
# - All without regenerating entire file!
```

**Benefits:**
- ✅ Efficient (no need to regenerate 10K token HTML)
- ✅ Precise (edit specific elements)
- ✅ Fast (search & replace is instant)
- ✅ Safe (backups, validation)
- ✅ LLM-friendly (easy for agent to use)

---

## 🚀 NEXT STEPS

**Would you like me to:**

1. **Implement file editing tools** - Create `file_editing_tools.py`?
2. **Integrate with Worker** - Add tools to Worker agent?
3. **Create usage examples** - Show how agent edits HTML reports?
4. **Add to current system** - Enable file editing for your Halliburton reports?

**File editing will make your agents much more powerful!** 🔥

