# ADR-0003: Hosted AI Adapters (OpenRouter, Replicate)

## Status
Accepted

## Context
The core spec requires provider-neutral ports for all AI generation capabilities (text/vision/image/video/music/speech/SFX) but deliberately names no specific provider. The user's confirmed strategy is hybrid: hosted APIs for text/top-quality image/video, self-hosted OSS models for cost-sensitive volume work (music, voice, image edits). Standing up self-hosted GPU infrastructure is a real operational cost that would otherwise block Phase 2.

## Decision
- Route hosted text/vision generation through LiteLLM Proxy (self-hosted OSS gateway software) with OpenRouter configured as one of its routed providers.
- Use Replicate as the default hosted-inference adapter for image, video, music, and voice generation starting in Phase 2, running the same open-source model classes (Kokoro-class TTS, MusicGen-class music, SDXL-class image, video models) that this project may later self-host.
- Treat self-hosting (ComfyUI, AudioCraft/MusicGen, Kokoro-82M on owned GPUs) as an optional later migration behind the identical port, triggered by volume/cost, not a Phase 2 requirement.

Note: neither OpenRouter nor Replicate is open-source software — both are hosted SaaS. They are adopted because they are fully swappable behind the mandated provider-neutral ports, the same abstraction that makes a later self-hosted migration possible without touching application code.

## Consequences
- Phase 2 is not blocked on GPU procurement or ML-ops capability.
- Per-generation cost is higher than self-hosting at volume; cost-per-accepted-output telemetry (`21_PROVIDER_STRATEGY_AND_COSTS.md`) should be watched from launch to decide when self-hosting migration pays off.
- Video generation has no proposed self-hosted alternative and stays Replicate-hosted regardless of what happens with other media types.
