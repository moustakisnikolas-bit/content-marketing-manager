import asyncio

import httpx

from content_studio.config import Settings

_POLL_INTERVAL_SECONDS = 2
_MAX_POLL_ATTEMPTS = 30  # ~60s ceiling for a single generation


class ReplicateImageAdapter:
    """Calls Replicate's prediction API (create -> poll -> fetch output),
    per 28_OSS_TECHNOLOGY_STACK.md's hosted-inference-by-default decision
    for image/video/music/voice. `model` is a Replicate model ref in
    `owner/name` or `owner/name:version` form."""

    def __init__(self, settings: Settings) -> None:
        self._api_token = settings.replicate_api_token

    async def generate_image(
        self, *, prompt: str, model: str, params: dict, reference_image_url: str | None = None
    ) -> bytes:
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
            "Prefer": "wait",
        }
        # params spread first so a reference image can't be silently
        # clobbered by a stray params["input_image"] (none exists today,
        # but this ordering makes the precedence unambiguous either way).
        input_payload = {"prompt": prompt, **params}
        if reference_image_url is not None:
            input_payload["input_image"] = reference_image_url
        payload = {"input": input_payload}

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
            # Replicate models return either a single URL or a list of URLs
            # depending on the model; normalize to "first output".
            image_url = output[0] if isinstance(output, list) else output

            image_response = await client.get(image_url)
            image_response.raise_for_status()
            return image_response.content

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
