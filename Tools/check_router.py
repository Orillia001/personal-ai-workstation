from pathlib import Path
import json
import os
import sys

path = Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8-sig"))
errors = []
for name, provider in data.get("providers", {}).items():
    required = ("base_url", "api_key_env", "models")
    missing = [key for key in required if not provider.get(key)]
    if missing:
        errors.append(f"{name}: missing {', '.join(missing)}")
    env_name = provider.get("api_key_env", "")
    state = "configured" if env_name and os.getenv(env_name) else "key not set"
    print(f"{name:12} {state:12} models={', '.join(provider.get('models', []))}")
if errors:
    print("INVALID: " + "; ".join(errors))
    raise SystemExit(1)
print("VALID: configuration structure only; no network request was made.")

