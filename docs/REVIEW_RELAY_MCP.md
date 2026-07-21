# AI QA Factory Review Relay MCP

## Purpose

The Review Relay removes copy/paste between Claude Code in VS Code and an independent GPT reviewer.
It is **not** an execution plane and does not replace GitHub or the read-only Observer.

It stores only bounded, secret-redacted records under:

```text
<AIQA_OUTPUT_ROOT>/_review_relay/
  checkpoints/
  decisions/
  acks/
```

There is no shell tool, source-code write tool, Git merge tool, outreach tool, browser tool, or delivery
approval. A `GO` decision explicitly has `merge_authorized=false`.

## Role separation

Run two instances over the same `AIQA_OUTPUT_ROOT`:

- **worker** — local Claude Code/VS Code via stdio;
- **reviewer** — ChatGPT via authenticated HTTP + the existing operator-managed tunnel pattern.

Each instance exposes only the tools for its role.

### Worker tools

- `relay_submit_checkpoint`
- `relay_get_decision`
- `relay_ack_decision`
- `relay_get_status`

### Reviewer tools

- `relay_list_checkpoints`
- `relay_get_checkpoint`
- `relay_post_decision`
- `relay_get_status`

## Claude Code / VS Code configuration

Example `.vscode/mcp.json` entry (adapt paths to the local checkout):

```json
{
  "servers": {
    "ai-qa-review-relay-worker": {
      "type": "stdio",
      "command": "C:\\aiqa\\.venv\\Scripts\\python.exe",
      "args": ["C:\\aiqa\\tools\\run_review_relay_mcp.py"],
      "env": {
        "AIQA_OUTPUT_ROOT": "C:\\aiqa\\outputs",
        "AIQA_REVIEW_RELAY_ROLE": "worker"
      }
    }
  }
}
```

## Reviewer HTTP process

Use a separate token from the Observer token:

```powershell
$env:AIQA_OUTPUT_ROOT = "C:\aiqa\outputs"
$env:AIQA_REVIEW_RELAY_ROLE = "reviewer"
$env:AIQA_RELAY_MCP_TOKEN = "<strong random token from user environment>"
.venv\Scripts\python.exe tools\run_review_relay_mcp.py --http --host 127.0.0.1 --port 8775
```

Expose the loopback endpoint only through the same authenticated, operator-managed tunnel approach used
for the Observer. Never commit the token and never pass it as a tool argument.

## Slice protocol

1. Claude finishes the scoped slice and creates/pushes the PR.
2. Claude calls `relay_submit_checkpoint` with branch, exact head SHA, PR number, summary, and real gates.
3. Claude prints the returned checkpoint id and **does not merge or begin the next slice**.
4. The user asks the GPT reviewer to check the relay.
5. GPT reads the checkpoint, independently checks GitHub/Observer, and calls `relay_post_decision`.
6. `GO`/`NO-GO` is accepted only when `reviewed_sha` equals the checkpoint head SHA.
7. Claude calls `relay_get_decision`, applies only NO-GO blockers, then calls `relay_ack_decision`.
8. A changed head requires a new checkpoint; decisions are immutable and cannot be silently overwritten.

Claude may wait locally after submission:

```powershell
.venv\Scripts\python.exe tools\review_relay_wait.py <checkpoint-id> --timeout 3600
```

This wait command only reads local relay files. It does not invoke Claude, ChatGPT, shell actions, or
external services.

## Current automation boundary

The relay removes message copying, but this ChatGPT conversation is not an always-running daemon. The
owner still triggers the reviewer with a message such as `проверь relay`. A future external reviewer
service may automate that trigger, but it must be a separate, explicitly approved change.
