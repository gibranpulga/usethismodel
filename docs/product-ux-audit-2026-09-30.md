# Product and UX audit — 2026-09-30

Production was inspected with browser automation at `https://usethismodel.codefiction.net` before implementation. The revised local build was then inspected at desktop and mobile viewports in dark and light themes. Screenshots were captured in the browser audit session before and after the changes.

## Outcome

The product now leads with the four inputs needed to answer “What model should I use?”: use case, harness, budget, and required capabilities. Recommendations remain deterministic and evidence-based. The route hierarchy is explicit: canonical model → provider route → route price/deal → harness fit.

## Findings and changes

1. **Homepage** — Before: the correct inputs existed, but raw provider/category controls, 15 navigation links, and capability toggles visually competed with the decision. After: the core four inputs are above the fold, advanced controls are actually collapsed, My Setup is a primary call to action, and common scenarios are one click away.
2. **Models table** — Before: 100 full cards rendered by default (about 11,900 px desktop / 29,600 px mobile). After: 18 useful starting points per page, explicit non-ranking language, preserved search/filter URLs, and pagination for the long tail.
3. **Model detail** — Before: a canonical GLM page immediately rendered 91 routes and overflowed horizontally. After: the four-level hierarchy is explained, 12 current routes are shown initially, exact route IDs link to route detail, and all 91 remain searchable.
4. **Harness detail** — Source-backed claims, MCP transports, access methods, and route evidence were already strong. Navigation and route-card changes make the page easier to enter and scan without weakening caveats.
5. **Compatibility** — Before: the tested OpenCode + Unreal MCP view rendered 100 verbose evidence cards. After: the first 12 cost-ordered evidence matches are shown, with an instruction to narrow by model/provider. Candidate evaluation stops once the requested page is filled.
6. **Offers** — Before: the page reached roughly 29,300 px desktop / 56,200 px mobile. After: eight recently verified offers and eight free routes are shown first, totals are disclosed, and the long tail links back to searchable Models.
7. **Compare** — Before: only the first 100 cheapest routes were selectable, so intended models could be absent. After: model/provider/route search is built in, “GLM 5.3 with DeepSeek” is split into both families, route freshness/deals/benchmarks/harness checks are visible, and pinned routes can be compared from My Setup.
8. **Calculator** — Before: 97 result cards rendered on initial load. After: the 12 lowest exact calculations are shown with the total matching-route count and route-aware harness filtering retained.
9. **Navigation** — Before: 15 equally weighted sidebar destinations. After: six decision destinations are primary; data/reference sections live under “Explore data.”
10. **Mobile** — Before: canonical model, Offers, and My Setup had horizontal overflow; the mobile nav was 1,165 px wide and several pages exceeded 15,000–56,000 px height. After: every audited route has zero document-level horizontal overflow; route IDs wrap; tables scroll inside their containers; primary navigation is shorter; rendered result counts are bounded.

## Search checks

Deterministic interpretation now covers the requested language: `glm`, `glm 5.3`, `deepseek`, `free tools`, `cheap coding`, `openrouter`, `hermes`, `unreal`, `reaper mcp`, `3d`, `deals right now`, and `new models this week`. Punctuation-insensitive model matching remains intact.

## Manual scenarios

Measured from the homepage in the revised build:

| Scenario | Interactions | Typical local response | Result |
| --- | ---: | ---: | --- |
| Hermes + cheapest tool-capable | 1 | under 0.3 s | Direct scenario link; route compatibility and cost evidence |
| OpenCode + Unreal MCP | 1 | about 0.15 s after candidate short-circuiting | Host, MCP, route tools, and reliability shown separately |
| Free tool-capable models | 1 | about 0.02 s | Exact $0 endpoints and caveats |
| Compare GLM 5.3 with DeepSeek | 4 | about 0.11 s search response | One link, select two exact routes, compare |
| New models this week | 1 | under 0.3 s | Dated canonical releases |
| Deals right now | 1 | about 0.05 s | Current verified offers |
| 3D assets | 1 | about 0.01 s | Native-unit 3D routes |

The compare flow intentionally asks for exact routes rather than silently blending provider-specific prices.

## Performance evidence

The production baseline had 9,329 active provider routes. Local SQLite query timing was approximately 88–146 ms for the unfiltered route query and about 43 ms for `glm 5.3`; no speculative index was added because existing covering indexes were adequate and the dominant issue was over-rendering.

Initial HTML/render reductions:

| Page | Before | After |
| --- | --- | --- |
| Models | 100 cards, 161 KB production response | 18 cards, about 44 KB local response |
| GLM-5.3 detail | 91 cards, 10,947 px desktop | 12 cards, 2,622 px desktop |
| Offers | 29,335 px desktop | about 18 KB HTML; eight offers + bounded tables |
| Calculator | 97 cards, 7,824 px desktop | 12 cards, about 9 KB HTML |
| OpenCode + Unreal compatibility | 100 cards, about 1.3 s local before short-circuit | seven current matches, about 0.15 s warm local |

No document-level horizontal overflow remained on the audited desktop or mobile routes. Dark and light themes were visually checked after the changes.

## Verification

- Ruff passes.
- Full pytest suite passes.
- Desktop and mobile browser audit covers homepage, Models, model detail, harness detail, compatibility, Offers, Compare, Calculator, My Setup, navigation, dark theme, and light theme.
