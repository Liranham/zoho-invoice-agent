"""Stdlib-only HTTPS client for Goldman's remote MCP endpoint.

The Goldman MCP server is an interactively-authenticated claude.ai connector, so it
is NOT loaded in scheduled / headless Claude runs -- every tool (wise_transactions,
create_invoice, notify_liran, ...) simply appears to not exist. The same tool surface
is also served as JSON-RPC over HTTPS by the Render service, which any run can reach.

Deliberately depends on nothing outside the standard library: this is the path used
when the normal path is already broken, so it must not need a virtualenv or an
installed `requests` to work.

CLI:
    python3 goldman_mcp.py list
    python3 goldman_mcp.py call wise_transactions '{"start":"2026-07-01","stop":"2026-07-21"}'
"""

import json
import os
import sys
import urllib.error
import urllib.request

DEFAULT_ENDPOINT = "https://goldman-qzv3.onrender.com/mcp"
DEFAULT_TIMEOUT = 300
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


class GoldmanMCPError(Exception):
    """Raised when the endpoint is unreachable or returns a JSON-RPC error."""


def load_api_key(env_path=ENV_PATH):
    """Return GOLDMAN_API_KEY from the environment, falling back to the .env file."""
    key = os.environ.get("GOLDMAN_API_KEY")
    if key:
        return key.strip()

    try:
        with open(env_path) as handle:
            for line in handle:
                line = line.strip()
                if line.startswith("GOLDMAN_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass

    raise GoldmanMCPError(
        "GOLDMAN_API_KEY not found in the environment or {}".format(env_path)
    )


def _request(payload, api_key, endpoint, timeout):
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer {}".format(api_key),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise GoldmanMCPError("HTTP {} from Goldman: {}".format(exc.code, detail))
    except urllib.error.URLError as exc:
        raise GoldmanMCPError("Could not reach Goldman at {}: {}".format(endpoint, exc.reason))

    try:
        parsed = json.loads(body)
    except ValueError:
        raise GoldmanMCPError("Goldman returned non-JSON: {}".format(body[:500]))

    if "error" in parsed:
        raise GoldmanMCPError("Goldman returned an error: {}".format(json.dumps(parsed["error"])[:500]))

    return parsed.get("result", {})


def list_tools(api_key=None, endpoint=DEFAULT_ENDPOINT, timeout=DEFAULT_TIMEOUT):
    """Return the list of tool names the endpoint currently serves."""
    result = _request(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        api_key or load_api_key(),
        endpoint,
        timeout,
    )
    return [tool["name"] for tool in result.get("tools", [])]


def call_tool(name, arguments=None, api_key=None, endpoint=DEFAULT_ENDPOINT, timeout=DEFAULT_TIMEOUT):
    """Call one Goldman tool and return its text output as a single string."""
    result = _request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
        api_key or load_api_key(),
        endpoint,
        timeout,
    )
    return "".join(block.get("text", "") for block in result.get("content", []))


def main(argv):
    if len(argv) < 2 or argv[1] not in ("list", "call"):
        print(__doc__.strip())
        return 2

    try:
        if argv[1] == "list":
            print("\n".join(list_tools()))
            return 0

        if len(argv) < 3:
            print("usage: goldman_mcp.py call <tool_name> ['<json arguments>']", file=sys.stderr)
            return 2

        arguments = json.loads(argv[3]) if len(argv) > 3 else {}
        print(call_tool(argv[2], arguments))
        return 0
    except GoldmanMCPError as exc:
        print("GOLDMAN_MCP_FAILED: {}".format(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print("Invalid JSON arguments: {}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
