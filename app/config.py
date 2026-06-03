from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    lens_token: str = ""
    epo_key: str = ""
    epo_secret: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
