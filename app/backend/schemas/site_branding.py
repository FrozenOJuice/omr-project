from pydantic import BaseModel


class SiteBrandingResponse(BaseModel):
    logo_url: str
    is_custom_logo: bool
