"""Trigger only UseThisModel with a private deploy-only Coolify credential."""
import json
import stat
from pathlib import Path
from urllib.request import Request, urlopen

APP = 'ild8duzk51xnfcuyxtyclzpg'


def trigger(credential_path):
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
