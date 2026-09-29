# Crawler policy verification

Verified 2026-09-30 against current vendor guidance:

- Googlebot is allowed. Google documents robots.txt for crawl control, `noindex`
  for index control, canonical URLs, and sitemaps for discovery:
  https://developers.google.com/search/docs/crawling-indexing/googlebot
- Bingbot is allowed and segmented sitemaps contain only canonical pages.
  Microsoft recommends sitemaps, crawlable internal links, bounded page sets,
  and robots.txt for Bing indexing:
  https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/generative-ai-public-websites
- OAI-SearchBot is explicitly allowed for ChatGPT search. GPTBot is separately
  disallowed because OpenAI documents search and training controls as independent:
  https://developers.openai.com/api/docs/bots
- Claude-SearchBot and Claude-User are allowed; ClaudeBot training crawl is
  separately disallowed per Anthropic's distinct bot roles:
  https://support.anthropic.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler
- Applebot is allowed for Spotlight, Siri, Safari, and search; Applebot-Extended
  is separately disallowed without affecting search inclusion:
  https://support.apple.com/en-us/119829
- PerplexityBot and Perplexity-User are explicitly allowed for answer discovery
  and user retrieval.

All factual pages are server-rendered. Query/filter combinations carry
`noindex,follow` and are excluded from grouped sitemaps. `/internal/` is both
robots-blocked and bearer-protected; `/analytics/` only accepts a bounded event
and is not indexable. Robots rules are discovery controls, not an access-control
mechanism.
