"""Fit rule and GGUF-derived sizing for the model playground (docs/model-playground.md).

weights + context_reserve + overhead <= budget, one parallel slot, where
context_reserve = bytes_per_token * requested_context + fixed_cache.
Pure functions only: no I/O, no defaults hidden from the caller.
"""
GIB = 1024 ** 3
CONTEXT_PRESETS = (8192, 16384, 32768)
DEFAULT_CONTEXT = 8192
SWA_CELLS = 1536  # llama.cpp sizes the sliding-window cache at min(n_ctx, 1024 + n_ubatch) padded to 256.
KV_BYTES_PER_VALUE = {'f16': 2.0, 'bf16': 2.0, 'q8_0': 34 / 32, 'q4_0': 18 / 32}
# Architectures whose global-attention layers follow a fixed interleave; every other layer
# uses a fixed-size sliding-window cache. Unknown architectures fall back to all-global.
GLOBAL_LAYER_INTERVAL = {'gemma3': 6, 'gemma4': 6}


def presets(native_max):
    """Context presets offered for a model: the fixed ladder capped by, then including, native max."""
    ladder = [p for p in CONTEXT_PRESETS if p < native_max]
    return tuple(ladder + [native_max])


def snap_context(requested, native_max):
    """Round a requested context up to its ceiling preset; None when it exceeds native max."""
    if requested is None:
        requested = min(DEFAULT_CONTEXT, native_max)
    if requested > native_max:
        return None
    for preset in presets(native_max):
        if requested <= preset:
            return preset
    return None


def derive(model_info, kv_type):
    """Derive bytes_per_token and fixed_cache from Ollama /api/show model_info.

    Returns (bytes_per_token, fixed_cache, native_max, architecture, exact) where exact is
    False when the architecture is unknown and every layer was treated as full attention.
    """
    architecture = model_info.get('general.architecture')
    if not architecture:
        raise ValueError('model_info lacks general.architecture')
    prefix = architecture + '.'
    layers = int(model_info[prefix + 'block_count'])
    native_max = int(model_info[prefix + 'context_length'])
    kv_heads = model_info.get(prefix + 'attention.head_count_kv', model_info.get(prefix + 'attention.head_count'))
    head_dim = model_info.get(prefix + 'attention.key_length')
    if head_dim is None:
        head_dim = int(model_info[prefix + 'embedding_length']) // int(model_info[prefix + 'attention.head_count'])
    per_value = KV_BYTES_PER_VALUE[kv_type]

    def layer_bytes(index):
        heads = kv_heads[index] if isinstance(kv_heads, list) else kv_heads
        return 2 * int(heads) * int(head_dim) * per_value  # K and V

    interval = GLOBAL_LAYER_INTERVAL.get(architecture)
    sliding = model_info.get(prefix + 'attention.sliding_window')
    exact = interval is not None and sliding is not None
    bytes_per_token = 0.0
    fixed_cache = 0.0
    for index in range(layers):
        is_global = not exact or (index % interval == interval - 1)
        if is_global:
            bytes_per_token += layer_bytes(index)
        else:
            fixed_cache += layer_bytes(index) * SWA_CELLS
    return int(bytes_per_token), int(fixed_cache), native_max, architecture, exact


def fit(model, backend, context):
    """Return (fits, needed_bytes, largest_fitting_preset_or_None)."""
    def need(ctx):
        return model['weight_bytes'] + model['bytes_per_token'] * ctx + model['fixed_cache'] + backend['overhead_bytes']
    needed = need(context)
    fits = needed <= backend['budget_bytes']
    largest = None
    for preset in presets(model['native_max']):
        if need(preset) <= backend['budget_bytes']:
            largest = preset
    return fits, int(needed), largest


def refusal(model_name, backend_name, context, needed, budget, largest):
    gib = lambda b: f'{b / GIB:.1f} GiB'
    tail = f' The largest preset that fits is {largest}.' if largest else ' No context preset fits this model here.'
    return (f'Context {context} for {model_name} does not fit on {backend_name}: needs {gib(needed)}, '
            f'budget {gib(budget)}.{tail} Pick a smaller context or enable the override for this model.')
