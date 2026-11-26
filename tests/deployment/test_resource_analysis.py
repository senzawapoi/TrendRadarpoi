import json
import math
import subprocess
import sys

import pytest

from scripts.ops.resource_analysis import analyze, interval, percentile


def point(**changes):
    return dict(boot='b', pid=1, start=10, mono=1.0, cpu=9.0, version='v', **changes)


def sample(mono=1, cpu=9, activity='idle', **changes):
    row = {'at': f'2026-11-11T00:{int(mono)//60:02}:00+00:00',
           'monotonic': mono, 'boot_token': 'b', 'observer_version': 'v',
           'activity': activity, 'unit_probe_error': None,
           'trendradar': {'cpu': {'usage_usec': cpu * 1000000}},
           'roles': {'worker': {'process': {'pid': 1, 'start_ticks': 10,
                                          'user_cpu_seconds': cpu,
                                          'system_cpu_seconds': 0}}}}
    row.update(changes)
    return row


def fixture(tmp_path, rows, tail=''):
    (tmp_path / 'samples.jsonl').write_text(
        ''.join(json.dumps(r) + '\n' for r in rows) + tail, encoding='utf-8')
    return tmp_path


@pytest.mark.parametrize('changes', [
    {'pid': 2, 'start': 20, 'mono': 61, 'cpu': 1},
    {'mono': 61, 'cpu': 8}, {'boot': 'c'}, {'boot': ''}, {'pid': None},
    {'pid': True}, {'start': -1}, {'version': 'w'}, {'mono': math.nan},
    {'cpu': math.inf}, {'cpu': -1}, {'cpu': True}, {'mono': -1},
])
def test_interval_rejects_unknown_or_reset(changes):
    old = point()
    new = old | changes
    assert interval(old, new) is None


def test_interval_recomputes_cpu():
    assert interval(point(), point() | {'mono': 61, 'cpu': 39}) == 50


def test_percentile_nearest_rank_and_empty():
    assert percentile(list(range(1, 21)), .95) == 19
    assert percentile([], .95) is None
    with pytest.raises(ValueError):
        percentile([1], 0)


def test_malformed_unsorted_duplicate_conflict(tmp_path):
    a, b = sample(), sample(61, 39)
    result = analyze(fixture(tmp_path, [b, a, a, b | {'activity': 'other'}], '{bad'))
    assert result['counts']['malformed'] == 1
    assert result['counts']['duplicate'] == 1
    assert result['counts']['conflict'] == 1
    assert result['counts']['valid'] == 1
    assert result['counts']['excluded_reasons']['conflicting_identity'] == 2


def test_transition_is_not_stable_group(tmp_path):
    result = analyze(fixture(tmp_path, [sample(), sample(61, 39, 'collect')]))
    assert result['activity_metrics']['transition']['cpu_percent']['p95'] == 50
    assert result['request_latency_p95'] == 'UNKNOWN'
    assert result['trigger_audit']['expected'] == 'UNKNOWN'


def test_missing_identity_and_probe_error_exclude_not_zero(tmp_path):
    rows = [sample(), sample(61, 39, unit_probe_error='failure'),
            sample(121, 69, boot_token=None)]
    result = analyze(fixture(tmp_path, rows))
    assert result['counts']['valid'] == 1
    assert result['counts']['excluded'] == 2
    assert result['activity_metrics'] == {}


def test_counter_reset_and_process_restart_unknown(tmp_path):
    a, b = sample(), sample(61, 8)
    b['roles']['worker']['process']['pid'] = 2
    result = analyze(fixture(tmp_path, [a, b]))
    assert result['activity_metrics']['idle']['cpu_percent']['p95'] is None
    assert result['activity_metrics']['idle']['roles']['worker']['p95'] is None
    assert result['boundaries']


def test_utf8_cli_and_input_digests(tmp_path):
    inputs = fixture(tmp_path, [sample(), sample(61, 39)])
    events = tmp_path / 'events.json'
    events.write_text('{"events": {}}', encoding='utf-8')
    out = tmp_path / 'result.json'
    subprocess.run([sys.executable, '-B', '-m', 'scripts.ops.resource_analysis',
                    '--samples-dir', str(inputs), '--events-file', str(events),
                    '--output', str(out)], check=True)
    result = json.loads(out.read_text(encoding='utf-8'))
    assert result['input_hashes']['samples.jsonl']['bytes'] > 0
    assert '采集' in out.with_suffix('.md').read_text(encoding='utf-8')


def test_journal_skips_are_not_execution_baseline(tmp_path):
    fixture(tmp_path, [sample(), sample(61, 39)])
    events = tmp_path / 'events.json'
    events.write_text(json.dumps({'events': {'trendradar-collect-ai.service': [
        {'at': '2026-11-11T00:00:00+00:00', 'message': 'Starting AI'},
        {'at': '2026-11-11T00:00:10+00:00', 'message': 'skipped because lock is busy'},
        {'at': '2026-11-11T00:00:20+00:00', 'message': 'Finished AI'},
    ]}}), encoding='utf-8')
    result = analyze(tmp_path, events)
    assert result['journal']['roles']['trendradar-collect-ai.service']['skipped'] == 1
    assert result['journal']['rounds'][0]['outcome'] == 'skipped'
    assert result['trigger_audit']['effective_calendar'] == 'UNKNOWN'
def test_formal_version_filter_and_missing_version(tmp_path):
    a, b = sample(), sample(61, 39, observer_version='w')
    result = analyze(fixture(tmp_path, [a, b]), version='w')
    assert result['counts']['valid'] == 1
    assert result['counts']['excluded_reasons']['other_version'] == 1


def test_global_reset_invalidates_other_cgroup_deltas(tmp_path):
    a, b = sample(), sample(61, 8)
    a['trendradar']['events'] = {'high': 1}
    b['trendradar']['events'] = {'high': 50}
    result = analyze(fixture(tmp_path, [a, b]))
    assert result['activity_metrics']['idle']['memory_high_per_second']['p95'] is None


def test_observed_page_size_required_for_swap_bytes(tmp_path):
    a, b = sample(), sample(61, 39)
    a['host'] = {'vmstat': {'pswpin': 0}}
    b['host'] = {'vmstat': {'pswpin': 60}}
    fixture(tmp_path, [a, b])
    assert analyze(tmp_path)['activity_metrics']['idle']['swap_in_bytes_per_second']['p95'] is None
    (tmp_path / 'live-status.json').write_text('{"page_size_bytes": 8192}')
    assert analyze(tmp_path)['activity_metrics']['idle']['swap_in_bytes_per_second']['p95'] == 8192
def test_sample_gauges_preserve_missing_values_and_input_hashes(tmp_path):
    a, b = sample(), sample(61, 39)
    a['trendradar']['memory.swap.current'] = 1048576
    fixture(tmp_path, [a, b])
    (tmp_path / 'REPORT.md').write_text('original damaged report')
    result = analyze(tmp_path)
    assert result['gauges']['swap_mib']['sample_mean'] == 1
    assert result['gauges']['swap_mib']['unknown'] == 1
    assert 'REPORT.md' in result['input_hashes']

def test_sort_uses_instant_not_iso_offset_lexicographic_order(tmp_path):
    a = sample(at='2026-11-11T08:00:00+08:00')
    b = sample(61, 39, at='2026-11-11T00:01:00+00:00')
    result = analyze(fixture(tmp_path, [b, a]))
    assert result['activity_metrics']['idle']['cpu_percent']['p95'] == 50
    assert result['gaps_seconds']['min'] == 60

def test_pressure_threshold_and_any_stall_have_distinct_denominators(tmp_path):
    rows = [sample(), sample(61, 39), sample(121, 69), sample(181, 99)]
    for row, value in zip(rows, [0, 1, 10, None], strict=True):
        row['trendradar']['memory_pressure'] = {'some': {'avg10': value}}
    result = analyze(fixture(tmp_path, rows))
    assert result['pressure_samples'] == {
        'valid': 3, 'unknown': 1,
        'any_stall': {'count': 2, 'fraction': 2 / 3, 'condition': 'avg10 > 0'},
        'alert_threshold': {'count': 1, 'fraction': 1 / 3, 'condition': 'avg10 >= 10'},
    }


@pytest.mark.parametrize('nested', [
    {'roles': None}, {'roles': {'worker': {'process': 'bad'}}},
    {'roles': {'worker': []}}, {'host': []}, {'trendradar': 'bad'},
    {'roles': {'worker': {'cgroup': []}}},
])
def test_invalid_nested_shapes_excluded_with_reason(tmp_path, nested):
    result = analyze(fixture(tmp_path, [sample(), sample(61, 39, **nested)]))
    assert result['counts']['valid'] == 1
    assert result['counts']['excluded_reasons']['invalid_nested_structure'] == 1
    assert result['activity_metrics'] == {}


def test_absent_oneshot_process_is_unknown_not_invalid_sample(tmp_path):
    a, b = sample(), sample(61, 39)
    a['roles']['oneshot'] = {'process': None, 'cgroup': None}
    b['roles']['oneshot'] = {'process': None, 'cgroup': None}
    result = analyze(fixture(tmp_path, [a, b]))
    assert result['counts']['valid'] == 2
    assert result['activity_metrics']['idle']['roles']['oneshot']['n'] == 0
    assert result['activity_metrics']['idle']['roles']['oneshot']['unknown'] == 1


def test_missing_trigger_metrics_explicitly_unknown(tmp_path):
    audit = analyze(fixture(tmp_path, [sample()]))['trigger_audit']
    assert audit['missing_trigger_count'] is None
    assert audit['missing_trigger_rate'] is None
    assert audit['status'] == 'UNKNOWN'
    assert audit['reason']

def test_version_filter_preserves_intervening_version_boundaries(tmp_path):
    rows = [sample(0, 0), sample(60, 60, observer_version='w'), sample(120, 120)]
    result = analyze(fixture(tmp_path, rows), version='v')
    assert result['counts']['valid'] == 2
    assert result['counts']['excluded_reasons']['other_version'] == 1
    assert result['activity_metrics'] == {}
    assert len(result['boundaries']) == 2
    assert all('observer_version' in b['categories'] for b in result['boundaries'])


def test_pending_journal_round_retained_before_next_start(tmp_path):
    fixture(tmp_path, [sample()])
    events = tmp_path / 'events.json'
    events.write_text(json.dumps({'events': {'worker': [
        {'at': '2026-11-11T00:00:00+00:00', 'message': 'Started worker'},
        {'at': '2026-11-11T00:01:00+00:00', 'message': 'Started worker'},
    ]}}), encoding='utf-8')
    rounds = analyze(tmp_path, events)['journal']['rounds']
    assert len(rounds) == 2
    assert rounds[0]['outcome'] == 'UNKNOWN'
    assert rounds[0]['reason'] == 'completion_not_captured_before_next_start'


def test_rate_statistics_explicit_sample_mean_not_physical_average(tmp_path):
    result = analyze(fixture(tmp_path, [sample(0, 0), sample(1, 1), sample(100, 1)]))
    cpu = result['activity_metrics']['idle']['cpu_percent']
    assert cpu['sample_mean'] == 50
    assert 'mean' not in cpu


def test_extreme_integer_counter_is_unknown_not_overflow(tmp_path):
    assert interval(point(), point() | {'mono': 61, 'cpu': 10**400}) is None
    result = analyze(fixture(tmp_path, [sample(), sample(61, 10**400)]))
    assert result['activity_metrics']['idle']['cpu_percent']['p95'] is None
