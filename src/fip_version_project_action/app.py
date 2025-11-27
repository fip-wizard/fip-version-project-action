import pathlib

import fastapi
import fastapi.staticfiles
import fastapi.templating

from . import logic, schemas


ROOT_DIR = pathlib.Path(__file__).parent
TEMPLATES_DIR = ROOT_DIR / 'templates'
STATIC_DIR = ROOT_DIR / 'static'


def create_app(api_url: str | None = None, root_path: str | None = None) -> fastapi.FastAPI:
    root_path = root_path or ''
    api_url = api_url or 'https://fip.preview.fair-wizard.com/wizard-api'

    root_path = root_path.rstrip('/')
    api_url = api_url.rstrip('/')

    app = fastapi.FastAPI(
        title='fip-version-project-action',
        description='FIP Wizard Project Action to check and suggest FIP version',
        version='0.1.0',
    )
    app.mount('/static', fastapi.staticfiles.StaticFiles(directory=STATIC_DIR), name='static')
    templates = fastapi.templating.Jinja2Templates(directory=TEMPLATES_DIR)

    @app.get('/')
    async def read_root(request: fastapi.Request):
        return templates.TemplateResponse(
            name='action.html',
            request=request,
            context={
                'ROOT_PATH': root_path,
            },
        )

    @app.post('/api/prepare-action', response_model=schemas.PrepareResponse)
    async def prepare_action(req: schemas.PrepareRequest) -> schemas.PrepareResponse:
        return await logic.prepare_action(api_url, req)

    @app.post('/api/submit-version', response_model=schemas.VersionResponse)
    async def submit_version(req: schemas.VersionRequest) -> schemas.VersionResponse:
        return await logic.submit_version(api_url, req)

    return app
