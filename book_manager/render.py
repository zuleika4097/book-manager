import os
import re

from pyppeteer.browser import Browser


EPUB_HORIZONTAL_MARGIN = 62
EPUB_VERTICAL_MARGIN = 56


def pre_render_content(contents: str):
    match = re.search(
        r'<img id="trigger" data-chapterid="[0-9]*?" src="" onerror="LoadChapter\(&apos;[0-9]*?&apos;\)" />',
        contents,
    )
    if match is not None:
        contents.replace(match.group(0), "")

    # Reveal hidden images
    hidden_images = re.findall("<img.*?>", contents, re.S)
    for img in hidden_images:
        img_new = img.replace("opacity: 0", "opacity: 1")
        img_new = img_new.replace("data-src", "src")
        contents = contents.replace(img, img_new)

    return contents


async def page_render(browser: Browser, chapter_no: int, chapter: str, cache_dir: str, format: str):
    page = await browser.newPage()
    await page.setUserAgent(
        r"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        r"(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
    )

    chapter = pre_render_content(chapter)
    with open(f"{cache_dir}/{chapter_no}.html", "w", encoding="utf-8") as f:
        f.write(chapter)
        os.fsync(f.fileno())

    await page.goto(
        f"file://{cache_dir}/{chapter_no}.html",
        {"waitUntil": ["load", "domcontentloaded", "networkidle0", "networkidle2"], "timeout": 0},
    )

    # Set PDF options
    options = {}
    match format:
        case "PDF":
            width, height = await page.evaluate(
                "() => { return [document.documentElement.offsetWidth + 1, document.documentElement.offsetHeight + 1]}"
            )
            options["width"] = width
            options["height"] = height
        case "EPUB":
            options["margin"] = {
                "top": str(EPUB_VERTICAL_MARGIN),
                "bottom": str(EPUB_VERTICAL_MARGIN),
                "left": str(EPUB_HORIZONTAL_MARGIN),
                "right": str(EPUB_HORIZONTAL_MARGIN),
            }

    document = await page.pdf(options)
    await page.close()
    return document
