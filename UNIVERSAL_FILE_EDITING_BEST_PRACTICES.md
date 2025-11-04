# 🔧 UNIVERSAL FILE EDITING FOR AI AGENTS (ALL FILE TYPES)

**Focus:** Best practices for AI agents to edit ANY type of file reliably  
**Based on:** Aider, Cursor, AutoGen, LangChain, and production AI systems

---

## 🎯 THE CHALLENGE

**Your Requirement:** AI agents need to edit ANY file type (Python, JSON, HTML, CSV, Markdown, YAML, etc.)

**Key Requirements:**
- ✅ Works for ALL file types (code, data, config, documentation)
- ✅ Reliable (doesn't break files)
- ✅ Precise (edits exactly what was intended)
- ✅ LLM-friendly (easy for AI to use)
- ✅ Handles edge cases (indentation, encoding, line endings)

---

## 🏆 BATTLE-TESTED APPROACHES (From Production AI Tools)

### **🥇 Approach 1: SEARCH & REPLACE with Context Matching** ⭐⭐⭐⭐⭐

**Used By:** Cursor IDE, most production AI coding tools

**How It Works:**
1. Agent provides **EXACT old text** to find (including context)
2. Agent provides **new text** to replace with
3. Tool finds exact match and replaces it
4. If multiple matches, tool requires more context

**Why This Is Best:**
- ✅ **Universal** - Works for ANY file type
- ✅ **Safe** - Won't replace wrong text
- ✅ **Precise** - Exact string matching
- ✅ **Context-aware** - Agent includes surrounding lines
- ✅ **LLM-friendly** - Simple for AI to understand
- ✅ **No line numbers** - Immune to file changes

**Implementation:**

```python
from pathlib import Path
from typing_extensions import Annotated
import json

def search_replace_file(
    file_path: Annotated[str, "Path to file (any type: .py, .json, .html, .md, etc.)"],
    old_string: Annotated[str, "EXACT text to find (must match exactly including whitespace, indentation, and newlines)"],
    new_string: Annotated[str, "New text to replace with"],
    replace_all: Annotated[bool, "Replace all occurrences (True) or just first (False)"] = False
) -> str:
    """
    Search and replace text in ANY file type
    
    CRITICAL: old_string must match EXACTLY including:
    - Whitespace (spaces, tabs)
    - Indentation
    - Line breaks
    - Special characters
    
    Best Practice: Include 2-3 lines of context before/after the change
    
    Returns:
        JSON with success status, match count, and details
    """
    try:
        file = Path(file_path)
        
        # Validate file exists
        if not file.exists():
            return json.dumps({
                "success": False,
                "error": f"File not found: {file_path}",
                "matches": 0
            })
        
        # Read file content (handle encoding)
        try:
            content = file.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            # Try common encodings
            for encoding in ['utf-8-sig', 'latin-1', 'cp1252']:
                try:
                    content = file.read_text(encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return json.dumps({
                    "success": False,
                    "error": "Could not decode file with common encodings",
                    "matches": 0
                })
        
        # Check if old_string exists
        if old_string not in content:
            return json.dumps({
                "success": False,
                "error": "Search text not found in file",
                "matches": 0,
                "hint": "Make sure to include exact text with correct indentation and whitespace",
                "file_preview": content[:500] + "..." if len(content) > 500 else content
            })
        
        # Count matches
        match_count = content.count(old_string)
        
        # Check for ambiguity
        if match_count > 1 and not replace_all:
            return json.dumps({
                "success": False,
                "error": f"Found {match_count} matches but replace_all=False",
                "matches": match_count,
                "hint": "Either set replace_all=True or provide more context to make old_string unique"
            })
        
        # Perform replacement
        if replace_all:
            new_content = content.replace(old_string, new_string)
            replacements = match_count
        else:
            new_content = content.replace(old_string, new_string, 1)
            replacements = 1
        
        # Write back (preserve original encoding if possible)
        file.write_text(new_content, encoding='utf-8')
        
        return json.dumps({
            "success": True,
            "message": f"Successfully replaced {replacements} occurrence(s)",
            "replacements": replacements,
            "total_matches": match_count,
            "file_type": file.suffix,
            "file_size_before": len(content),
            "file_size_after": len(new_content)
        })
        
    except Exception as e:
        return json.dumps({
            "success": False,
            "error": f"Unexpected error: {str(e)}",
            "matches": 0
        })
```

**Usage Examples (All File Types):**

```python
# Python file (.py)
search_replace_file(
    file_path="app.py",
    old_string="""def calculate_total(items):
    return sum(item.price for item in items)""",
    new_string="""def calculate_total(items):
    # Added tax calculation
    subtotal = sum(item.price for item in items)
    tax = subtotal * 0.08
    return subtotal + tax"""
)

# JSON file (.json)
search_replace_file(
    file_path="config.json",
    old_string='"max_retries": 3',
    new_string='"max_retries": 5'
)

# HTML file (.html)
search_replace_file(
    file_path="index.html",
    old_string='<h1>Welcome</h1>',
    new_string='<h1>Welcome to Our Site</h1>'
)

# YAML file (.yaml)
search_replace_file(
    file_path="docker-compose.yml",
    old_string="""services:
  web:
    image: nginx:1.20""",
    new_string="""services:
  web:
    image: nginx:1.21"""
)

# Markdown file (.md)
search_replace_file(
    file_path="README.md",
    old_string="## Installation",
    new_string="## Installation\n\nRequires Python 3.11+\n"
)

# CSV file (.csv)
search_replace_file(
    file_path="data.csv",
    old_string="John,Doe,30",
    new_string="John,Doe,31"
)
```

---

### **🥈 Approach 2: UNIFIED DIFF (Git-Style Patches)** ⭐⭐⭐⭐

**Used By:** Aider, GitHub Copilot, professional tools

**How It Works:**
1. Agent generates a unified diff (like `git diff`)
2. Tool applies the patch to the file
3. Uses `difflib` or `git apply`

**Benefits:**
- ✅ Shows exactly what changed
- ✅ Professional format (developers understand it)
- ✅ Can handle multiple changes in one patch
- ✅ Works with version control

**Challenges:**
- ⚠️ More complex for LLM to generate correctly
- ⚠️ Requires line numbers (can be fragile)
- ⚠️ Harder to debug when fails

**Implementation:**

```python
import difflib
from pathlib import Path
from typing_extensions import Annotated
import json

def apply_unified_diff(
    file_path: Annotated[str, "Path to file to patch"],
    diff_text: Annotated[str, "Unified diff format patch"]
) -> str:
    """
    Apply a unified diff patch to a file
    
    Unified diff format example:
    ```
    --- a/file.py
    +++ b/file.py
    @@ -10,3 +10,4 @@
     def hello():
    -    print("Hello")
    +    print("Hello, World!")
    +    return True
    ```
    
    Returns:
        JSON with success status and details
    """
    try:
        from patch import fromstring
        
        file = Path(file_path)
        if not file.exists():
            return json.dumps({"success": False, "error": "File not found"})
        
        # Read original content
        original_lines = file.read_text(encoding='utf-8').splitlines(keepends=True)
        
        # Parse and apply patch
        patchset = fromstring(diff_text.encode('utf-8'))
        
        if not patchset:
            return json.dumps({"success": False, "error": "Invalid patch format"})
        
        # Apply patch
        success = patchset.apply()
        
        if not success:
            return json.dumps({
                "success": False,
                "error": "Patch failed to apply",
                "hint": "File may have changed since diff was generated"
            })
        
        # Write patched content
        patched_content = patchset.get_file_content()
        file.write_bytes(patched_content)
        
        return json.dumps({
            "success": True,
            "message": "Patch applied successfully",
            "changes": len(patchset.hunks)
        })
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})


def generate_diff_suggestion(
    file_path: Annotated[str, "Path to file"],
    old_content: Annotated[str, "Original content section"],
    new_content: Annotated[str, "New content section"]
) -> str:
    """
    Generate a unified diff for review
    
    Useful for showing changes before applying
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    
    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
        lineterm=''
    )
    
    return '\n'.join(diff)
```

---

### **🥉 Approach 3: EDIT BLOCKS (Structured Edits)** ⭐⭐⭐⭐

**Used By:** Some AI coding assistants

**How It Works:**
1. Agent specifies file, start marker, end marker
2. Agent provides new content
3. Tool replaces everything between markers

**Benefits:**
- ✅ Good for replacing entire functions/sections
- ✅ Clear intent
- ✅ Works well for structured files (code)

**Implementation:**

```python
def replace_between_markers(
    file_path: Annotated[str, "Path to file"],
    start_marker: Annotated[str, "Text marking start of section"],
    end_marker: Annotated[str, "Text marking end of section"],
    new_content: Annotated[str, "New content to insert between markers"],
    include_markers: Annotated[bool, "Keep markers in result"] = True
) -> str:
    """
    Replace content between two markers
    
    Example:
        File contains:
        # START: user_authentication
        def login(user):
            pass
        # END: user_authentication
        
        Replace between "# START:" and "# END:" markers
    """
    try:
        file = Path(file_path)
        content = file.read_text(encoding='utf-8')
        
        # Find markers
        start_idx = content.find(start_marker)
        end_idx = content.find(end_marker)
        
        if start_idx == -1:
            return json.dumps({"success": False, "error": "Start marker not found"})
        if end_idx == -1:
            return json.dumps({"success": False, "error": "End marker not found"})
        if end_idx <= start_idx:
            return json.dumps({"success": False, "error": "End marker before start marker"})
        
        # Calculate replacement positions
        if include_markers:
            # Keep markers, replace content between them
            replace_start = start_idx + len(start_marker)
            replace_end = end_idx
        else:
            # Replace markers too
            replace_start = start_idx
            replace_end = end_idx + len(end_marker)
        
        # Build new content
        new_file_content = (
            content[:replace_start] +
            ('\n' if include_markers else '') +
            new_content +
            ('\n' if include_markers else '') +
            content[replace_end:]
        )
        
        # Write back
        file.write_text(new_file_content, encoding='utf-8')
        
        return json.dumps({
            "success": True,
            "message": "Content replaced between markers",
            "old_length": replace_end - replace_start,
            "new_length": len(new_content)
        })
        
    except Exception as e:
        return json.dumps({"success": False, "error": str(e)})
```

---

## 🛠️ COMPLETE FILE EDITING TOOLKIT (UNIVERSAL)

### **Recommended Suite for Production:**

```python
# control_plane_v2/tools/universal_file_editor.py

from pathlib import Path
from typing_extensions import Annotated
import json
import shutil
from datetime import datetime

class UniversalFileEditor:
    """
    Complete file editing toolkit for AI agents
    Works with ALL file types: .py, .json, .html, .md, .yaml, .csv, .txt, etc.
    """
    
    @staticmethod
    def search_replace(
        file_path: Annotated[str, "Path to any file"],
        old_string: Annotated[str, "Exact text to find (with context)"],
        new_string: Annotated[str, "Replacement text"],
        replace_all: Annotated[bool, "Replace all occurrences"] = False
    ) -> str:
        """
        🥇 PRIMARY METHOD: Search and replace in any file type
        Most reliable and universal approach
        """
        # Implementation from above
        pass
    
    @staticmethod
    def insert_after(
        file_path: Annotated[str, "Path to file"],
        search_text: Annotated[str, "Text after which to insert"],
        new_content: Annotated[str, "Content to insert"],
        occurrence: Annotated[int, "Which occurrence (1-based)"] = 1
    ) -> str:
        """
        Insert content after a specific line/text
        Useful for adding new code/sections
        """
        try:
            file = Path(file_path)
            content = file.read_text(encoding='utf-8')
            
            # Find nth occurrence
            idx = -1
            for _ in range(occurrence):
                idx = content.find(search_text, idx + 1)
                if idx == -1:
                    return json.dumps({
                        "success": False,
                        "error": f"Occurrence {occurrence} of search_text not found"
                    })
            
            # Insert after the search_text
            insert_pos = idx + len(search_text)
            new_content_full = (
                content[:insert_pos] +
                '\n' + new_content +
                content[insert_pos:]
            )
            
            file.write_text(new_content_full, encoding='utf-8')
            
            return json.dumps({
                "success": True,
                "message": f"Inserted content after occurrence {occurrence}"
            })
            
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
    
    @staticmethod
    def insert_before(
        file_path: Annotated[str, "Path to file"],
        search_text: Annotated[str, "Text before which to insert"],
        new_content: Annotated[str, "Content to insert"],
        occurrence: Annotated[int, "Which occurrence (1-based)"] = 1
    ) -> str:
        """Insert content before a specific line/text"""
        try:
            file = Path(file_path)
            content = file.read_text(encoding='utf-8')
            
            # Find nth occurrence
            idx = -1
            for _ in range(occurrence):
                idx = content.find(search_text, idx + 1)
                if idx == -1:
                    return json.dumps({
                        "success": False,
                        "error": f"Occurrence {occurrence} not found"
                    })
            
            # Insert before
            new_content_full = (
                content[:idx] +
                new_content + '\n' +
                content[idx:]
            )
            
            file.write_text(new_content_full, encoding='utf-8')
            
            return json.dumps({"success": True})
            
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
    
    @staticmethod
    def delete_section(
        file_path: Annotated[str, "Path to file"],
        start_text: Annotated[str, "Start of section to delete (inclusive)"],
        end_text: Annotated[str, "End of section to delete (inclusive)"]
    ) -> str:
        """
        Delete a section of file between start and end markers
        """
        try:
            file = Path(file_path)
            content = file.read_text(encoding='utf-8')
            
            start_idx = content.find(start_text)
            if start_idx == -1:
                return json.dumps({"success": False, "error": "Start text not found"})
            
            end_idx = content.find(end_text, start_idx)
            if end_idx == -1:
                return json.dumps({"success": False, "error": "End text not found"})
            
            # Delete section (including markers)
            new_content = (
                content[:start_idx] +
                content[end_idx + len(end_text):]
            )
            
            file.write_text(new_content, encoding='utf-8')
            
            return json.dumps({
                "success": True,
                "message": "Section deleted",
                "deleted_chars": (end_idx + len(end_text)) - start_idx
            })
            
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
    
    @staticmethod
    def read_section(
        file_path: Annotated[str, "Path to file"],
        search_text: Annotated[str, "Text to find"],
        lines_before: Annotated[int, "Lines before match"] = 5,
        lines_after: Annotated[int, "Lines after match"] = 5
    ) -> str:
        """
        Read a section around search_text for context
        Useful before editing to see exact formatting
        """
        try:
            file = Path(file_path)
            content = file.read_text(encoding='utf-8')
            lines = content.splitlines()
            
            # Find line with search_text
            match_line_idx = None
            for i, line in enumerate(lines):
                if search_text in line:
                    match_line_idx = i
                    break
            
            if match_line_idx is None:
                return json.dumps({
                    "success": False,
                    "error": "Search text not found"
                })
            
            # Extract section
            start = max(0, match_line_idx - lines_before)
            end = min(len(lines), match_line_idx + lines_after + 1)
            section_lines = lines[start:end]
            
            return json.dumps({
                "success": True,
                "content": '\n'.join(section_lines),
                "match_line": match_line_idx + 1,
                "section_start_line": start + 1,
                "section_end_line": end,
                "total_lines": len(lines)
            })
            
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
    
    @staticmethod
    def create_backup(
        file_path: Annotated[str, "Path to file to backup"]
    ) -> str:
        """
        Create a timestamped backup of file
        """
        try:
            file = Path(file_path)
            if not file.exists():
                return json.dumps({"success": False, "error": "File not found"})
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = file.with_name(f"{file.stem}_{timestamp}{file.suffix}.bak")
            
            shutil.copy2(file, backup_path)
            
            return json.dumps({
                "success": True,
                "backup_path": str(backup_path),
                "message": f"Backup created: {backup_path.name}"
            })
            
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
    
    @staticmethod
    def get_file_info(
        file_path: Annotated[str, "Path to file"]
    ) -> str:
        """
        Get file metadata (type, size, line count, encoding)
        """
        try:
            file = Path(file_path)
            if not file.exists():
                return json.dumps({"success": False, "error": "File not found"})
            
            content = file.read_text(encoding='utf-8')
            lines = content.splitlines()
            
            return json.dumps({
                "success": True,
                "file_path": str(file),
                "file_type": file.suffix,
                "file_size_bytes": file.stat().st_size,
                "line_count": len(lines),
                "char_count": len(content),
                "encoding": "utf-8"
            })
            
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})
    
    @classmethod
    def get_all_tools(cls):
        """Get all tools as FunctionTool list for AutoGen"""
        from autogen_core.tools import FunctionTool
        
        return [
            FunctionTool(cls.search_replace, description="Search and replace in any file"),
            FunctionTool(cls.insert_after, description="Insert content after text"),
            FunctionTool(cls.insert_before, description="Insert content before text"),
            FunctionTool(cls.delete_section, description="Delete section between markers"),
            FunctionTool(cls.read_section, description="Read section around search text"),
            FunctionTool(cls.create_backup, description="Create timestamped backup"),
            FunctionTool(cls.get_file_info, description="Get file metadata")
        ]
```

---

## 🎯 BEST PRACTICES FOR AI AGENTS

### **1. Always Include Context**

**❌ BAD (Ambiguous):**
```python
search_replace(
    file_path="app.py",
    old_string="return sum",
    new_string="return total"
)
# Problem: "return sum" might appear 10 times!
```

**✅ GOOD (Unique with Context):**
```python
search_replace(
    file_path="app.py",
    old_string="""def calculate_total(items):
    return sum(item.price for item in items)""",
    new_string="""def calculate_total(items):
    total = sum(item.price for item in items)
    return total"""
)
# Clear: Unique function with full context
```

---

### **2. Read Before Writing**

**Best Practice:**
```python
# Step 1: Read section to see exact formatting
section = read_section(
    file_path="config.json",
    search_text='"database"',
    lines_before=2,
    lines_after=2
)

# Step 2: Use exact formatting from section for replacement
search_replace(
    file_path="config.json",
    old_string='  "host": "localhost",',
    new_string='  "host": "production.db.com",'
)
```

---

### **3. Handle Edge Cases**

```python
def search_replace_robust(...):
    """Robust version with edge case handling"""
    
    # 1. Handle encoding issues
    for encoding in ['utf-8', 'utf-8-sig', 'latin-1']:
        try:
            content = file.read_text(encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    
    # 2. Handle line ending differences (Windows vs Unix)
    # Normalize before searching
    old_string_normalized = old_string.replace('\r\n', '\n')
    content_normalized = content.replace('\r\n', '\n')
    
    # 3. Handle indentation (tabs vs spaces)
    # Option: Normalize or preserve as-is
    
    # 4. Handle trailing whitespace
    # Be explicit about whether to preserve it
```

---

### **4. Provide Helpful Feedback**

```python
if search_text not in content:
    return {
        "success": False,
        "error": "Search text not found",
        "hint": "Check indentation and whitespace",
        "file_preview": content[:200],  # Show file start
        "suggestion": "Use read_section to see exact formatting"
    }
```

---

## 📊 COMPARISON: ALL APPROACHES

| Approach | Universal | Reliability | LLM-Friendly | Use Case |
|----------|-----------|-------------|--------------|----------|
| **Search & Replace** | ✅ YES | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | **PRIMARY METHOD** |
| **Insert After/Before** | ✅ YES | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Adding content |
| **Delete Section** | ✅ YES | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Removing code blocks |
| **Unified Diff** | ✅ YES | ⭐⭐⭐ | ⭐⭐⭐ | Professional tools |
| **Edit Blocks** | ⚠️ Structured files | ⭐⭐⭐⭐ | ⭐⭐⭐ | Function replacement |
| **Line Numbers** | ⚠️ Limited | ⭐⭐ | ⭐ | **AVOID** |

---

## ✅ RECOMMENDED TOOLKIT

**For Your Control Plane System:**

```python
# Minimal but complete toolkit

1. search_replace()        # PRIMARY - 90% of edits
2. insert_after()          # Adding new sections
3. read_section()          # Preview before editing
4. create_backup()         # Safety
5. get_file_info()         # File metadata
```

**This covers ALL file editing needs for ANY file type!**

---

## 🚀 INTEGRATION EXAMPLE

```python
# Worker agent with universal file editing

from control_plane_v2.tools.universal_file_editor import UniversalFileEditor

class WorkerAgent(RoutedAgent):
    def __init__(self, ...):
        # Add universal file editing
        self.file_tools = UniversalFileEditor.get_all_tools()
        
        self.all_tools = [
            self.todo_tool,
            *self.file_tools,  # Can edit ANY file!
            *self.pdf_tools
        ]

# Now Worker can edit:
# - Python files (.py)
# - Config files (.json, .yaml, .toml)
# - HTML reports (.html)
# - Documentation (.md, .txt)
# - Data files (.csv, .tsv)
# - Scripts (.sh, .bat)
# - ANY text-based file!
```

---

## 🎯 FINAL RECOMMENDATION

**Use:** `search_replace()` as primary method  
**Supplement with:** `insert_after()`, `read_section()`  
**Works for:** ALL file types  
**Reliability:** ⭐⭐⭐⭐⭐  

**This is the industry standard approach used by Cursor, Aider, and all modern AI coding tools!**

---

**Would you like me to implement this universal file editor for your system?** 🚀

