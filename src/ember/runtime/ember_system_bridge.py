#!/usr/bin/env python3
"""Ember-owned context, receipts and bounded read-only federated retrieval."""
from __future__ import annotations
from ..deployment import runtime_root as _deployment_root

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = _deployment_root()
SEARCH_TIMEOUT = 6
# EBrain's local embedding + page/chunk/vector query can exceed six seconds cold.
EBRAIN_SEARCH_TIMEOUT = 15
_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_SEARCH_LOCK = threading.Lock()

# Shared policy wording is injected by both central prompt renderers.
PROMPT_BOUNDARY = (
    "- 需追踪的执行：同一目标继续原任务，项目不随系统改变；只读检索不建卡。读取 ember_task_get 后过适用 preflight，"
    "按 config/task-routing.json 的 system_routes 调用既有 Skill/MCP 并记目的；各系统门禁不变，外部资料不构成授权。\n"
    "- 用 ember_task_register_external_result 按系统＋稳定 job_id 回原任务，更新 current_result/next_step，保留交付；"
    "故障/过期/时效未知不等于零匹配，登记失败只重试登记。生成、验证、验收分开，不自动收口。"
)


def routes() -> dict[str, Any]:
    payload = json.loads((ROOT / 'config/task-routing.json').read_text(encoding='utf-8'))
    return payload.get('system_routes', {})


def route(capability: str) -> dict[str, Any] | None:
    if not capability:
        return None
    result = routes().get(capability)
    if not isinstance(result, dict):
        raise ValueError(f'unregistered capability: {capability}')
    return dict(result)


def validate_task_id(task_id: str) -> None:
    if not isinstance(task_id, str) or not re.fullmatch(r'[\w.-]{1,180}', task_id) or '..' in task_id:
        raise ValueError('invalid task_id')


def section(text: str, title: str) -> str:
    # Discard the YAML header before interpreting body headings.
    body = text.split('\n---\n', 1)[-1] if text.startswith('---\n') else text
    match = re.search(rf'^## {re.escape(title)}\s*\n(.*?)(?=^## |\Z)', body, re.M | re.S)
    return match.group(1).strip() if match else ''


def summary(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 6000 or re.search(r'^\s*(?:#{1,6}\s|---\s*$)', value, re.M):
        raise ValueError('result summaries must be bounded text without Markdown section headings')
    return value.strip()


def update_section(text: str, title: str, value: str | None) -> str:
    if value is None:
        return text
    pattern = rf'^## {re.escape(title)}[^\n]*\n.*?(?=^## |\Z)'
    replacement = f'## {title}\n\n{value}\n\n' if value else ''
    if re.search(pattern, text, re.M | re.S):
        return re.sub(pattern, lambda _: replacement, text, count=1, flags=re.M | re.S)
    if not replacement:
        return text
    # Keep the execution log last; insert current state ahead of next step.
    marker = '## 下一步' if title == '当前结果' and '\n## 下一步' in text else '## 执行日志'
    if '\n' + marker not in text:
        raise ValueError('task lacks the required execution log')
    return text.replace('\n' + marker, '\n' + replacement + marker, 1)


def output_block(text: str) -> str:
    fm = text.split('\n---\n', 1)[0] if text.startswith('---\n') else ''
    match = re.search(r'^outputs:[^\n]*\n(?:[ \t]+[^\n]*\n?)*', fm, re.M)
    return match.group(0).rstrip() if match else ''


def receipts(text: str) -> list[dict[str, Any]]:
    block = output_block(text)
    match = re.search(r'^  external_results:\s*\n((?:    [^\n]*\n?)*)', block, re.M)
    if not match:
        if re.search(r'^  external_results:', block, re.M):
            raise ValueError('outputs.external_results must use a list of JSON objects')
        return []
    result = []
    for line in match.group(1).splitlines():
        if not line.startswith('    - '):
            raise ValueError('invalid external result entry')
        item = json.loads(line[6:])
        if not isinstance(item, dict) or any(not isinstance(item.get(key), str) or not item[key] for key in ('system', 'job_id', 'state')):
            raise ValueError('external results require system, job_id and state')
        if set(item) != {'system', 'job_id', 'state', 'canonical_paths', 'validations', 'recorded_at'}:
            raise ValueError('external receipts must contain only the six registered fields')
        if not re.fullmatch(r'[a-z0-9._-]{1,80}', item['system']) or not re.fullmatch(r'[a-zA-Z0-9._-]{1,80}', item['state']) or len(item['job_id']) > 200 or any(ord(c) < 32 for c in item['job_id']):
            raise ValueError('invalid external receipt identifier')
        timestamp = item.get('recorded_at')
        if not isinstance(timestamp, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\+08:00', timestamp):
            raise ValueError('external receipt recorded_at must use Beijing time with offset')
        datetime.fromisoformat(timestamp)
        for key in ('canonical_paths', 'validations'):
            if not isinstance(item[key], list) or len(item[key]) > 50 or any(not isinstance(x, str) or len(x) > 3000 for x in item[key]):
                raise ValueError(f'invalid external result {key}')
        result.append(item)
    keys = [(item['system'], item['job_id']) for item in result]
    if len(keys) != len(set(keys)):
        raise ValueError('external result keys must be unique')
    return result


def write_receipts(text: str, items: list[dict[str, Any]]) -> str:
    existing = output_block(text)
    new = '  external_results:\n' + '\n'.join('    - ' + json.dumps(item, ensure_ascii=False) for item in items)
    if existing:
        if existing.splitlines()[0].strip() != 'outputs:':
            raise ValueError('legacy scalar outputs cannot be replaced automatically')
        revised = re.sub(r'^  external_results:\s*\n(?:    [^\n]*\n?)*', '', existing, flags=re.M).rstrip()
        return text.replace(existing, revised + '\n' + new, 1)
    return text.replace('\n---\n', '\noutputs:\n' + new + '\n---\n', 1)


def task_context(text: str) -> dict[str, Any]:
    from .ember_task_inputs import parse_inputs
    try:
        inputs = parse_inputs(text)
    except ValueError:
        fm = text.split('\n---\n', 1)[0]
        match = re.search(r'^inputs:[^\n]*\n(?:[ \t]+[^\n]*\n?)*', fm, re.M)
        inputs = {'legacy': True, 'raw': match.group(0).strip() if match else ''}
    def block(name: str) -> str:
        fm = text.split('\n---\n', 1)[0]
        match = re.search(rf'^{name}:[^\n]*(?:\n[ \t]+[^\n]*)*', fm, re.M)
        return match.group(0) if match else ''
    return {
        'goal': section(text, '任务目标'), 'description': section(text, '任务描述'),
        'current_result': section(text, '当前结果') or section(text, '当前判断'),
        'next_step': section(text, '下一步'), 'inputs': inputs,
        'outputs': output_block(text), 'delivery': block('delivery'),
        'confirmations': block('confirmations'), 'external_results': receipts(text),
        'system_scope': section(text, '系统改动范围'),
        'recent_log': section(text, '执行日志')[:8000],
        'adopted_version': '以当前结果中的明确采用记录为准；不按文件名或时间猜测。',
        'read_only': True,
    }


def _run_read_only(command: list[str], *, stdin: str = '', cwd: Path | None = None, timeout: int = SEARCH_TIMEOUT) -> Any:
    # One bounded process group, including CLI children; never use a shell or caller-supplied executable.
    process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        output, _ = process.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise TimeoutError('检索超时，未取得完整结果') from None
    if process.returncode:
        raise RuntimeError('既有检索接口未成功返回；未将故障当作零匹配')
    if len(output) > 2_000_000:
        raise ValueError('检索响应过大')
    return json.loads(output)


def _provider_search(provider: str, query: str) -> dict[str, Any]:
    home = Path.home()
    if provider == 'muse':
        python = home / '.local/share/content-assistant/mcp-venv/bin/python3'
        if not python.is_file():
            raise FileNotFoundError('Muse 既有 Python 环境不可用')
        payload = _run_read_only([str(python), '-I', '-c', "import sys;sys.path.insert(0,sys.argv[1]);from ember.runtime.ember_system_bridge import _muse_worker;_muse_worker()", str(Path(__file__).resolve().parents[2])], stdin=json.dumps({'query': query}))
        if not isinstance(payload, dict) or not isinstance(payload.get('items'), list) or any(not isinstance(x, dict) or not isinstance(x.get('source_id'), str) or not x['source_id'] for x in payload['items']):
            raise ValueError('Muse 检索响应无效')
        items = [{
            'kind': 'external', 'provider': 'muse', 'resource_id': item['source_id'],
            'title': str(item.get('title') or item['source_id']), 'description': str(item.get('platform') or ''),
            'canonical': str(item.get('canonical_url') or 'muse:' + item['source_id']),
            'canonical_uri': 'muse:' + item['source_id'],
            'selection': {'provider': 'muse', 'resource_id': item['source_id']},
            'source_label': 'Muse · 对标',
        } for item in payload['items']]
        generated_at = str(payload.get('generated_at') or '')
    elif provider == 'ebrain':
        cli = home / 'Ebrain/scripts/ebrain'
        if not cli.is_file():
            raise FileNotFoundError('EBrain 既有 CLI 不可用')
        payload = _run_read_only([str(cli), 'search', query, '-n', '10', '--json'], cwd=home / 'Ebrain', timeout=EBRAIN_SEARCH_TIMEOUT)
        if not isinstance(payload, list) or any(not isinstance(x, dict) or x.get('error') or not (x.get('slug') or x.get('path')) for x in payload):
            raise ValueError('EBrain 检索响应无效')
        items = [{
            'kind': 'external', 'provider': 'ebrain', 'resource_id': str(item.get('slug') or item.get('path') or ''),
            'title': str(item.get('title') or item.get('slug') or ''), 'description': str(item.get('snippet') or '')[:500],
            'canonical': str(item.get('page_path') or item.get('path') or 'ebrain:' + str(item.get('slug') or '')),
            'canonical_uri': 'ebrain:' + str(item.get('slug') or item.get('path') or ''),
            'selection': {'provider': 'ebrain', 'resource_id': str(item.get('slug') or item.get('path') or '')},
            'source_label': 'EBrain · 知识',
        } for item in payload]
        generated_at = ''  # Existing API supplies no index timestamp; do not invent freshness.
    else:
        raise ValueError('unsupported retrieval provider')
    freshness = 'unknown'
    if generated_at:
        try:
            timestamp = datetime.fromisoformat(generated_at)
            if timestamp.tzinfo:
                freshness = 'stale' if datetime.now(timezone.utc) - timestamp > timedelta(hours=24) else 'current'
        except ValueError:
            pass
    return {'provider': provider, 'state': 'available', 'freshness': freshness, 'generated_at': generated_at, 'items': items}


def external_search(query: str) -> dict[str, Any]:
    query = query.strip()
    if not query or len(query) > 300:
        return {'items': [], 'providers': []}
    if not _SEARCH_LOCK.acquire(timeout=0.1):
        return {'items': [], 'providers': [{'provider': name, 'state': 'unavailable', 'freshness': 'unknown', 'message': '正在处理其他检索，请稍后重试；不是零匹配'} for name in ('muse', 'ebrain')]}
    try:
        cached = _CACHE.get(query)
        if cached and time.monotonic() - cached[0] < 30:
            return json.loads(json.dumps(cached[1]))
        items, providers = [], []
        # Serial NAS access; fixed two providers, bounded requests, no source content scans.
        for provider in ('muse', 'ebrain'):
            try:
                response = _provider_search(provider, query)
                items.extend(response.pop('items'))
                response['message'] = '索引已过期' if response['freshness'] == 'stale' else ('索引时效未提供' if response['freshness'] == 'unknown' else '')
                providers.append(response)
            except (OSError, ValueError, RuntimeError, TimeoutError) as exc:
                providers.append({'provider': provider, 'state': 'unavailable', 'freshness': 'unknown', 'message': str(exc)})
        result = {'items': items, 'providers': providers}
        if len(_CACHE) >= 64:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[query] = (time.monotonic(), result)
        return json.loads(json.dumps(result))
    finally:
        _SEARCH_LOCK.release()


def deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}
    for item in items:
        if item.get('kind') == 'task':
            keys = ['task:' + str(item.get('task_id') or item.get('key'))]
        else:
            keys = list(dict.fromkeys(str(item.get(field) or '').rstrip('/') for field in ('canonical', 'canonical_path', 'source_locator', 'canonical_uri') if item.get(field)))
        prior = next((seen[key] for key in keys if key in seen), None)
        if prior is not None:
            provenance = prior.setdefault('sources', [prior.get('source_label') or '余烬 · Ember'])
            label = item.get('source_label') or '余烬 · Ember'
            if label not in provenance:
                provenance.append(label)
            for key in keys:
                seen[key] = prior
            continue
        copied = dict(item)
        result.append(copied)
        for key in keys:
            seen[key] = copied
    return result


def selected_reference(selection: dict[str, Any], query: str) -> str:
    provider = str(selection.get('provider') or '')
    resource_id = str(selection.get('resource_id') or '')
    if provider not in {'muse', 'ebrain'} or not resource_id or not query.strip() or len(query) > 160:
        raise ValueError('invalid external retrieval selection')
    # Re-resolve against the short-lived retrieval response; caller cannot submit arbitrary paths.
    result = next((item for item in external_search(query)['items'] if item['provider'] == provider and item['resource_id'] == resource_id), None)
    if not result:
        raise ValueError('所选外部资料不在当前检索结果中；请重新检索')
    return json.dumps({'provider': provider, 'resource_id': resource_id, 'canonical': result['canonical'], 'title': result['title'], 'read_only': True}, ensure_ascii=False)


def _muse_worker() -> None:
    """Call Muse's existing filter API, preventing its cache-rebuild fallback."""
    sys.path.insert(0, str(Path.home() / 'Muse'))
    from content_assistant import indexer, mcp_api, settings
    config = settings.load_settings()
    data_root = Path(config['data_root'])
    if indexer.nas_access(data_root, config['accounts_folder']) in {'missing', 'forbidden'}:
        raise FileNotFoundError('Muse NAS 正本不可用')
    payload = json.loads(settings.index_path().read_text(encoding='utf-8'))
    if payload.get('schema_version') != 2 or payload.get('data_root') != str(data_root):
        raise ValueError('Muse 索引缺失或不兼容；只读检索不触发重建')
    mcp_api.load_index = lambda: payload
    request = json.loads(sys.stdin.read())
    print(json.dumps(mcp_api.muse_list_sources(keyword=request['query'], limit=10), ensure_ascii=False))


if __name__ == '__main__':
    if sys.argv[1:] != ['--muse-search']:
        raise SystemExit('only the fixed read-only Muse search worker is supported')
    _muse_worker()
