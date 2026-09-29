# Harness, provider route, and workflow compatibility — 2026-09-29

Verification date: **2026-09-29**. Only official project documentation,
repositories, release feeds, and the locally installed Hermes checkout were
used for catalog claims. The normalized, UI-visible claims live in
`harness_claims`, `harness_access_methods`, `harness_mcp_capabilities`,
`route_compatibility_evidence`, and the workflow registry tables.

## Harness release snapshot

| Harness | Version verified | Primary official evidence |
|---|---|---|
| Codex CLI | 0.159.1 | <https://github.com/openai/codex/releases/tag/rust-v0.159.1> |
| Claude Code | 2.1.285 | <https://github.com/anthropics/claude-code/releases/tag/v2.1.285> |
| OpenCode | 1.18.33 | <https://github.com/anomalyco/opencode/releases> |
| Pi | 0.99.1 | <https://github.com/earendil-works/pi> |
| Qwen Code | 0.24.7 | <https://github.com/QwenLM/qwen-code/releases/tag/v0.24.7> |
| Gemini CLI | 0.61.0 stable | <https://github.com/google-gemini/gemini-cli/releases> |
| goose | 1.52.0 | <https://github.com/aaif-goose/goose/releases/tag/v1.52.0> |
| Cline | VS Code 4.1.21; CLI 3.0.65; Desktop 0.0.37 | <https://github.com/cline/cline/releases> |
| Roo Code | VS Code 3.54.0; CLI 0.1.17; archived | <https://github.com/RooCodeInc/Roo-Code> |
| Aider | PyPI 0.86.2; GitHub latest 0.86.0 | <https://pypi.org/project/aider-chat/0.86.2/> |
| Continue | IDE 2.0.0; CLI 1.5.47 | <https://github.com/continuedev/continue/releases/tag/v2.0.0-vscode> |
| ZCode | 3.14.3 | <https://zcode.z.ai/en/changelog> |
| Hermes Agent | VPS installed 0.20.0; upstream 0.21.5 | <https://github.com/NousResearch/hermes-agent/releases/tag/v2026.9.24> |
| Zed | 1.21.0 | <https://github.com/zed-industries/zed/releases/tag/v1.21.0> |

Important qualifications retained by the catalog:

- Codex custom providers now use the Responses protocol; generic Chat
  Completions compatibility is not claimed.
- Claude Code can use OpenRouter's Anthropic endpoint, but OpenRouter only
  guarantees Claude models and Anthropic does not support non-Claude gateway
  models. See <https://openrouter.ai/docs/guides/coding-agents/claude-code-integration>.
- Gemini CLI does not provide a native OpenRouter or generic OpenAI-compatible
  route. Consumer subscription access ended in 2026; enterprise Code Assist
  remains distinct from API-key access.
- Roo Code is archived, so its documented capabilities are marked frozen.
- Aider has no native MCP client at the cutoff; shell access is not presented
  as MCP support.
- ZCode and Zed are remote-capable desktop/IDE applications but are not
  general headless coding-agent CLIs.

## Manually checked route cases

Each result keeps four independent facts: harness model access, harness MCP
support, exact provider-route tool support, and known tool-call reliability.
Unverified reliability is never upgraded to “reliable” from protocol support.

| Case | Result | Why |
|---|---|---|
| OpenCode + GLM-5.3 via Z.ai | Compatible with configuration | Native Z.ai/Coding Plan or OpenAI-compatible endpoint; MCP host; exact route advertises tools. |
| OpenCode + GLM-5.3 via OpenRouter | Compatible with configuration | Native OpenRouter and MCP; exact OpenRouter route advertises tools. |
| Pi + GLM-5.3 via OpenRouter | Compatible with configuration | Native OpenRouter/custom provider and MCP; exact route advertises tools. |
| Hermes + GLM-5.3 via OpenRouter | Compatible with configuration | Installed provider registry includes OpenRouter; MCP stdio/HTTP/SSE confirmed in installed code. |
| Hermes + DeepSeek V4 Pro via OpenRouter | Compatible with configuration | Installed OpenRouter provider plus exact tool-capable route; reliability remains unverified. |
| Hermes + DeepSeek direct | Compatible | Installed native DeepSeek provider plus exact direct route; reliability remains unverified. |
| Codex + OpenAI gpt-6.1-sol | Compatible | Native OpenAI route; API key and ChatGPT/Codex subscription are shown as separate access choices. |
| Unreal MCP + OpenCode | Compatible with configuration | OpenCode hosts stdio/Streamable HTTP MCP; install one exact Unreal implementation. |
| Unreal MCP + Codex | Compatible with configuration | Codex hosts stdio/Streamable HTTP MCP; install one exact Unreal implementation. |

The catalog contains no invented “Unreal score” or “REAPER score.” Workflow
pages show the underlying coding/agent benchmark rows when present.

## Workflow implementation evidence

Unreal is represented by separate projects, including Epic's Experimental UE
5.8 server and distinct community architectures:

- <https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor>
- <https://github.com/IvanMurzak/Unreal-MCP>
- <https://github.com/ChiR24/Unreal_mcp>
- <https://github.com/x0cipher/unreal-mcp>
- <https://github.com/GenOrca/unreal-mcp>

No Cockos-official REAPER MCP server was found. The registry therefore lists
community implementations separately, including:

- <https://github.com/TwelveTake-Studios/reaper-mcp>
- <https://github.com/bonfire-systems/reaper-mcp>
- <https://github.com/danielkinahan/ReaMCP>

Filesystem, Git, GitHub, browser, and generic remote MCP records come from the
official MCP reference servers, GitHub MCP Server, Microsoft Playwright MCP,
and the MCP transport specification.

## Installed Hermes inspection

The VPS process runs Hermes from `/var/lib/hermes/.hermes/hermes-agent`.
Inspection was read-only and did not expose configuration values or
credentials. The installed checkout was package version **0.20.0**, commit
`6a6aacc1cb60fa5d7fd4ef1abcd5879116f25eca`. Its provider plugin registry
contains native OpenRouter, DeepSeek, Z.ai, OpenAI Codex, Anthropic, Qwen OAuth,
Alibaba Coding Plan, custom provider, and numerous other profiles. The
installed MCP client code supports stdio, Streamable HTTP, and SSE. The public
upstream release was newer (0.21.5), so the page deliberately displays both
installed and upstream versions rather than conflating them.
