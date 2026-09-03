import asyncio
import base64

import httpx

from content_studio.config import Settings

_POLL_INTERVAL_SECONDS = 2
_MAX_POLL_ATTEMPTS = 30  # ~60s ceiling for a single generation

# flux-kontext-pro's own input schema (confirmed live against Replicate's
# API) has no resolution/megapixel control at all — output is a fixed
# ~1MP budget regardless of prompt or params, which reads soft next to
# Meta's own recommended minimums (1080x1080 feed, 1080x1920 story). A
# dedicated upscale pass afterward is the only lever this model exposes
# for actually raising resolution.
_UPSCALE_MODEL = "nightmareai/real-esrgan"
# 2x, not the model's own 4x default — doubles resolution (comfortably
# past Meta's minimums for any image this pipeline produces) without the
# extra latency/cost/file-size a 4x pass would add for no visible benefit
# at social-post display sizes.
_UPSCALE_SCALE = 2


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
            raw_bytes = image_response.content

            try:
                return await self._upscale(client, raw_bytes, headers)
            except (httpx.HTTPError, RuntimeError, TimeoutError, KeyError):
                # Best-effort — a resolution boost, not core functionality.
                # A failed upscale pass must never lose an otherwise-good
                # generation; ship the model's own (lower-resolution)
                # output rather than fail the whole job over it.
                return raw_bytes

    async def _upscale(self, client: httpx.AsyncClient, image_bytes: bytes, headers: dict) -> bytes:
        data_uri = f"data:image/png;base64,{base64.b64encode(image_bytes).decode()}"
        response = await client.post(
            f"https://api.replicate.com/v1/models/{_UPSCALE_MODEL}/predictions",
            headers=headers,
            json={"input": {"image": data_uri, "scale": _UPSCALE_SCALE, "face_enhance": False}},
        )
        response.raise_for_status()
        prediction = await self._await_completion(client, response.json(), headers)
        output = prediction["output"]
        upscaled_url = output[0] if isinstance(output, list) else output

        upscaled_response = await client.get(upscaled_url)
        upscaled_response.raise_for_status()
        return upscaled_response.content

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
