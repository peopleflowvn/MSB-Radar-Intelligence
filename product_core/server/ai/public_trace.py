"""Public workflow metadata, excluding provider-private reasoning content."""

_PRIVATE_KEYS = frozenset({"reasoning", "reasoning_trace", "thinking", "chain_of_thought"})


def public_metadata(value):
    if isinstance(value, dict):
        return {key: public_metadata(item) for key, item in value.items()
                if key not in _PRIVATE_KEYS}
    if isinstance(value, list):
        return [public_metadata(item) for item in value]
    return value
