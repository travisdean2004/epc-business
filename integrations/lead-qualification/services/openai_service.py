import json
import logging
from typing import Optional

from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a B2B sales lead qualification assistant.
Analyze the provided lead and return ONLY a valid JSON object with these exact fields:
- lead_score: integer from 0 to 100 reflecting purchase intent and fit
- priority: exactly one of "Hot", "Warm", or "Cold"
- summary: one sentence describing the lead's need
- recommended_action: the single best next step for the sales team

Return ONLY the JSON object. No markdown fences, no explanation."""


def qualify_lead(name: str, email: str, company: str, message: str) -> Optional[dict]:
    client = OpenAI(api_key=get_settings().openai_api_key)

    user_prompt = (
        f"Name: {name}\n"
        f"Email: {email}\n"
        f"Company: {company}\n"
        f"Message: {message}"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        data = json.loads(content)

        required = {"lead_score", "priority", "summary", "recommended_action"}
        if not required.issubset(data.keys()):
            logger.error("OpenAI response missing required fields: %s", data)
            return None

        data["lead_score"] = max(0, min(100, int(data["lead_score"])))

        if data["priority"] not in ("Hot", "Warm", "Cold"):
            logger.warning("Unexpected priority value '%s', defaulting to Warm", data["priority"])
            data["priority"] = "Warm"

        return data

    except json.JSONDecodeError as exc:
        logger.error("Failed to parse OpenAI response as JSON: %s", exc)
        return None
    except Exception as exc:
        logger.error("OpenAI API error: %s", exc)
        return None
