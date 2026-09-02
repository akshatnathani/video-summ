"""ELI5 and detailed summarization using Google Gemini. Shared by gateway (on-demand) and ingest (pipeline)."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from google import genai

ELI5_SYSTEM = """You are an expert at explaining complex topics simply — like you're talking to a curious 5-year-old (or someone with no background in the topic).

Rules:
- Use simple words, short sentences, and everyday analogies
- Avoid jargon completely — if you must use a technical term, explain it in plain language immediately
- Make it conversational and warm
- Focus on the "why" and "what it means" not just the "what"
- Use analogies: "Think of it like...", "Imagine...", "It's similar to..."
- Keep it under 300 words
- No markdown, no bullet points — just friendly paragraphs"""

DETAILED_SYSTEM = """You are a skilled technical writer creating comprehensive but accessible summaries.

Rules:
- Structure with clear sections (Overview, Key Points, Details, Implications)
- Include specific facts, numbers, and quotes from the transcript
- Explain technical concepts clearly for an educated layperson
- Highlight what's important and why it matters
- Note any claims that seem questionable or need verification
- 500-1000 words
- Use markdown for readability"""

KEY_POINTS_SYSTEM = """Extract the 5-7 most important takeaways from this video transcript.

Rules:
- Each point: one clear sentence, self-contained
- Focus on actionable insights, surprising facts, or key arguments
- Quote timestamps where relevant: [MM:SS]
- No fluff, no repetition
- Return as JSON array of strings"""

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n?|\n?\s*```\s*$")


def build_context(
    transcript_text: str, segments: list[dict], title: str = "", duration: float = 0
) -> str:
    timestamped = "\n".join(
        f"[{int(s['start']//60):02d}:{int(s['start']%60):02d}] {s['text']}"
        for s in segments[:200]  # Limit for token budget
    )
    return f"Video: {title}\nDuration: {duration/60:.1f} minutes\n\nTranscript:\n{timestamped}"


def parse_key_points(text: str) -> list[str]:
    """Parse the model's key-points response, tolerating ```json fences and plain lists."""
    stripped = _FENCE_RE.sub("", text or "[]").strip()
    try:
        points = json.loads(stripped)
        if isinstance(points, list):
            return [str(p) for p in points[:7]]
    except json.JSONDecodeError:
        pass
    lines = [l.strip(" -•\t") for l in stripped.split("\n") if l.strip()]
    return lines[:7]


class Summarizer:
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    # ── sync (used by the ingest worker thread) ────────────────

    def summarize(
        self, transcript_text: str, segments: list[dict], title: str = "", duration: float = 0
    ) -> dict[str, Any]:
        context = build_context(transcript_text, segments, title, duration)
        eli5 = self._generate(ELI5_SYSTEM, context, temperature=0.7)
        detailed = self._generate(DETAILED_SYSTEM, context, temperature=0.5)
        key_points = self._generate_key_points(context)
        return {"eli5": eli5, "detailed": detailed, "key_points": key_points}

    def _generate(self, system: str, user: str, temperature: float = 0.5) -> str:
        response = self.client.models.generate_content(
            model=self.model,
            contents=f"{system}\n\n{user}",
            config={"temperature": temperature, "max_output_tokens": 2000},
        )
        return response.text or ""

    def _generate_key_points(self, context: str) -> list[str]:
        response = self.client.models.generate_content(
            model=self.model,
            contents=f"{KEY_POINTS_SYSTEM}\n\n{context}",
            config={"temperature": 0.3, "max_output_tokens": 1000},
        )
        return parse_key_points(response.text or "[]")

    # ── async (used by the gateway's on-demand endpoint) ────────

    async def summarize_async(
        self, transcript_text: str, segments: list[dict], title: str = "", duration: float = 0
    ) -> dict[str, Any]:
        context = build_context(transcript_text, segments, title, duration)
        eli5_resp, detailed_resp, kp_resp = await asyncio.gather(
            self.client.models.generate_content_async(
                model=self.model, contents=f"{ELI5_SYSTEM}\n\n{context}",
                config={"temperature": 0.7, "max_output_tokens": 2000},
            ),
            self.client.models.generate_content_async(
                model=self.model, contents=f"{DETAILED_SYSTEM}\n\n{context}",
                config={"temperature": 0.5, "max_output_tokens": 3000},
            ),
            self.client.models.generate_content_async(
                model=self.model, contents=f"{KEY_POINTS_SYSTEM}\n\n{context}",
                config={"temperature": 0.3, "max_output_tokens": 1000},
            ),
        )
        return {
            "eli5": eli5_resp.text or "",
            "detailed": detailed_resp.text or "",
            "key_points": parse_key_points(kp_resp.text or "[]"),
        }
