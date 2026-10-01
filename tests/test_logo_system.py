from pathlib import Path

from app.logo_system import resolve_logo


def test_known_model_labs_resolve_to_local_marks():
    cases = {
        "GPT-6.1 Sol": "openai",
        "Claude X": "anthropic",
        "Gemini Pro": "google",
        "DeepSeek V4": "deepseek",
        "GLM-5.3": "zai",
        "Qwen 3": "qwen",
        "Kimi K2": "kimi",
        "MiniMax M2": "minimax",
        "Mistral Large": "mistral",
        "Llama 4": "meta",
        "Command R": "cohere",
        "Grok 4": None,
    }
    for name, expected in cases.items():
        result = resolve_logo("lab", name)
        if expected:
            assert result["path"].endswith(f"/{expected}.svg")
        elif name == "Grok 4":
            assert result["name"] == "xAI" and result["path"] is None


def test_provider_aliases_and_unknown_fallback():
    assert resolve_logo("provider", "OpenRouter")["path"].endswith("/openrouter.svg")
    assert resolve_logo("provider", "Deep Infra")["path"].endswith("/deepinfra.svg")
    assert resolve_logo("provider", "Together AI")["path"].endswith("/together.svg")
    assert resolve_logo("provider", "Fireworks AI")["path"].endswith("/fireworks.svg")
    assert resolve_logo("provider", "Z.ai")["path"].endswith("/zai.svg")
    unknown = resolve_logo("provider", "Example Routing")
    assert unknown["path"] is None and unknown["initials"] == "ER"


def test_all_resolved_asset_paths_exist_and_svg_is_local_safe():
    for kind, mapping in (
        (
            "lab",
            [
                "OpenAI",
                "Anthropic",
                "Google",
                "DeepSeek",
                "Qwen",
                "Kimi",
                "MiniMax",
                "Mistral",
                "Meta",
                "Cohere",
                "Z.ai",
            ],
        ),
        (
            "provider",
            [
                "OpenRouter",
                "Replicate",
                "Google Cloud",
                "Cloudflare",
                "Vercel",
                "Hugging Face",
                "NVIDIA",
                "Poe",
                "DigitalOcean",
                "Together AI",
                "Fireworks AI",
                "Deep Infra",
            ],
        ),
    ):
        for name in mapping:
            path = resolve_logo(kind, name)["path"]
            assert path and Path("app" + path).is_file()
            svg = Path("app" + path).read_text().lower()
            assert "<script" not in svg and "href=" not in svg


def test_dark_mode_safety_uses_contained_neutral_assets():
    # The same monochrome marks sit on a neutral white contained surface in both themes.
    css = Path("app/static/product.css").read_text()
    assert ".entity-logo" in css and "background:#fff" in css
    assert ".entity-logo-fallback" in css


def test_every_mapped_asset_exists():
    from app.logo_system import LABS, PROVIDERS

    for entity_type, mapping in (("lab", LABS), ("provider", PROVIDERS)):
        for _label, asset in mapping.values():
            if asset:
                result = resolve_logo(entity_type, _label)
                assert result["path"] and Path("app" + result["path"]).is_file()


def test_wordmarks_keep_readable_wide_intrinsic_space():
    assert resolve_logo("provider", "DeepInfra")["wide"] is True
    assert resolve_logo("provider", "OpenRouter")["wide"] is False
    css = Path("app/static/product.css").read_text()
    assert ".entity-logo-wide.logo-small{width:64px}" in css
