# Logo assets and sources

Retrieved 2026-10-01. SVGs are stored locally and requested from this site only. Simple Icons assets use CC0 1.0 Universal (license: https://github.com/simple-icons/simple-icons/blob/develop/LICENSE.md). Brand marks remain the property of their owners; use is for identification.

| Brand / files | Source | License or usage note |
|---|---|---|
| Anthropic, Google, DeepSeek, Qwen, Kimi, MiniMax, Meta, OpenRouter, Replicate, Google Cloud, Cloudflare, Vercel, Hugging Face, NVIDIA, Poe, DigitalOcean | https://github.com/simple-icons/simple-icons/tree/develop/icons (matching SVG files) | Simple Icons, CC0 1.0; monochrome brand marks |
| OpenAI | https://git.mibew.org/Mibew/simple-icons/src/commit/867e93290c2479f613fea92732a9f8ae98a13d52/icons/openai.svg | Simple Icons mirror, CC0 1.0; monochrome brand mark |
| Z.ai | https://z.ai/ (official site references https://z-cdn.chatglm.cn/z-ai/static/logo.svg) | Official Z.ai mark; local SVG with export metadata removed |
| Cohere | https://cohere.com/logo.svg | Official Cohere logo; local SVG |
| Together AI | https://www.together.ai/ (inline navigation logo) | Official multicolor logo; local SVG |
| Fireworks AI | https://fireworks.ai/ (official site Sanity asset `46d329cfd46294a5986218e94752d5d283cbe16c-343x44.svg`) | Official Fireworks wordmark; local SVG |
| Corporate API-provider aliases (OpenAI, Anthropic, Google, DeepSeek, Z.ai, Qwen, Kimi, MiniMax, Mistral, Meta, Cohere) | The corresponding sourced lab mark above, copied under `app/static/logos/providers/` | Alias mapping remains separate for lab and route provider identity |

## Brands using the initials fallback

The catalog includes many aggregators and gateways without a safely sourced local brand asset. In the specifically requested provider set, Groq, Cerebras, fal, Azure, and AWS Bedrock currently use the fallback. The Groq brand policy restricts copying its corporate logo without permission, so a fallback is safer than an unlicensed mark.

| DeepInfra | https://deepinfra.com/ (official header `aria-label="Logo"` SVG) | Official DeepInfra wordmark; local SVG |

The official xAI site blocked retrieval during this audit; `xAI` uses the fallback. The similar Simple Icons `x` asset is X Corp's mark, so it is not substituted for xAI.

The canonical aliases and fallback renderer are in `app/logo_system.py`.
