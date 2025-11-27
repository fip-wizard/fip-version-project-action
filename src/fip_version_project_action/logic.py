import json
import urllib.parse
import uuid

import httpx
import rdflib
import websocket

from . import schemas


VERSION_REPLY_PATH = 'c1248b82-0538-4780-a0b4-983f632b1615.1c3b8b33-d9b6-435d-a69e-498f09a51fca'
RDF_FIP_TYPE = rdflib.URIRef('https://w3id.org/fair/fip/terms/FAIR-Implementation-Profile')
RDF_VERSION = rdflib.URIRef('https://schema.org/version')


async def prepare_action(api_url: str, req: schemas.PrepareRequest) -> schemas.PrepareResponse:
    # Get questionnaire
    try:
        questionnaire_data = await _fetch_questionnaire(api_url, req.project_uuid, req.user_token)
    except httpx.HTTPError as e:
        return schemas.PrepareResponse(
            ok=False,
            message=f'Failed to fetch questionnaire: {str(e)}'
        )
    # Extract questionnaire version
    reply = questionnaire_data['replies'].get(VERSION_REPLY_PATH, {})
    questionnaire_version = reply.get('value', {}).get('value', None)
    # Get documents (with submissions)
    try:
        documents_data = await _fetch_documents(api_url, req.project_uuid, req.user_token)
    except httpx.HTTPError as e:
        return schemas.PrepareResponse(
            ok=False,
            message=f'Failed to fetch documents: {str(e)}'
        )
    documents = documents_data.get('_embedded', {}).get('documents', [])
    submitted_versions = []
    for document in documents:
        submissions = document.get('submissions', [])
        for submission in submissions:
            if submission.get('state', '') != 'DoneSubmissionState':
                continue
            submitted_versions.append(
                schemas.SubmittedVersion(
                    uri=submission.get('location', ''),
                    version=None,
                    submittedAt=submission.get('createdAt', None),
                )
            )
    await _find_fip_versions(submitted_versions)

    return schemas.PrepareResponse(
        ok=True,
        message='Action is ready',
        questionnaireVersion=questionnaire_version,
        submittedVersions=submitted_versions,
        debug=questionnaire_data,
    )


async def submit_version(api_url: str, req: schemas.VersionRequest) -> schemas.VersionResponse:
    try:
        event_uuid = await _update_version_via_websocket(
            api_url=api_url,
            project_uuid=req.project_uuid,
            user_token=req.user_token,
            version=req.version,
        )
        await _create_project_version(
            api_url=api_url,
            project_uuid=req.project_uuid,
            user_token=req.user_token,
            version=req.version,
            description=req.description,
            event_uuid=event_uuid,
        )
    except Exception as e:
        return schemas.VersionResponse(
            ok=False,
            message=f'Failed to submit version: {str(e)}'
        )
    return schemas.VersionResponse(
        ok=True,
        message=f'Version {req.version} submitted successfully'
    )


async def _fetch_questionnaire(api_url: str, project_uuid: str, user_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url=f'{api_url}/questionnaires/{project_uuid}/questionnaire',
            headers={
                'Authorization': f'Bearer {user_token}',
                'User-Agent': 'fip-version-project-action/0.1.0',
            },
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()


async def _fetch_documents(api_url: str, project_uuid: str, user_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url=f'{api_url}/questionnaires/{project_uuid}/documents',
            headers={
                'Authorization': f'Bearer {user_token}',
                'User-Agent': 'fip-version-project-action/0.1.0',
            },
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()


async def _find_fip_versions(submitted_versions: list[schemas.SubmittedVersion]):
    async with httpx.AsyncClient() as client:
        for submitted_version in submitted_versions:
            try:
                nanopub_rdf = await _fetch_fip_nanopublication(client, submitted_version.uri)
                version = extract_version(nanopub_rdf)
                if version:
                    submitted_version.version = version
            except httpx.HTTPError:
                continue


async def _fetch_fip_nanopublication(client: httpx.AsyncClient, uri: str) -> str:
    response = await client.get(
        url=uri,
        headers={
            'Accept': 'application/trig',
            'User-Agent': 'fip-version-project-action/0.1.0',
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.text


async def _get_websocket_url(api_url: str) -> str | None:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url=f'{api_url}/configs/bootstrap',
        )
        response.raise_for_status()
        return response.json().get('signalBridge', {}).get('webSocketUrl', None)


async def _create_project_version(*, api_url: str, project_uuid: str, user_token: str,
                                  event_uuid: str, version: str, description: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url=f'{api_url}/questionnaires/{project_uuid}/versions',
            headers={
                'Authorization': f'Bearer {user_token}',
                'User-Agent': 'fip-version-project-action/0.1.0',
            },
            json={
                'eventUuid': event_uuid,
                'name': version,
                'description': description,
            },
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()


async def _update_version_via_websocket(api_url: str, project_uuid: str, user_token: str, version: str) -> str:
    ws_url = await _get_websocket_url(api_url)
    ws_params = {
        'Authorization': f'Bearer {user_token}',
        'subscription': 'Questionnaire',
        'identifier': project_uuid,
    }
    if not ws_url:
        raise ValueError('WebSocket URL not found in FAIR Wizard config')
    url = f'{ws_url}?{urllib.parse.urlencode(ws_params)}'
    ws = websocket.create_connection(
        url,
        headers={
            'Origin': api_url.replace('wizard-api', 'wizard'),
            'User-Agent': 'python-websocket',
        },
    )
    ws.recv()
    event_uuid = str(uuid.uuid4())
    events = [
        {
            'type': 'SetContent_ClientQuestionnaireAction',
            'data': {
                'type': 'SetReplyEvent',
                'uuid': event_uuid,
                'path': VERSION_REPLY_PATH,
                'value': {
                    'type': 'StringReply',
                    'value': version,
                },
            },
        },
    ]
    for event in events:
        ws.send(json.dumps(event))
        ws.recv()
    ws.close()
    return event_uuid


def extract_version(nanopub_rdf: str) -> str | None:
    g = rdflib.ConjunctiveGraph()
    g.parse(data=nanopub_rdf, format='trig')
    for s in g.subjects(rdflib.RDF.type, RDF_FIP_TYPE):
        for o in g.objects(s, RDF_VERSION):
            return str(o)
    return None
