import asyncio
import json
import os
import sys
import edge_tts

async def main():
    job_dir = sys.argv[1] if len(sys.argv) > 1 else "/data/jobs/test"

    input_file = os.path.join(job_dir, "script.json")
    output_file = os.path.join(job_dir, "voice.mp3")

    with open(input_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    narration = data.get("narration", "").strip()
    if not narration:
        raise ValueError("The narration field is empty")

    voice = os.environ.get("TTS_VOICE", "en-US-AriaNeural")

    communicate = edge_tts.Communicate(
        narration,
        voice,
        rate="-5%"
    )

    await communicate.save(output_file)
    print(f"Audio saved to: {output_file}")

if __name__ == "__main__":
    asyncio.run(main())