Qwen Visual Mode Rule:

- Qwen is a visual understanding provider, not a coding agent.
- Use it only for screenshot inspection and visual comparison.
- Never send source code, secrets, tokens, .env, certificates, private keys, provisioning profiles, or private local configuration to Qwen.
- Use reference-first workflow.
- reference-only is allowed but is not full visual validation.
- If the provider is unavailable, record a blocker and do not claim visual validation.
- Use only Forgis virtual screenshot paths through the sandbox tools.
- Main agent remains responsible for code edits, build, tests, and final report.
- User visual feedback has priority over Qwen similarity assessment.
