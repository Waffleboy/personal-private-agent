import os

import pydantic_ai.models

# Set up dummy API key for testing (required to initialize pydantic_ai models)
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-key")

# Disable real model requests in tests
pydantic_ai.models.ALLOW_MODEL_REQUESTS = False
