"""Synthetic timed transcripts for clip-finder tests."""

OPENERS = (
    "Why do cities flood every spring?",
    "Here is the simple truth about water.",
    "And then the river came back.",
    "You can measure it yourself with a bucket.",
    "Three numbers explain the whole problem.",
    "It was raining for weeks.",
    "So the town built a wall.",
    "The wall made things worse for everyone downstream.",
)
BODY = (
    "Engineers walked the banks and counted every drain.",
    "The old maps showed streams that nobody remembered.",
    "People had paved over the places where water used to rest.",
    "When the ground cannot drink the water runs to the lowest street.",
    "A park can hold more water than a pipe twice its size.",
    "The council listened and changed the plan.",
    "Now the meadow floods and the houses stay dry.",
)


def talk(minutes=12, word=0.3, inner=0.08, between=0.6, punctuated=True):
    """Words of a talk of about ``minutes``; returns (words, sentences, duration)."""
    words, sentences, time, index = [], [], 0.5, 0
    limit = minutes * 60 - 2
    while time < limit:
        if index % 4 == 0:
            text = OPENERS[(index // 4) % len(OPENERS)]
        else:
            text = BODY[index % len(BODY)]
        tokens = text.split()
        if not punctuated:
            tokens = [t.strip(".?!,").lower() for t in tokens]
        first = len(words)
        for token in tokens:
            words.append(
                {
                    "id": len(words),
                    "start": round(time, 3),
                    "end": round(time + word, 3),
                    "text": token,
                    "probability": 0.9,
                }
            )
            time += word + inner
        time += between - inner
        sentences.append((first, len(words) - 1))
        index += 1
    return words, sentences, round(time + 1.0, 3)


def transcript(words):
    return {
        "language": "en",
        "engine": "synthetic-fixture",
        "status": "ok",
        "text": " ".join(w["text"] for w in words),
        "words": words,
    }
