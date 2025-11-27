import pydantic


class PrepareRequest(pydantic.BaseModel):
    project_uuid: str = pydantic.Field(..., alias='projectUuid')
    user_token: str = pydantic.Field(..., alias='userToken')


class SubmittedVersion(pydantic.BaseModel):
    uri: str
    version: str | None = None
    submitted_at: str | None = pydantic.Field(default=None, alias='submittedAt')


class PrepareResponse(pydantic.BaseModel):
    ok: bool
    message: str | None = None
    questionnaire_version: str | None = pydantic.Field(default=None, alias='questionnaireVersion')
    submitted_versions: list = pydantic.Field(default_factory=list, alias='submittedVersions')
    debug: dict | None = None


class VersionRequest(pydantic.BaseModel):
    project_uuid: str = pydantic.Field(..., alias='projectUuid')
    user_token: str = pydantic.Field(..., alias='userToken')
    version: str
    description: str


class VersionResponse(pydantic.BaseModel):
    ok: bool
    message: str | None = None
