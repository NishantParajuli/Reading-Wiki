#!/usr/bin/env python3
"""Defense-in-depth tool gate. Application validation remains authoritative."""
import json
import os
import sys


def main():
    try:
        payload = json.load(sys.stdin)
        call = payload.get("toolCall") or {}
        name = str(call.get("name") or "")
        args = call.get("args") or {}
        forbidden = {
            "run_command", "manage_task", "schedule", "ask_permission", "list_permissions",
            "search_web", "read_url", "read_url_content", "execute_url", "invoke_subagent", "define_subagent",
            "send_message", "manage_subagents", "generate_image", "ask_question",
        }
        if name in forbidden or name.startswith("browser_") or "mcp" in name.lower():
            print(json.dumps({"decision": "deny", "reason": "This isolated job forbids execution, network, MCP, and collaboration tools."}))
            return
        roots = payload.get("workspacePaths") or []
        workspace = os.path.realpath(roots[0] if roots else os.getcwd())
        write_names = {"write_to_file", "replace_file_content", "multi_replace_file_content"}
        path_values = []
        for key in ("TargetFile", "AbsolutePath", "DirectoryPath", "SearchPath", "SearchDirectory"):
            if args.get(key):
                path_values.append(str(args[key]))
        for raw in path_values:
            resolved = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(workspace, raw))
            if os.path.commonpath([workspace, resolved]) != workspace:
                print(json.dumps({"decision": "deny", "reason": "Outside-workspace access is forbidden."}))
                return
            if name in write_names and os.path.commonpath([os.path.join(workspace, "output"), resolved]) != os.path.join(workspace, "output"):
                print(json.dumps({"decision": "deny", "reason": "Writes are allowed only under output/."}))
                return
        print(json.dumps({"decision": "allow"}))
    except Exception:
        print(json.dumps({"decision": "deny", "reason": "NovelWiki safety hook could not validate the tool call."}))


if __name__ == "__main__":
    main()
