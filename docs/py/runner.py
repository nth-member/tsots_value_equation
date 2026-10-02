"""Bridge between the page and shula_simulation.py.

The page passes Config fields as JSON; this coerces each value to the type the
Config field declares, runs the simulator unchanged, and returns its rows,
cohorts and criteria as JSON.
"""
import json
from dataclasses import asdict, fields, replace

from shula_simulation import Config, ShulaSimulation, compare_honest

TYPES = {f.name: f.type for f in fields(Config)}


def describe_json():
    """Field order, declared types and defaults, all read from Config."""
    return json.dumps(dict(order=list(TYPES), types=TYPES, defaults=asdict(Config())))


def coerce(name, value):
    declared = TYPES[name]
    if value is None:
        if 'None' not in declared:
            raise ValueError(f'{name} requires a value')
        return None
    if declared.startswith('bool'):
        return bool(value)
    if declared.startswith('float'):
        return float(value)
    if declared.startswith('int'):
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(f'{name} must be an integer')
        return int(value)
    return value


def run_json(settings_json):
    settings = json.loads(settings_json)
    honest = bool(settings.pop('compare_honest', False))
    unknown = set(settings) - set(TYPES)
    if unknown:
        raise ValueError('Unknown settings: ' + ', '.join(sorted(unknown)))
    config = Config(**{name: coerce(name, value) for name, value in settings.items()})
    result = ShulaSimulation(config).run()
    if honest:
        reference = ShulaSimulation(replace(config, honest_reference=True)).run()
        result.criteria['fabrication_less_rewarded'] = compare_honest(result, reference)
    return json.dumps(dict(config=asdict(config), criteria=result.criteria,
                           rows=result.rows, cohorts=result.cohorts),
                      sort_keys=True, allow_nan=False)
