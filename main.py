import asyncio
import logging
import re
import os
import shutil
from asyncio import TaskGroup
from io import BytesIO

import pyppeteer
import pydantic
from pypdf import PdfWriter
from rich import print
from rich.panel import Panel
from rich.progress import track
from rich.prompt import Prompt
from rich.logging import RichHandler

from book_manager.config import Settings
from book_manager.provider import DataProvider, DataProviderError
from book_manager.render import page_render

FORMAT = "%(message)s"
logging.basicConfig(level="INFO", format=FORMAT, datefmt="[%X]", handlers=[RichHandler()])


def prompt_credentials():
    print(
        Panel(
            "Instructions for obtaining the tokens can be found " "[link=https://youtu.be/X4msqCulOYk]here[/link].",
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
        book_id=book_id,
        auth_token=auth_token,
        recaptcha_token=recaptcha_token,
    )


async def main():
    print(":books:[bold]Book Manager[/bold] starting...")

    try:
        config = Settings()
        print("[bold green]Config loaded from local .env file.[/bold green]")
    except pydantic.ValidationError:
        config = prompt_credentials()

    provider = DataProvider(
        auth_token=config.auth_token,
        recaptcha_token=config.recaptcha_token,
        width=config.page_width,
        cache_dir=config.cache_dir,
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

    try:
        chapters = await provider.fetch_contents(book_id=config.book_id)
    except DataProviderError as e:
        print(f"[bold red]Error[/bold red]: {e}")
        exit(1)

    file_name = re.sub(r"\W+|^(?=\d)", "_", metadata.title)
    book_chapter_cache_dir = os.path.join(os.path.abspath(config.cache_dir), str(config.book_id), "chapters")
    if not os.path.exists(book_chapter_cache_dir):
        os.makedirs(book_chapter_cache_dir)

    browser = await pyppeteer.launch(
        options={
            "headless": True,
            "autoClose": False,
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-web-security",
                "--webkit-print-color-adjust",
                "--disable-extensions",
            ],
        },
    )

    task_semaphore = asyncio.Semaphore(config.task_concurrency)
    writer = PdfWriter()
    pages = {}
    async with TaskGroup() as task_group:
        for chapter_no, chapter in track(chapters.items(), description="Converting to PDF..."):

            async def wrapper(_chapter_no, _chapter):
                page = await page_render(browser, _chapter_no, _chapter, book_chapter_cache_dir, metadata.format)
                pages[_chapter_no] = page
                task_semaphore.release()

            await task_semaphore.acquire()
            task_group.create_task(wrapper(chapter_no, chapter))

    await browser.close()

    for chapter_no, page in sorted(pages.items()):
        writer.append(BytesIO(page))

    writer.write(f"{file_name}.pdf")
    writer.close()
    shutil.rmtree(book_chapter_cache_dir)

    print("[bold]Done.[/bold]")


if __name__ == "__main__":
    asyncio.run(main())
