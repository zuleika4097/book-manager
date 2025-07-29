from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_CACHE_DIR = "cache"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", env_nested_delimiter="__")

    book_id: int
    auth_token: str
    recaptcha_token: str

    page_width: int
    cache_dir: str = DEFAULT_CACHE_DIR
    task_concurrency: int = 50
