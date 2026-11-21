#!/usr/bin/env python3
"""Whitelisted board overrides for tools/mkadt_pandora.py.

mkadt_pandora.py hard-codes the 17 Pro Max board constants. A port supplies an
`adt_overrides.json` (produced by gen_byron_config.py) and passes
`--board-json PATH`; only the keys below may change. Anything else is rejected
so a typo or a stray key can never silently corrupt the ADT.

Standalone module so it can be unit-tested without importing mkadt_pandora.py
(which needs the external `adt.py` that upstream does not ship in this repo).
"""
import json

ALLOWED = {
    'PHYS_BASE', 'MEM_SIZE', 'HIGH_PHYS_BASE', 'HIGH_MEM_SIZE', 'PANIC_LOG_SIZE',
    'SOC_BASE', 'DSP_SHM', 'DSP_SHM_SIZE',
    'GICD', 'GICD_SIZE', 'GICR', 'GICR_SIZE',
    'FB', 'FB_SIZE', 'FB_W', 'FB_H', 'FB_STRIDE',
    'UFS', 'UFS_SIZE', 'TIMEBASE', 'VTIMER_INTID', 'MPIDRS',
    'PANDORA_ECID', 'BOOT_MANIFEST_HASH',
}
INTS = ALLOWED - {'MPIDRS', 'BOOT_MANIFEST_HASH'}


def coerce(key, value):
    if key == 'MPIDRS':
        if not isinstance(value, list):
            raise ValueError('MPIDRS must be a list')
        return [_scalar(x) for x in value]
    if key in INTS:
        return _scalar(value)
    return value


def _scalar(v):
    if isinstance(v, bool):
        raise ValueError('boolean is not a board constant')
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        try:
            return int(s, 0)
        except ValueError:
            raise ValueError('expected an integer (0x... or decimal), got %r' % v[:40])
    raise ValueError('expected integer, got %r' % (type(v).__name__,))


def apply_board_overrides(namespace, path):
    """Apply overrides into a module globals() dict. Returns applied key list."""
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    ov = data.get('overrides', data)
    if not isinstance(ov, dict):
        raise ValueError('overrides must be an object')
    unknown = sorted(set(ov) - ALLOWED)
    if unknown:
        raise ValueError('refusing non-whitelisted ADT keys: %s' % ', '.join(unknown))
    applied = []
    for k in sorted(ov):
        namespace[k] = coerce(k, ov[k])
        applied.append(k)
    return applied
