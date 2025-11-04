"""
Universal File Editor for AI Agents

Provides file editing capabilities for ANY file type (.py, .json, .html, .yaml, .md, .csv, etc.)
Compatible with AutoGen Core FunctionTool and AWS Bedrock Claude.
"""

import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import List
from typing_extensions import Annotated
from autogen_core.tools import FunctionTool


class UniversalFileEditor:
    """
    Universal file editing toolkit for AI agents.
    All methods return JSON strings for AutoGen compatibility.
    """
    
    @staticmethod
    def search_replace_in_file(
        file_path: Annotated[str, "Path to file (any type: .py, .json, .html, .md, etc.)"],
        old_string: Annotated[str, "EXACT text to find (must match exactly including whitespace, indentation, and newlines)"],
        new_string: Annotated[str, "New text to replace with"],
        replace_all: Annotated[bool, "Replace all occurrences (True) or just first (False)"] = False
    ) -> str:
        """
        Search and replace text in ANY file type.
        
        CRITICAL: old_string must match EXACTLY including:
        - Whitespace (spaces, tabs)
        - Indentation
        - Line breaks
        - Special characters
        
        Best Practice: Include 2-3 lines of context before/after the change
        
        Returns:
            JSON string with success status, match count, and details
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
            content = None
            used_encoding = None
            for encoding in ['utf-8', 'utf-8-sig', 'latin-1', 'cp1252']:
                try:
                    content = file.read_text(encoding=encoding)
                    used_encoding = encoding
                    break
                except UnicodeDecodeError:
                    continue
            
            if content is None:
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
            file.write_text(new_content, encoding=used_encoding or 'utf-8')
            
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
    
    @staticmethod
    def insert_after_text(
        file_path: Annotated[str, "Path to file"],
        search_text: Annotated[str, "Text after which to insert"],
        new_content: Annotated[str, "Content to insert"],
        occurrence: Annotated[int, "Which occurrence (1-based)"] = 1
    ) -> str:
        """
        Insert content after a specific line/text.
        Useful for adding new code/sections.
        
        Returns:
            JSON string with success status
        """
        try:
            file = Path(file_path)
            
            if not file.exists():
                return json.dumps({
                    "success": False,
                    "error": f"File not found: {file_path}"
                })
            
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
                "message": f"Inserted content after occurrence {occurrence}",
                "insert_position": insert_pos
            })
            
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e)
            })
    
    @staticmethod
    def insert_before_text(
        file_path: Annotated[str, "Path to file"],
        search_text: Annotated[str, "Text before which to insert"],
        new_content: Annotated[str, "Content to insert"],
        occurrence: Annotated[int, "Which occurrence (1-based)"] = 1
    ) -> str:
        """
        Insert content before a specific line/text.
        
        Returns:
            JSON string with success status
        """
        try:
            file = Path(file_path)
            
            if not file.exists():
                return json.dumps({
                    "success": False,
                    "error": f"File not found: {file_path}"
                })
            
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
            
            return json.dumps({
                "success": True,
                "message": f"Inserted content before occurrence {occurrence}",
                "insert_position": idx
            })
            
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e)
            })
    
    @staticmethod
    def delete_section(
        file_path: Annotated[str, "Path to file"],
        start_text: Annotated[str, "Start of section to delete (inclusive)"],
        end_text: Annotated[str, "End of section to delete (inclusive)"]
    ) -> str:
        """
        Delete a section of file between start and end markers.
        
        Returns:
            JSON string with success status
        """
        try:
            file = Path(file_path)
            
            if not file.exists():
                return json.dumps({
                    "success": False,
                    "error": f"File not found: {file_path}"
                })
            
            content = file.read_text(encoding='utf-8')
            
            start_idx = content.find(start_text)
            if start_idx == -1:
                return json.dumps({
                    "success": False,
                    "error": "Start text not found"
                })
            
            end_idx = content.find(end_text, start_idx)
            if end_idx == -1:
                return json.dumps({
                    "success": False,
                    "error": "End text not found"
                })
            
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
            return json.dumps({
                "success": False,
                "error": str(e)
            })
    
    @staticmethod
    def read_file_section(
        file_path: Annotated[str, "Path to file"],
        search_text: Annotated[str, "Text to find"],
        lines_before: Annotated[int, "Lines before match"] = 5,
        lines_after: Annotated[int, "Lines after match"] = 5
    ) -> str:
        """
        Read a section around search_text for context.
        Useful before editing to see exact formatting.
        
        Returns:
            JSON string with content and line numbers
        """
        try:
            file = Path(file_path)
            
            if not file.exists():
                return json.dumps({
                    "success": False,
                    "error": f"File not found: {file_path}"
                })
            
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
            return json.dumps({
                "success": False,
                "error": str(e)
            })
    
    @staticmethod
    def create_file_backup(
        file_path: Annotated[str, "Path to file to backup"]
    ) -> str:
        """
        Create a timestamped backup of file.
        
        Returns:
            JSON string with backup path
        """
        try:
            file = Path(file_path)
            
            if not file.exists():
                return json.dumps({
                    "success": False,
                    "error": "File not found"
                })
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = file.with_name(f"{file.stem}_{timestamp}{file.suffix}.bak")
            
            shutil.copy2(file, backup_path)
            
            return json.dumps({
                "success": True,
                "backup_path": str(backup_path),
                "message": f"Backup created: {backup_path.name}"
            })
            
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e)
            })
    
    @staticmethod
    def get_file_info(
        file_path: Annotated[str, "Path to file"]
    ) -> str:
        """
        Get file metadata (type, size, line count, encoding).
        
        Returns:
            JSON string with file information
        """
        try:
            file = Path(file_path)
            
            if not file.exists():
                return json.dumps({
                    "success": False,
                    "error": "File not found"
                })
            
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
            return json.dumps({
                "success": False,
                "error": str(e)
            })
    
    @classmethod
    def get_all_tools(cls) -> List[FunctionTool]:
        """
        Get all file editing tools as FunctionTool list for AutoGen.
        
        Returns:
            List of FunctionTool objects compatible with AutoGen Core
        """
        return [
            FunctionTool(
                cls.search_replace_in_file,
                description="Search for exact text in file and replace it. PRIMARY method for file editing. Works with ANY file type."
            ),
            FunctionTool(
                cls.insert_after_text,
                description="Insert content after specific text in file. Use for adding new sections."
            ),
            FunctionTool(
                cls.insert_before_text,
                description="Insert content before specific text in file. Use for adding new sections."
            ),
            FunctionTool(
                cls.delete_section,
                description="Delete section between start and end markers in file."
            ),
            FunctionTool(
                cls.read_file_section,
                description="Read section of file around search text. Use BEFORE editing to see exact formatting."
            ),
            FunctionTool(
                cls.create_file_backup,
                description="Create timestamped backup of file before editing."
            ),
            FunctionTool(
                cls.get_file_info,
                description="Get file metadata (type, size, line count)."
            )
        ]

