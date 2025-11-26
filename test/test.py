from hub import summarize

# Dummy transcript for testing
transcript = """
YouTube has become one of the biggest platforms for video content. Researchers use
transcripts to analyze educational and market trends. Manual transcript extraction is
inefficient, which is why APIs and ASR tools are used to automate and improve the process.
"""

# Get summary
summary = summarize(transcript)
print("Summary from Mistral:\n", summary)
