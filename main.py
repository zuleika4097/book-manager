import asyncio

import pydantic
from rich import print
from rich.panel import Panel
from rich.prompt import Prompt

from book_manager.config import Settings
from book_manager.provider import DataProvider, DataProviderError


def prompt_credentials():
    print(
        Panel(
            "Instructions for obtaining the tokens can be found "
            "[link=https://youtu.be/X4msqCulOYk]here[/link].",
            title="Note",
            style="gray50",
        )
    )
    book_id = Prompt.ask("Enter your book ID")
    try:
        book_id = int(book_id)
    except ValueError:
        print("[bold red]Error[/bold red]: book ID must be a valid integer.")
        exit(1)

    auth_token = Prompt.ask("Enter your authentication token")
    recaptcha_token = Prompt.ask("Enter your recaptcha token")
    create_config = Prompt.ask(
        r"Do you want to create a config file?",
        choices=["yes", "no"],
    )
    if create_config == "yes":
        with open(".env", "w", encoding="utf-8") as config_file:
            config_file.writelines(
                [
                    f"BOOK_ID={book_id}\n",
                    f"AUTH_token={auth_token}\n",
                    f"RECAPTCHA_TOKEN={recaptcha_token}\n",
                ]
            )

    return Settings(
        book_id=book_id, auth_token=auth_token, recaptcha_token=recaptcha_token
    )


async def main():
    print(":books:[bold]Book Manager[/bold] starting...")

    try:
        config = Settings()
        print("[bold green]Config loaded from local .env file.[/bold green]")
    except pydantic.ValidationError:
        config = prompt_credentials()

    provider = DataProvider(
        auth_token=config.auth_token, recaptcha_token=config.recaptcha_token
    )

    try:
        metadata = await provider.get_metadata(config.book_id)
    except DataProviderError as e:
        print(f"[bold red]Error[/bold red]: {e}")
        exit(1)

    response = Prompt.ask(
        f"Do you want to download [italic]{metadata.title} by {metadata.author}[/italic]?",
        choices=["yes", "no"],
    )

    if response == "no":
        exit(1)

    print(metadata)


if __name__ == "__main__":
    asyncio.run(main())
