from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator, Field
from typing import List, Union

BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    bot_token: str = Field(..., validation_alias="BOT_TOKEN")
    admin_ids: List[int] = Field(..., validation_alias="ADMIN_IDS")
    manager_group_id: int = Field(..., validation_alias="MANAGER_GROUP_ID")
    db_url: str = Field(..., validation_alias="DB_URL")

    @field_validator("admin_ids", mode="before")
    def parse_admin_ids(cls, v: Union[int, str, List[int]]) -> List[int]:
        if isinstance(v, int):
            return [v]
        if isinstance(v, str):
            return [int(i.strip()) for i in v.split(",") if i.strip()]
        return v

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()  # type: ignore