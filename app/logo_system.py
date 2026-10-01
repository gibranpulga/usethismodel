"""Central, local-only lab and provider logo resolution."""

import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).parent / "static" / "logos"

# Asset IDs map to locally stored Simple Icons SVGs (CC0), or project-curated
# local marks documented in docs/logo-sources.md.
LABS = {
    "openai": ("OpenAI", "openai"),
    "anthropic": ("Anthropic", "anthropic"),
    "google": ("Google / Gemini", "google"),
    "deepseek": ("DeepSeek", "deepseek"),
    "zai": ("Z.ai", "zai"),
    "qwen": ("Qwen / Alibaba", "qwen"),
    "kimi": ("Moonshot / Kimi", "kimi"),
    "minimax": ("MiniMax", "minimax"),
    "mistral": ("Mistral", "mistral"),
    "meta": ("Meta", "meta"),
    "cohere": ("Cohere", "cohere"),
    "xai": ("xAI", None),
}
PROVIDERS = {
    "openrouter": ("OpenRouter", "openrouter"),
    "together": ("Together AI", "together"),
    "deepinfra": ("DeepInfra", "deepinfra"),
    "fireworks": ("Fireworks AI", "fireworks"),
    "groq": ("Groq", None),
    "cerebras": ("Cerebras", None),
    "replicate": ("Replicate", "replicate"),
    "fal": ("fal", None),
    "google": ("Google", "google"),
    "googleaistudio": ("Google AI Studio", "google"),
    "googlecloud": ("Google Cloud", "googlecloud"),
    "azure": ("Azure", None),
    "aws": ("AWS Bedrock", None),
    "cloudflare": ("Cloudflare Workers AI", "cloudflare"),
    "nanogpt": ("NanoGPT", None),
    "vercel": ("Vercel AI Gateway", "vercel"),
    "huggingface": ("Hugging Face", "huggingface"),
    "nvidia": ("NVIDIA", "nvidia"),
    "edenai": ("Eden AI", None),
    "poe": ("Poe", "poe"),
    "novita": ("Novita AI", None),
    "digitalocean": ("DigitalOcean", "digitalocean"),
    "zai": ("Z.ai", "zai"),
    "openai": ("OpenAI", "openai"),
    "anthropic": ("Anthropic", "anthropic"),
    "deepseek": ("DeepSeek", "deepseek"),
    "qwen": ("Qwen / Alibaba", "qwen"),
    "kimi": ("Moonshot / Kimi", "kimi"),
    "minimax": ("MiniMax", "minimax"),
    "mistral": ("Mistral", "mistral"),
    "cohere": ("Cohere", "cohere"),
    "meta": ("Meta", "meta"),
    "xai": ("xAI", None),
}


def _norm(name):
    value = (
        unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    )
    return re.sub(r"[^a-z0-9]+", "", value)


def _lab_key(name):
    n = _norm(name)
    if any(x in n for x in ("openai", "chatgpt", "gpt")):
        return "openai"
    if "anthropic" in n or "claude" in n:
        return "anthropic"
    if "google" in n or "gemini" in n:
        return "google"
    if "deepseek" in n:
        return "deepseek"
    if "zhipu" in n or n in {"zai", "z"} or "glm" in n:
        return "zai"
    if "qwen" in n or "alibaba" in n:
        return "qwen"
    if "moonshot" in n or "kimi" in n:
        return "kimi"
    if "minimax" in n:
        return "minimax"
    if "mistral" in n:
        return "mistral"
    if "meta" in n or "llama" in n:
        return "meta"
    if "cohere" in n or "command" in n:
        return "cohere"
    if "grok" in n or "xai" in n:
        return "xai"
    return None


def _provider_key(name):
    n = _norm(name)
    checks = (
        ("openrouter", "openrouter"),
        ("together", "together"),
        ("deepinfra", "deepinfra"),
        ("fireworks", "fireworks"),
        ("groq", "groq"),
        ("cerebras", "cerebras"),
        ("replicate", "replicate"),
        ("fal", "fal"),
        ("googleaistudio", "googleaistudio"),
        ("googlecloud", "googlecloud"),
        ("google", "googleaistudio"),
        ("azure", "azure"),
        ("bedrock", "aws"),
        ("amazon", "aws"),
        ("cloudflare", "cloudflare"),
        ("nanogpt", "nanogpt"),
        ("vercel", "vercel"),
        ("huggingface", "huggingface"),
        ("nvidia", "nvidia"),
        ("edenai", "edenai"),
        ("poe", "poe"),
        ("novita", "novita"),
        ("digitalocean", "digitalocean"),
        ("zhipu", "zai"),
        ("zai", "zai"),
        ("qwen", "qwen"),
        ("alibaba", "qwen"),
        ("openai", "openai"),
        ("anthropic", "anthropic"),
        ("deepseek", "deepseek"),
        ("kimi", "kimi"),
        ("moonshot", "kimi"),
        ("minimax", "minimax"),
        ("mistral", "mistral"),
        ("cohere", "cohere"),
        ("meta", "meta"),
        ("xai", "xai"),
    )
    return next((key for alias, key in checks if alias in n), None)


def resolve_logo(entity_type, name):
    """Return local asset, title, initials, and whether a real mark is available."""
    raw = str(name or "AI").strip() or "AI"
    mapping = LABS if entity_type == "lab" else PROVIDERS if entity_type == "provider" else {}
    key = _lab_key(raw) if entity_type == "lab" else _provider_key(raw)
    canonical, asset = mapping.get(key, (raw, None)) if key else (raw, None)
    path = (
        f"/static/logos/{'labs' if entity_type == 'lab' else 'providers'}/{asset}.svg"
        if asset
        else None
    )
    if (
        path
        and not (
            ROOT / ("labs" if entity_type == "lab" else "providers") / f"{asset}.svg"
        ).is_file()
    ):
        path = None
    initials = "".join(x[0] for x in re.findall(r"[A-Za-z0-9]+", canonical)[:2]).upper() or "AI"
    return {
        "path": path,
        "name": canonical,
        "initials": initials,
        "supported": bool(path),
        "wide": asset in {"cohere", "together", "fireworks", "deepinfra"},
    }


def logo_html(entity_type, name, size="small"):
    """Render the shared accessible logo component for templates/includes."""
    from markupsafe import Markup, escape

    mark = resolve_logo(entity_type, name)
    klass = f"entity-logo {'entity-logo-wide' if mark['wide'] else ''} logo-{size}"
    if mark["path"]:
        return Markup(
            '<img class="{}" src="{}" alt="" aria-hidden="true" width="28" height="28" loading="lazy" decoding="async">'
        ).format(escape(klass), escape(mark["path"]))
    return Markup('<span class="entity-logo-fallback logo-{}" aria-hidden="true">{}</span>').format(
        escape(size), escape(mark["initials"])
    )
