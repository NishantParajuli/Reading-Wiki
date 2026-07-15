#!/usr/bin/env python3
"""Defense-in-depth tool gate. Application validation remains authoritative."""
import json
import os
import re
import sys


def main():
    try:
        payload = json.load(sys.stdin)
        call = payload.get("toolCall") or {}
        name = str(call.get("name") or "")
        normalized = re.sub(r"[^a-z0-9]", "", name.lower())
        args = call.get("args") or {}
        allowed = {
            "readfile", "viewfile", "edit", "writetofile", "writefile",
            "replacefilecontent", "multireplacefilecontent",
        }
        if normalized not in allowed:
            print(json.dumps({"decision": "deny", "reason": "This isolated job permits only bounded file tools; terminal, network, MCP, permissions, and collaboration are forbidden."}))
            return
        roots = payload.get("workspacePaths") or []
        workspace = os.path.realpath(roots[0] if roots else os.getcwd())
        write_names = {
            "edit", "writetofile", "writefile", "replacefilecontent",
            "multireplacefilecontent",
        }
        path_values = []
        for key, value in args.items():
            key_name = str(key).lower()
            if (
                "path" in key_name or "director" in key_name
                or key_name in {"targetfile", "absolutefile", "searchfile"}
            ):
                if isinstance(value, str) and value:
                    path_values.append(value)
        if not path_values:
            print(json.dumps({"decision": "deny", "reason": "A bounded file path is required."}))
            return
        output = os.path.join(workspace, "output")
        readable_roots = (
            os.path.join(workspace, "input"),
            output,
        )
        for raw in path_values:
            resolved = os.path.realpath(raw if os.path.isabs(raw) else os.path.join(workspace, raw))
            if os.path.commonpath([workspace, resolved]) != workspace:
                print(json.dumps({"decision": "deny", "reason": "Outside-workspace access is forbidden."}))
                return
            if normalized in write_names and os.path.commonpath([output, resolved]) != output:
                print(json.dumps({"decision": "deny", "reason": "Writes are allowed only under output/."}))
                return
            if normalized not in write_names and resolved != workspace and not any(
                os.path.commonpath([root, resolved]) == root for root in readable_roots
            ):
                print(json.dumps({"decision": "deny", "reason": "Reads are limited to input/ and output/."}))
                return
        print(json.dumps({"decision": "allow"}))
    except Exception:
        print(json.dumps({"decision": "deny", "reason": "NovelWiki safety hook could not validate the tool call."}))


if __name__ == "__main__":
    main()
