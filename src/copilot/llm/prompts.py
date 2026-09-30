"""All prompt text lives here, never inline in business logic."""

STRUCTURED_OUTPUT = """{task}

Reply with a single JSON object and nothing else. It must match this JSON schema:
{schema}"""

RETRY_INVALID_OUTPUT = """{original}

Your last output was invalid because: {error}
Reply again with only a corrected JSON object."""
