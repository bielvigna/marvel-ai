from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from .ai_tools import build_tools
from .comic_vine import ComicVineClient
from .config import Settings


SPOILER_POLICY = {
    "NONE": "Do not reveal deaths, endings, plot twists, betrayals, identity reveals, or major future events. If a direct answer would spoil one, say you can answer with a higher spoiler setting.",
    "LOW": "Give basic context and avoid major consequences, deaths, endings, and major twists.",
    "MEDIUM": "Important events may be discussed, but preserve the main twists and endings.",
    "HIGH": "Answer fully, including major plot events and endings when supported by Comic Vine evidence.",
}

LANGUAGE_INSTRUCTIONS = {
    "pt-BR": "Respond in Brazilian Portuguese.",
    "en": "Respond in English.",
}

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def create_marvel_agent(settings: Settings, comic_vine: ComicVineClient, spoiler_level: str, language: str = "pt-BR"):
    if not settings.ai_api_key or not settings.ai_model:
        raise RuntimeError("AI_NOT_CONFIGURED")
    provider = settings.ai_provider.strip().lower()
    if provider not in {"openai", "openai-compatible", "groq"}:
        raise RuntimeError("UNSUPPORTED_AI_PROVIDER")
    model_options = {"model": settings.ai_model, "api_key": settings.ai_api_key, "temperature": 0.2}
    base_url = settings.ai_base_url.strip()
    if base_url:
        model_options["base_url"] = base_url
    elif provider == "groq":
        model_options["base_url"] = GROQ_BASE_URL
    model = ChatOpenAI(**model_options)
    return create_agent(
        model=model,
        tools=build_tools(comic_vine),
        system_prompt=(
            "You are Marvel Battlefield, a Marvel and comic-book research assistant. "
            + LANGUAGE_INSTRUCTIONS[language]
            + " Preserve Marvel character names and source URLs. "
            + "Use Comic Vine tools before stating verifiable facts about characters, powers, teams, issues, story arcs, or movies. "
            + "Never invent facts. If tools return no evidence, say so. Keep answers concise and cite Comic Vine links when available. "
            + "Follow this spoiler policy for this response: " + SPOILER_POLICY[spoiler_level]
        ),
    )


def normalize_spoiler_level(value: str) -> str:
    normalized = value.strip().upper()
    return normalized if normalized in SPOILER_POLICY else "NONE"
