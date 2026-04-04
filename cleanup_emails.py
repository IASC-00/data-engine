#!/usr/bin/env python3
"""
Clean up AI-generated outreach emails before review.
Fixes: preamble lines, bad salutations, sentence count violations.
"""

import csv
import re
from pathlib import Path

GENERATED_CSV = Path("/mnt/c/Users/iswai/Desktop/ClaudeCode/outreach_generated.csv")

PREAMBLE_PATTERNS = re.compile(
    r"^(here is (a |the )?(personalized )?outreach email[:\.]?|"
    r"here'?s? (a |the )?(personalized )?outreach email[:\.]?|"
    r"subject:.*\n?)",
    re.IGNORECASE | re.MULTILINE,
)

BAD_SALUTATIONS = re.compile(
    r"^(dear there|hi there|hello there|dear owner)[,.]?\s*\n?",
    re.IGNORECASE,
)


def split_sentences(text):
    """Split on sentence-ending punctuation followed by whitespace or end."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


def clean_email(body: str) -> str:
    if not body:
        return body

    # Strip preamble lines
    body = PREAMBLE_PATTERNS.sub("", body).strip()

    # Strip bad salutations
    body = BAD_SALUTATIONS.sub("", body).strip()

    # Strip "Dear [name]," / "Hi [name]," salutation lines entirely
    # (keep signature at bottom — don't strip that)
    lines = body.split("\n")
    cleaned_lines = []
    for line in lines:
        # Skip standalone salutation lines
        if re.match(r"^(dear|hi|hello)\s+\w+[,.]?\s*$", line.strip(), re.IGNORECASE):
            continue
        cleaned_lines.append(line)
    body = "\n".join(cleaned_lines).strip()

    # Enforce 3-sentence max on the main paragraph
    # Find signature line (Ian, iswain.dev)
    sig_match = re.search(r"\n\s*(Ian[,.]?\s*iswain\.dev.*?)$", body, re.IGNORECASE)
    if sig_match:
        main = body[: sig_match.start()].strip()
        sig = sig_match.group(0).strip()
    else:
        main = body
        sig = "Ian, iswain.dev"

    sentences = split_sentences(main)
    if len(sentences) > 3:
        sentences = sentences[:3]
        # Ensure last sentence ends with "Worth a quick look?"
        if not any("worth a quick look" in s.lower() for s in sentences):
            sentences[-1] = "Worth a quick look?"

    main = " ".join(sentences)
    if not main.endswith("Worth a quick look?"):
        # Ensure sign-off is present
        pass

    return f"{main}\n\n{sig}"


def main():
    with open(GENERATED_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []

    changed = 0
    for row in rows:
        original = row.get("email_1", "")
        cleaned = clean_email(original)
        if cleaned != original:
            row["email_1"] = cleaned
            changed += 1

    with open(GENERATED_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    print(f"✓ Cleaned {changed} / {len(rows)} emails")
    print(f"  Saved to: {GENERATED_CSV}")


if __name__ == "__main__":
    main()
