# Migration Profile: local-first-app

Use this profile for local-first applications that store user data primarily on device.

## Strategy

- Prefer local storage over cloud services unless the source project clearly requires cloud sync.
- Avoid inventing backend services.
- Keep API keys, tokens, and user data out of generated code.
- Preserve import/export flows when possible.
- Record data model assumptions in notes under the target output directory.


## Translation-first local storage rule

Preserve the source app's local-first behavior.

Do not replace local storage with a server or cloud service.

Translate the source persistence model as directly as possible into the target stack.
