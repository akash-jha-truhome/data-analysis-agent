from google import genai
from google.genai import types


class GeminiProvider:
    # Flash tier — cheapest sensible default for code generation + answer
    # composition. See spec/architecture.md > Stack.
    DEFAULT_MODEL = "gemini-3.1-flash"

    def __init__(self, api_key: str, model: str) -> None:
        self._client = genai.Client(api_key=api_key)
        self._model = model or self.DEFAULT_MODEL

    def _generate(self, prompt: str, system: str | None):
        config = (
            types.GenerateContentConfig(system_instruction=system)
            if system
            else None
        )
        return self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )

    def call_model(self, prompt: str, *, system: str | None = None) -> str:
        return self._generate(prompt, system).text

    def call_with_usage(
        self, prompt: str, *, system: str | None = None
    ) -> tuple[str, dict]:
        """Return (text, {prompt, completion, total}) token usage.

        ``google-genai`` exposes ``response.usage_metadata`` with
        ``prompt_token_count`` / ``candidates_token_count`` / ``total_token_count``.
        """
        response = self._generate(prompt, system)
        usage = _extract_usage(getattr(response, "usage_metadata", None))
        return response.text, usage


def _extract_usage(meta) -> dict:
    if meta is None:
        return {"prompt": 0, "completion": 0, "total": 0}
    prompt = int(getattr(meta, "prompt_token_count", 0) or 0)
    completion = int(getattr(meta, "candidates_token_count", 0) or 0)
    total = int(getattr(meta, "total_token_count", 0) or 0)
    if total == 0:
        total = prompt + completion
    return {"prompt": prompt, "completion": completion, "total": total}
