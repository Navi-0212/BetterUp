import json
import os
from typing import Any

from src.models import ConflictResolution, Employee


SYSTEM_PROMPT = """You are resolving a data conflict for an HR onboarding sync system. You
will be given two employee records that a deterministic name-similarity
check flagged as a possible match. Decide whether they are the same
person, different people, or too ambiguous to auto-decide. Respond with
ONLY a JSON object, no other text, matching exactly this shape:
{"decision": "same_person" | "different_person" | "needs_human_review",
 "confidence": <float 0.0-1.0>, "reasoning": "<one sentence>"}"""


class GeminiHandler:
    def __init__(
        self,
        client: Any = None,
        model: str | None = None,
    ) -> None:
        """If client is None, construct a real genai.Client() using
        GEMINI_API_KEY. Tests inject a fake client.
        model defaults to env var GEMINI_MODEL, falling back to
        'gemini-2.5-flash'."""
        if client is not None:
            self.client = client
        else:
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
            if api_key:
                try:
                    from google import genai

                    self.client = genai.Client(api_key=api_key)
                except Exception:
                    self.client = None
            else:
                self.client = None

        self.model = (
            model or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
        )

    def resolve_conflict(
        self, record_a: Employee, record_b: Employee, context: str
    ) -> ConflictResolution:
        """Resolves ambiguous identity conflicts between two employee records with confidence gating."""
        if self.client is None:
            return ConflictResolution(
                decision="needs_human_review",
                confidence=0.0,
                reasoning="Gemini client not configured or GEMINI_API_KEY missing",
            )

        user_prompt = f"""Record A (existing, from {record_a.source_system}):
{record_a.model_dump_json(indent=2)}

Record B (incoming, from {record_b.source_system}):
{record_b.model_dump_json(indent=2)}

Context: {context}"""

        try:
            # Handle official google-genai client with models.generate_content
            if hasattr(self.client, "models") and hasattr(self.client.models, "generate_content"):
                try:
                    from google.genai import types

                    config = types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.0,
                        response_mime_type="application/json",
                    )
                except Exception:
                    config = None

                response = self.client.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=config,
                )
                raw_text = getattr(response, "text", "") or str(response)
            elif hasattr(self.client, "generate_content"):
                response = self.client.generate_content(user_prompt)
                raw_text = getattr(response, "text", "") or str(response)
            elif hasattr(self.client, "messages") and hasattr(self.client.messages, "create"):
                # Support message create style stubs
                response = self.client.messages.create(
                    model=self.model,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                raw_text = response.content[0].text
            else:
                raw_text = str(self.client)

            raw_text = raw_text.strip()
            # Handle potential markdown code fences in LLM output
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_text = "\n".join(lines).strip()

            parsed = json.loads(raw_text)
            resolution = ConflictResolution.model_validate(parsed)

            # Confidence gating: force override if confidence < 0.70
            if resolution.confidence < 0.70:
                return ConflictResolution(
                    decision="needs_human_review",
                    confidence=resolution.confidence,
                    reasoning=f"Confidence {resolution.confidence:.2f} below threshold (0.70): {resolution.reasoning}",
                )

            return resolution

        except Exception as e:
            return ConflictResolution(
                decision="needs_human_review",
                confidence=0.0,
                reasoning=f"Conflict resolution fallback due to error: {str(e)}",
            )
