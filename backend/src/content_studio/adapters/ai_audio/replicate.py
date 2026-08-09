import asyncio

import httpx

from content_studio.config import Settings

_POLL_INTERVAL_SECONDS = 2
_MAX_POLL_ATTEMPTS = 60  # audio/music generation runs longer than image — ~120s ceiling


class ReplicateAudioAdapter:
    """Calls Replicate's prediction API (create -> poll -> fetch output),
    same shape as ReplicateImageAdapter — Replicate's API is generic across
    model classes, so voiceover/music models work through the identical
    create/poll/fetch flow. `model` is a Replicate model ref in
    `owner/name` or `owner/name:version` form."""

    def __init__(self, settings: Settings) -> None:
        self._api_token = settings.replicate_api_token

    async def generate_audio(self, *, prompt: str, model: str, params: dict) -> bytes:
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        }
        payload = {"input": {"prompt": prompt, **params}}

        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10)) as client:
            response = await client.post(
                f"https://api.replicate.com/v1/models/{model}/predictions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            prediction = response.json()

            prediction = await self._await_completion(client, prediction, headers)
            output = prediction["output"]
            # Audio models return either a single URL or a list of URLs
            # depending on the model; normalize to "first output".
            audio_url = output[0] if isinstance(output, list) else output

            audio_response = await client.get(audio_url)
            audio_response.raise_for_status()
            return audio_response.content

    async def _await_completion(
        self, client: httpx.AsyncClient, prediction: dict, headers: dict
    ) -> dict:
        for _ in range(_MAX_POLL_ATTEMPTS):
            status = prediction["status"]
            if status == "succeeded":
                return prediction
            if status in ("failed", "canceled"):
                raise RuntimeError(f"Replicate prediction {status}: {prediction.get('error')}")

            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
            poll_response = await client.get(prediction["urls"]["get"], headers=headers)
            poll_response.raise_for_status()
            prediction = poll_response.json()

        raise TimeoutError("Replicate prediction did not complete in time")
