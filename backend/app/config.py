from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "mysql+aiomysql://root:Mobigen_1234@localhost:3306/chat_demo"
    ollama_base_url: str = "http://localhost:11434"

    class Config:
        env_file = ".env"


settings = Settings()
