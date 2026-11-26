"""Analyze captured proc/cgroup samples offline; never contact a running service."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

UNKNOWN = 'UNKNOWN'


def number(value: Any) -> bool:
    try:
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and value >= 0)
    except OverflowError:
        return False


def identity(p: dict[str, Any]) -> bool:
    return (isinstance(p.get('boot'), str) and bool(p['boot'].strip())
            and type(p.get('pid')) is int and p['pid'] > 0
            and type(p.get('start')) is int and p['start'] >= 0)


def interval(old: dict[str, Any], new: dict[str, Any]) -> float | None:
    """CPU percent of one core, only across the same known process identity."""
    if not identity(old) or not identity(new):
        return None
    if any(old.get(k) != new.get(k) for k in ('boot', 'pid', 'start', 'version')):
        return None
    return rate(old.get('cpu'), new.get('cpu'), old.get('mono'), new.get('mono'), 100)


def rate(a: Any, b: Any, t0: Any, t1: Any, scale: float = 1) -> float | None:
    if not all(number(v) for v in (a, b, t0, t1)) or t1 <= t0 or b < a:
        return None
    return scale * (b - a) / (t1 - t0)


def percentile(values: list[float], q: float) -> float | None:
    if not 0 < q <= 1:
        raise ValueError('q must be in (0, 1]')
    values = sorted(v for v in values if number(v))
    return values[math.ceil(q * len(values)) - 1] if values else None


def stats(values: list[Any]) -> dict[str, Any]:
    valid = [v for v in values if number(v)]
    return {'n': len(valid), 'unknown': len(values) - len(valid),
            'min': min(valid) if valid else None, 'p95': percentile(valid, .95),
            'max': max(valid) if valid else None,
            'sample_mean': sum(valid) / len(valid) if valid else None}


def get(row: dict[str, Any], *keys: str) -> Any:
    value: Any = row
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def nested_structure_valid(row: dict[str, Any]) -> bool:
    """Reject wrong container shapes; null oneshot process/cgroup remains legitimate."""
    roles = row.get('roles', {})
    if not isinstance(roles, dict):
        return False
    for role in roles.values():
        if not isinstance(role, dict):
            return False
        if any(role.get(key) is not None and not isinstance(role[key], dict)
               for key in ('process', 'cgroup')):
            return False
    for key in ('host', 'trendradar', 'observer'):
        value = row.get(key)
        if value is not None and not isinstance(value, dict):
            return False
    return True


def digest(path: Path) -> dict[str, Any]:
    body = path.read_bytes()
    return {'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}


def timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def journal(path: Path | None) -> dict[str, Any]:
    """Export fixed event categories, never raw journal messages."""
    result: dict[str, Any] = {'roles': {}, 'ledger': [], 'rounds': []}
    if path is None:
        return result
    events = json.loads(path.read_text(encoding='utf-8-sig')).get('events', {})
    for role, entries in events.items():
        counts: Counter[str] = Counter()
        pending = None
        for event in sorted(entries, key=lambda e: e.get('at', '')):
            msg = event.get('message', '')
            category = None
            if msg.startswith(('Starting ', 'Started ')):
                category = 'started'
                if pending:
                    pending['reason'] = 'completion_not_captured_before_next_start'
                    result['rounds'].append(pending)
                pending = {'role': role, 'start': event.get('at'), 'outcome': UNKNOWN}
            elif 'skipped because' in msg:
                category = 'skipped'
                if pending:
                    pending['outcome'] = 'skipped'
            elif msg.startswith('Finished '):
                category = 'completed'
                if pending:
                    pending['end'] = event.get('at')
                    if pending['outcome'] != 'skipped':
                        pending['outcome'] = 'service_completed_execution_unknown'
                    start, end = timestamp(pending['start']), timestamp(pending['end'])
                    pending['wall_seconds'] = (end - start).total_seconds() if start and end else None
                    result['rounds'].append(pending)
                    pending = None
            elif 'Main process exited' in msg:
                category = 'exited'
            elif 'Scheduled restart' in msg:
                category = 'restart_scheduled'
            elif 'runner unavailable' in msg:
                category = 'runner_unavailable'
            if category:
                counts[category] += 1
                result['ledger'].append({'role': role, 'at': event.get('at'), 'category': category})
            if 'Consumed ' in msg and result['rounds']:
                match = re.search(r'Consumed (?:(\d+)h )?(?:(\d+)min )?([\d.]+)s CPU time', msg)
                last = result['rounds'][-1]
                if match and last['role'] == role:
                    last['cpu_seconds'] = (int(match[1] or 0) * 3600
                                           + int(match[2] or 0) * 60 + float(match[3]))
        if pending:
            result['rounds'].append(pending)
        result['roles'][role] = dict(counts)
    return result


def analyze(
    samples_dir: Path, events_file: Path | None = None, version: str | None = None,
) -> dict[str, Any]:
    samples_dir = Path(samples_dir)
    paths = sorted(samples_dir.glob('samples.jsonl*'))
    hashes = {p.name: digest(p) for p in paths}
    for name in ('live-status.json', 'recent-health.json', 'analysis.json', 'analyze.py',
                 'files.sha256.json', 'REPORT.md'):
        path = samples_dir / name
        if path.is_file():
            hashes[name] = digest(path)
    if events_file:
        hashes[Path(events_file).name] = digest(Path(events_file))
    reasons: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    keyed: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    versions: Counter[str] = Counter()
    for path in paths:
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            counts['lines'] += 1
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('not an object')
            except ValueError:
                counts['malformed'] += 1
                continue
            versions[str(row.get('observer_version', UNKNOWN))] += 1
            if not number(row.get('monotonic')) or not timestamp(row.get('at')):
                reasons['missing_or_invalid_time'] += 1
                continue
            if not isinstance(row.get('boot_token'), str) or not row['boot_token'].strip():
                reasons['missing_boot_identity'] += 1
                continue
            if not isinstance(row.get('observer_version'), str) or not row['observer_version']:
                reasons['missing_version'] += 1
                continue
            if row.get('unit_probe_error'):
                reasons['unit_probe_error'] += 1
                continue
            if not nested_structure_valid(row):
                reasons['invalid_nested_structure'] += 1
                continue
            keyed[(row['observer_version'], row['boot_token'], row['monotonic'])].append(row)
    rows = []
    for candidates in keyed.values():
        unique = {json.dumps(r, sort_keys=True) for r in candidates}
        if len(unique) > 1:
            counts['conflict'] += 1
            reasons['conflicting_identity'] += len(candidates)
        else:
            counts['duplicate'] += len(candidates) - 1
            rows.append(candidates[0])
    rows.sort(key=lambda r: (timestamp(r['at']), r['monotonic']))
    chronology = rows
    if version is not None:
        rows = [r for r in chronology if r['observer_version'] == version]
        reasons['other_version'] += len(chronology) - len(rows)
    counts['valid'] = len(rows)
    counts['excluded'] = sum(reasons.values())
    page_size = None
    status_path = samples_dir / 'live-status.json'
    if status_path.exists():
        hashes[status_path.name] = digest(status_path)
        page_size = json.loads(status_path.read_text(encoding='utf-8-sig')).get('page_size_bytes')
        if not number(page_size) or page_size == 0:
            page_size = None
    boundaries = []
    gaps = []
    groups: dict[str, Any] = defaultdict(lambda: defaultdict(list))
    role_groups: dict[str, Any] = defaultdict(lambda: defaultdict(list))
    unknown_rates: Counter[str] = Counter()
    for old, new in pairwise(chronology):
        changed = [k for k in ('boot_token', 'observer_version') if old[k] != new[k]]
        if changed:
            boundaries.append({'at': new['at'], 'categories': changed})
            continue
        if version is not None and (old['observer_version'] != version
                                    or new['observer_version'] != version):
            continue
        dt = (timestamp(new['at']) - timestamp(old['at'])).total_seconds()
        gaps.append(dt)
        t0, t1 = old['monotonic'], new['monotonic']
        group = new.get('activity') if old.get('activity') == new.get('activity') else 'transition'
        group = group if isinstance(group, str) and group else UNKNOWN
        metrics = groups[group]
        specifications = {
            'cpu_percent': (('trendradar', 'cpu', 'usage_usec'), .0001),
            'observer_cpu_percent': (('observer', 'cpu', 'usage_usec'), .0001),
            'memory_high_per_second': (('trendradar', 'events', 'high'), 1),
            'major_faults_per_second': (('host', 'vmstat', 'pgmajfault'), 1),
            'swap_in_bytes_per_second': (('host', 'vmstat', 'pswpin'), page_size),
            'swap_out_bytes_per_second': (('host', 'vmstat', 'pswpout'), page_size),
            'memory_pressure_some_fraction': (
                ('trendradar', 'memory_pressure', 'some', 'total'), .000001),
        }
        # A reset of the shared cgroup CPU counter invalidates all shared counter deltas.
        global_reset = (number(get(old, 'trendradar', 'cpu', 'usage_usec'))
                        and number(get(new, 'trendradar', 'cpu', 'usage_usec'))
                        and get(new, 'trendradar', 'cpu', 'usage_usec')
                        < get(old, 'trendradar', 'cpu', 'usage_usec'))
        if global_reset:
            boundaries.append({'at': new['at'], 'categories': ['cgroup_counter_reset']})
        for name, (keys, scale) in specifications.items():
            value = (rate(get(old, *keys), get(new, *keys), t0, t1, scale)
                     if scale is not None and not global_reset else None)
            metrics[name].append(value)
            if value is None:
                unknown_rates[name] += 1
        for role in sorted(set(old.get('roles', {})) | set(new.get('roles', {}))):
            points = []
            for row in (old, new):
                proc = get(row, 'roles', role, 'process') or {}
                user, system = proc.get('user_cpu_seconds'), proc.get('system_cpu_seconds')
                points.append({'boot': row['boot_token'], 'pid': proc.get('pid'),
                               'start': proc.get('start_ticks'), 'mono': row['monotonic'],
                               'version': row['observer_version'],
                               'cpu': user + system if number(user) and number(system) else None})
            role_groups[group][role].append(interval(*points))
            if points[0]['pid'] != points[1]['pid'] or points[0]['start'] != points[1]['start']:
                boundaries.append({'at': new['at'], 'categories': ['process_identity_change'],
                                   'role': role})
        ticks0, ticks1 = get(old, 'host', 'cpu_ticks'), get(new, 'host', 'cpu_ticks')
        steal = None
        if (isinstance(ticks0, list) and isinstance(ticks1, list)
                and len(ticks0) >= 8 and len(ticks1) == len(ticks0)
                and all(number(v) for v in ticks0 + ticks1)):
            deltas = [b - a for a, b in zip(ticks0[:8], ticks1[:8], strict=True)]
            if min(deltas) >= 0 and sum(deltas) > 0:
                steal = 100 * deltas[7] / sum(deltas)
        metrics['host_steal_percent'].append(steal)
    activity = {g: {k: stats(v) for k, v in metrics.items()} for g, metrics in groups.items()}
    for g, roles in role_groups.items():
        activity[g]['roles'] = {role: stats(values) for role, values in roles.items()}
    journal_data = journal(Path(events_file) if events_file else None)
    pressures = [get(r, 'trendradar', 'memory_pressure', 'some', 'avg10') for r in rows]
    known_pressure = [v for v in pressures if number(v)]
    pressure_samples = {
        'valid': len(known_pressure), 'unknown': len(pressures) - len(known_pressure),
        'any_stall': {'count': sum(v > 0 for v in known_pressure),
                      'fraction': (sum(v > 0 for v in known_pressure) / len(known_pressure)
                                   if known_pressure else None), 'condition': 'avg10 > 0'},
        'alert_threshold': {'count': sum(v >= 10 for v in known_pressure),
                            'fraction': (sum(v >= 10 for v in known_pressure) / len(known_pressure)
                                         if known_pressure else None),
                            'condition': 'avg10 >= 10'},
    }
    by_version = dict(Counter(r['observer_version'] for r in rows))
    gauges = {}
    for name, keys, scale in (
        ('swap_mib', ('trendradar', 'memory.swap.current'), 1048576),
        ('memory_mib', ('trendradar', 'memory.current'), 1048576),
        ('host_available_mib', ('host', 'memory_kib', 'MemAvailable'), 1024),
    ):
        gauges[name] = stats([get(r, *keys) / scale if number(get(r, *keys)) else None
                              for r in rows])
    role_memory = {}
    for role in sorted({role for r in rows for role in r.get('roles', {})}):
        role_memory[role] = stats([
            get(r, 'roles', role, 'process', 'VmRSS') / 1024
            if number(get(r, 'roles', role, 'process', 'VmRSS')) else None for r in rows])
    return {'gauges': gauges, 'role_rss_mib': role_memory, 'input_hashes': hashes, 'counts': dict(counts) | {
                'malformed': counts['malformed'], 'duplicate': counts['duplicate'],
                'conflict': counts['conflict'], 'excluded_reasons': dict(reasons)},
            'raw_versions': dict(versions), 'valid_versions': by_version,
            'first_sample': rows[0]['at'] if rows else None,
            'last_sample': rows[-1]['at'] if rows else None,
            'gaps_seconds': stats(gaps), 'gaps_over_90s': sum(v > 90 for v in gaps),
            'boundaries': boundaries, 'activity_metrics': activity,
            'unknown_counter_intervals': dict(unknown_rates),
            'pressure_fraction': (sum(v > 0 for v in known_pressure) / len(known_pressure)
                                  if known_pressure else None),
            'pressure_fraction_basis': 'valid samples with avg10 > 0; not time weighted',
            'pressure_samples': pressure_samples,
            'pressure_avg10_percent': stats(pressures), 'page_size_bytes': page_size or UNKNOWN,
            'request_latency_p95': UNKNOWN, 'journal': journal_data,
            'trigger_audit': {'effective_calendar': UNKNOWN, 'expected': UNKNOWN,
                              'missing_trigger_count': None, 'missing_trigger_rate': None,
                              'status': UNKNOWN,
                              'reason': 'historical effective timer calendar not captured',
                              'actual_attempts': {k: v.get('started', 0)
                                                  for k, v in journal_data['roles'].items()}}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples-dir', type=Path, required=True)
    parser.add_argument('--events-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', help='restrict analysis to one captured observer version')
    args = parser.parse_args()
    report = analyze(args.samples_dir, args.events_file, args.version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
                           + '\n', encoding='utf-8')
    args.output.with_suffix('.md').write_text(
        '# 历史采集资源基线\n\n'
        f'有效样本：{report["counts"]["valid"]}；'
        f'损坏行：{report["counts"]["malformed"]}。\n\n'
        f'采集窗口：{report["first_sample"]} 至 {report["last_sample"]}。\n\n'
        f'PSI some avg10>=10：{report["pressure_samples"]["alert_threshold"]["count"]}/'
        f'{report["pressure_samples"]["valid"]}；'
        f'任意停顿 avg10>0：{report["pressure_samples"]["any_stall"]["count"]}/'
        f'{report["pressure_samples"]["valid"]}。两者均按有效 PSI 样本为分母。\n\n'
        'sample_mean 是区间样本算术均值，不是按持续时间加权的物理平均速率。\n\n'
        '百分位采用 nearest-rank；活动切换区间单列 transition。缺失或重置计数不补零。\n\n'
        '实际触发和跳过以 journal 分类为准；有效历史 calendar 未保存，预期触发完整性 UNKNOWN。'
        '无请求延迟证据，P95 为 UNKNOWN。详细统计见同名 JSON。\n', encoding='utf-8')


if __name__ == '__main__':
    main()
