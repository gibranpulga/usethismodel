"""Trigger only UseThisModel with a private deploy-only Coolify credential."""
import json
import os
import stat
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

APP = os.environ.get('COOLIFY_APP_ID')


def trigger(credential_path):
    if not APP:
        raise ValueError('COOLIFY_APP_ID must be configured in the private deployment environment')
    path = Path(credential_path)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise ValueError('Deployment credential must be mode 0600')
    token = json.loads(path.read_text())['token']
    request = Request('http://127.0.0.1:8000/api/v1/deploy', method='POST',
                      data=json.dumps({'uuid': APP, 'force': False}).encode(),
                      headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Accept': 'application/json'})
    with urlopen(request, timeout=45) as response:
        result = json.load(response)
    deployments = result.get('deployments', [])
    if not deployments or not deployments[0].get('deployment_uuid'):
        raise RuntimeError('Coolify did not acknowledge deployment')
    return deployments[0]['deployment_uuid']


def verify_health(base_url=None, timeout=600, interval=10, warmup=30, stable_polls=3,
                  expected_snapshot_digest=None):
    """Wait for both liveness and readiness after deployment, or fail clearly."""
    base = (base_url or __import__('os').environ.get('DEPLOY_HEALTHCHECK_URL', 'https://usethismodel.com')).rstrip('/')
    deadline = time.monotonic() + timeout
    last = 'no successful health response'
    if warmup:
        time.sleep(min(warmup, timeout))
    healthy_streak = 0
    while time.monotonic() < deadline:
        states = []
        for path in ('/health', '/health/readiness'):
            try:
                request = Request(base + path, headers={'Accept': 'application/json', 'Cache-Control': 'no-cache'})
                with urlopen(request, timeout=min(10, max(1, timeout))) as response:
                    payload = json.load(response)
                    healthy = response.status == 200 and payload.get('status') == 'ok'
                    if path == '/health' and expected_snapshot_digest:
                        healthy = healthy and payload.get('catalog_snapshot_digest') == expected_snapshot_digest
                        if not healthy:
                            last = 'deployed catalog snapshot digest does not match the published snapshot'
                    states.append(healthy)
                    if not states[-1] and (response.status != 200 or payload.get('status') != 'ok'):
                        last = f'{path} returned status={payload.get("status", "unknown")}'
            except (URLError, HTTPError, TimeoutError, ValueError) as error:
                states.append(False)
                last = f'{path} unavailable ({type(error).__name__})'
        if all(states):
            healthy_streak += 1
            if healthy_streak >= stable_polls:
                return {'base_url': base, 'health': 'ok', 'readiness': 'ok', 'stable_polls': healthy_streak}
        else:
            healthy_streak = 0
        time.sleep(interval)
    raise RuntimeError(f'Deployment did not become healthy at {base} within {timeout}s: {last}. Inspect Coolify deployment logs and /health/readiness actions.')
