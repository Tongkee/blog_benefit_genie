import re
import os

def clean_srt(filepath, outpath):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Remove WebVTT header if any
    content = re.sub(r"^WEBVTT\s*", "", content)

    # Split into blocks
    blocks = content.strip().split("\n\n")
    lines_out = []
    seen = set()

    for block in blocks:
        lines = block.split("\n")
        # Find lines that are not numbers and not timestamps
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.isdigit():
                continue
            if "-->" in line:
                continue
            # Remove XML-like tags like <c> or </c>
            line = re.sub(r"<[^>]+>", "", line)
            
            # Simple deduplication for scrolling subtitles
            if line not in seen:
                lines_out.append(line)
                seen.add(line)

    # Join lines and split into paragraphs based on pauses or just group them
    # Auto-subtitles are usually one long sentence, so let's join them with spaces.
    text = " ".join(lines_out)
    # Basic phrasing cleanups
    text = re.sub(r"\s+", " ", text).strip()

    with open(outpath, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Cleaned {filepath} -> {outpath}")

if __name__ == "__main__":
    for filename in os.listdir("."):
        if filename.endswith(".srt"):
            clean_srt(filename, filename.replace(".ko.srt", ".txt"))
