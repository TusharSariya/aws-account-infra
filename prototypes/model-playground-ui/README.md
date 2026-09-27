# Model playground UI prototype (wayfinder #243)

Throwaway rig to react to Open WebUI and SillyTavern from a phone before the
playground spec picks a UI. Nothing here is deployed; the compose file's header
has the start, expose and stop commands. SillyTavern's whitelist is disabled in
`sillytavern-config/config.yaml` because Tailscale serve proxies from localhost.

What to react to on the phone (from the ticket): mobile layout, model switching,
pulling a model by Hugging Face URL, system-prompt presets and per-chat
parameters including context length, chat history, and how a "backend waking"
state surfaces. Notes and screenshots are captured on the ticket, not here.
