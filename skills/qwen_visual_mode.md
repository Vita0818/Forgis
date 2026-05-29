Qwen Visual Mode Rule:

- Qwen is a visual understanding provider, not a coding agent.
- Prefer reference-guided migration: find configured reference screenshots, inspect them, then use the visual guidance to inform main-agent code changes.
- Use it only for screenshot discovery, screenshot inspection, and visual comparison.
- Never send source code, secrets, tokens, .env, certificates, private keys, provisioning profiles, or private local configuration to Qwen.
- Use reference-first workflow.
- reference-only is valid visual migration guidance but is not full rendered visual validation.
- If the provider is unavailable, record a blocker and do not claim visual validation.
- Use only Forgis virtual screenshot paths through the sandbox tools.
- Actual screenshots are optional; Forgis does not need to run a simulator, device, or window screenshot capture.
- Main agent remains responsible for code edits, build, tests, and final report.
- User visual feedback has priority over Qwen similarity assessment.
