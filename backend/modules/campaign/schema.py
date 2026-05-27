from pydantic import BaseModel


class CreateCampaign(BaseModel):
    name: str

    
class ActivateCampaign(BaseModel):
    campaign_id: str