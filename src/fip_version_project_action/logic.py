import asyncio
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
USER_AGENT = 'fip-version-project-action/0.1.0'
NANOPUB_TEMPLATE_PREFIX = 'dsw:nanopub-template:'


async def prepare_action(api_url: str, req: schemas.PrepareRequest) -> schemas.PrepareResponse:
    async with httpx.AsyncClient() as client:
        wizard = APIClient(
            api_url=api_url,
            user_token=req.user_token,
            client=client,
        )
        # Get questionnaire
        try:
            questionnaire_data = await wizard.fetch_questionnaire(req.project_uuid)
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
            documents_data = await wizard.fetch_documents(req.project_uuid)
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


async def _update_version_in_questionnaire(api_url: str, project_uuid: str, user_token: str,
                                           version: str, description: str):
    async with httpx.AsyncClient() as client:
        wizard = APIClient(
            api_url=api_url,
            user_token=user_token,
            client=client,
        )
        event_uuid = await wizard.update_version_via_websocket(
            project_uuid=project_uuid,
            version=version,
        )
        await wizard.create_project_version(
            project_uuid=project_uuid,
            version=version,
            description=description,
            event_uuid=event_uuid,
        )


async def save_version(api_url: str, req: schemas.VersionRequest) -> schemas.VersionSaveResponse:
    async with httpx.AsyncClient() as client:
        wizard = APIClient(
            api_url=api_url,
            user_token=req.user_token,
            client=client,
        )
        try:
            event_uuid = await wizard.update_version_via_websocket(
                project_uuid=req.project_uuid,
                version=req.version,
            )
            await wizard.create_project_version(
                project_uuid=req.project_uuid,
                version=req.version,
                description=req.description,
                event_uuid=event_uuid,
            )
        except Exception as e:
            return schemas.VersionSaveResponse(
                ok=False,
                message=f'Failed to submit version: {str(e)}'
            )
        return schemas.VersionSaveResponse(
            ok=True,
            message=f'Version {req.version} submitted successfully'
        )


async def submit_version(api_url: str, req: schemas.VersionRequest) -> schemas.VersionSubmitResponse:
    async with httpx.AsyncClient() as client:
        wizard = APIClient(
            api_url=api_url,
            user_token=req.user_token,
            client=client,
        )
        try:
            event_uuid = await wizard.update_version_via_websocket(
                project_uuid=req.project_uuid,
                version=req.version,
            )
            await wizard.create_project_version(
                project_uuid=req.project_uuid,
                version=req.version,
                description=req.description,
                event_uuid=event_uuid,
            )
            project = await wizard.fetch_questionnaire(
                project_uuid=req.project_uuid,
            )
            document_template_id, format_uuid = await wizard.get_document_template_and_format(
                project=project,
            )
            document_new = await wizard.create_document(
                project=project,
                document_template_id=document_template_id,
                format_uuid=format_uuid,
                version=req.version,
                event_uuid=event_uuid,
            )
            document_done = await wizard.wait_for_document(
                document=document_new,
            )
            if document_done.get('state', '') != 'DoneDocumentState':
                return schemas.VersionSubmitResponse(
                    ok=True,
                    message='Document could not be created',
                    documentDone=False,
                    documentUuid=document_done.get('uuid', None),
                )
            submission = await wizard.submit_document(
                document=document_done,
            )
            return schemas.VersionSubmitResponse(
                ok=True,
                message='Version submitted successfully',
                documentDone=True,
                documentUuid=document_done.get('uuid', None),
                submissionDone=submission.get('state', '') == 'DoneSubmissionState',
                submissionUuid=submission.get('uuid', None),
                submissionLocation=submission.get('location', None),
            )
        except Exception as e:
            return schemas.VersionSubmitResponse(
                ok=False,
                message=f'Failed to submit version due to error: {str(e)}'
            )


class APIClient:

    def __init__(self, api_url: str, user_token: str, client: httpx.AsyncClient):
        self.api_url = api_url
        self.user_token = user_token
        self.client = client
        self.client.headers.update({
            'Authorization': f'Bearer {user_token}',
            'User-Agent': USER_AGENT,
        })
        self.client.timeout = 10.0
        self.client.base_url = api_url.rstrip('/')

    async def fetch_questionnaire(self, project_uuid: str) -> dict:
        response = await self.client.get(
            url=f'/projects/{project_uuid}/questionnaire',
        )
        response.raise_for_status()
        return response.json()

    async def fetch_documents(self, project_uuid: str) -> dict:
        response = await self.client.get(
            url=f'/projects/{project_uuid}/documents',
        )
        response.raise_for_status()
        return response.json()

    async def get_websocket_url(self) -> str | None:
        response = await self.client.get(
            url='/configs/bootstrap',
            headers={
                'User-Agent': USER_AGENT,
            },
        )
        response.raise_for_status()
        return response.json().get('signalBridge', {}).get('webSocketUrl', None)

    async def create_project_version(self, project_uuid: str, event_uuid: str,
                                     version: str, description: str) -> dict:
        response = await self.client.post(
            url=f'/projects/{project_uuid}/versions',
            json={
                'eventUuid': event_uuid,
                'name': version,
                'description': description,
            },
        )
        response.raise_for_status()
        return response.json()

    async def get_document_template_and_format(self, project: dict) -> tuple[str, str]:
        km_package_id = project.get('knowledgeModelPackageId', '')
        response = await self.client.get(
            url='/document-templates/suggestions',
            params={
                'page': 0,
                'size': 20,
                'pkgId': km_package_id,
                'phase': 'ReleasedDocumentTemplatePhase',
            },
        )
        response.raise_for_status()
        for template in response.json().get('_embedded', {}).get('documentTemplates', []):
            template_id = template.get('id', '')
            if template_id.startswith(NANOPUB_TEMPLATE_PREFIX):
                format_uuid = ''
                for fmt in template.get('formats', []):
                    if fmt.get('name', '') == 'RDF TriG':
                        format_uuid = fmt.get('uuid', '')
                        break
                if not format_uuid:
                    continue
                return template_id, format_uuid
        raise ValueError('No suitable nanopublication document template found')

    async def create_document(self, *, project: dict, document_template_id: str,
                              format_uuid: str, version: str, event_uuid: str) -> dict:
        project_uuid = project.get('uuid', '')
        project_name = project.get('name', 'Unnamed Project')
        document_name = f'{project_name} (v{version})'
        response = await self.client.post(
            url='/documents',
            json={
                'name': document_name,
                'projectUuid': project_uuid,
                'documentTemplateId': document_template_id,
                'formatUuid': format_uuid,
                'projectEventUuid': event_uuid,
            },
        )
        response.raise_for_status()
        return response.json()

    async def submit_document(self, document: dict) -> dict:
        document_uuid = document.get('uuid', '')
        service_id = 'nanopub-test'
        response = await self.client.post(
            url=f'/documents/{document_uuid}/submissions',
            json={
                'serviceId': service_id,
            },
        )
        response.raise_for_status()
        return response.json()

    async def wait_for_document(self, document: dict) -> dict:
        project_uuid = document.get('project', {}).get('uuid', '')
        document_uuid = document.get('uuid', '')
        while True:
            response = await self.client.get(
                url=f'/projects/{project_uuid}/documents',
                params={
                    'page': 0,
                    'size': 20,
                    'sort': 'createdAt,desc',
                },
            )
            response.raise_for_status()
            document_data = None
            documents = response.json().get('_embedded', {}).get('documents', [])
            for doc in documents:
                if doc.get('uuid', '') == document_uuid:
                    document_data = doc
                    break
            if not document_data:
                raise ValueError('Document not found after creation')
            if document_data.get('state', '') in ('DoneDocumentState', 'ErrorDocumentState'):
                return document_data
            await asyncio.sleep(5.0)

    async def update_version_via_websocket(self, project_uuid: str, version: str) -> str:
        ws_url = await self.get_websocket_url()
        ws_params = {
            'Authorization': f'Bearer {self.user_token}',
            'subscription': 'Project',
            'identifier': project_uuid,
        }
        if not ws_url:
            raise ValueError('WebSocket URL not found in FAIR Wizard config')
        url = f'{ws_url}?{urllib.parse.urlencode(ws_params)}'
        ws = websocket.create_connection(
            url,
            headers={
                'Origin': self.api_url.replace('wizard-api', 'wizard'),
                'User-Agent': 'python-websocket',
            },
        )
        ws.recv()
        event_uuid = str(uuid.uuid4())
        events = [
            {
                'type': 'SetContent_ClientProjectMessage',
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


# Nanopublication network
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
            'User-Agent': USER_AGENT,
        },
        timeout=10.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def extract_version(nanopub_rdf: str) -> str | None:
    g = rdflib.ConjunctiveGraph()
    g.parse(data=nanopub_rdf, format='trig')
    for s in g.subjects(rdflib.RDF.type, RDF_FIP_TYPE):
        for o in g.objects(s, RDF_VERSION):
            return str(o)
    return None
