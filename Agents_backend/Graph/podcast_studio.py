import os
import time
from datetime import datetime
import random
from pathlib import Path
try:
    from google import genai
    from google.genai import types
except ImportError:
    try:
        import google.genai as genai
        from google.genai import types
    except ImportError:
        # Fallback for older SDK or specific environment masks
        genai = None
        types = None

from Graph.agents.utils import logger, _job, _emit

# ✅ FIX: Retry configuration for Gemini TTS (matches video.py).
# Gemini's TTS endpoint occasionally returns transient 500 errors.
# 3 attempts with exponential backoff is enough to survive most transient failures.
_TTS_MAX_ATTEMPTS = 5
_TTS_BACKOFF_BASE = 2
_PODCAST_VOICE = "Aoede"  # calm, warm voice — good for educational podcasts

# ============================================================================
# PODCAST AUDIO GENERATION
# ============================================================================

PODCAST_SYSTEM_PROMPT = """You are an engaging solo podcast host discussing a blog post topic.
Create a 2-3 minute audio clip naturally discussing the core ideas.
Make it conversational, educational, and natural-sounding. Include pauses like "hmm", "you know", "right".
Speak directly to the audience.

RULES:
- Talk for about 2-3 minutes.
- Tone: Educational but entertaining.
"""

def _get_gemini_client():
    """
    Lazy initialization of the Gemini client.
    Called at function runtime (not import time), ensuring
    load_dotenv() in main.py has already run before we read the env var.
    """
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def generate_podcast_audio(state: dict, output_path: str) -> bool:
    """
    Generate a conversational podcast audio from blog content using Gemini's native audio output.

    ✅ FIX: Added retry with exponential backoff (mirrors video.py).
    Gemini's TTS endpoint returns transient 500 errors that succeed on retry.
    Previously a bare try/except returned False immediately, aborting the
    podcast on what is almost always a recoverable API hiccup.

    Also added explicit speech_config with a named voice so audio output
    is consistent and controlled across runs.
    """
    gemini_client = _get_gemini_client()

    if not gemini_client:
        logger.warning("GOOGLE_API_KEY missing. Cannot generate podcast.")
        return False

    plan = state.get("plan")
    topic = state.get("topic", "the topic")

    # Build context from sections
    sections_summary = ""
    if plan and hasattr(plan, 'tasks'):
        sections_summary = "\n".join([f"- {task.title}" for task in plan.tasks])

    prompt = f"""Create an audio podcast discussing: "{plan.blog_title if plan else topic}"

Key sections to cover:
{sections_summary}

Target audience: {plan.audience if plan else "general"}
Tone: {plan.tone if plan else "conversational"}
"""

    for attempt in range(1, _TTS_MAX_ATTEMPTS + 1):
        try:
            logger.info(f"🎙️ Podcast TTS attempt {attempt}/{_TTS_MAX_ATTEMPTS} (voice: {_PODCAST_VOICE})...")

            response = gemini_client.models.generate_content(
                model='gemini-2.5-flash-preview-tts',
                contents=[prompt],
                config=types.GenerateContentConfig(
                    system_instruction=PODCAST_SYSTEM_PROMPT,
                    response_modalities=["AUDIO"],
                    # ✅ FIX: Explicit voice config — previously unset, so Gemini
                    # chose an arbitrary default voice on every run.
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=_PODCAST_VOICE
                            )
                        )
                    ),
                    temperature=0.7,
                )
            )

            audio_data = None
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if part.inline_data and part.inline_data.data:
                        audio_data = part.inline_data.data
                        break

            if audio_data:
                with open(output_path, "wb") as f:
                    f.write(audio_data)
                logger.info(f"   ✅ Podcast TTS succeeded on attempt {attempt}.")
                return True

            # Response came back but contained no audio — not worth retrying
            logger.error("Gemini returned a response but contained no audio data.")
            return False

        except Exception as e:
            if attempt < _TTS_MAX_ATTEMPTS:
                wait = (_TTS_BACKOFF_BASE ** attempt) + (random.random() * 2)
                logger.warning(
                    f"   ⚠️ Podcast TTS attempt {attempt} failed: {e}. "
                    f"Retrying in {wait:.1f}s..."
                )
                time.sleep(wait)
            else:
                logger.error(
                    f"   ❌ Podcast TTS failed after {_TTS_MAX_ATTEMPTS} attempts. "
                    f"Last error: {e}"
                )

    return False

# ============================================================================
# MAIN NODE
# ============================================================================

def podcast_node(state: dict) -> dict:
    """
    Generate podcast audio from blog content using Gemini 2.5 Flash.
    Returns: {"podcast_audio_path": str}
    """
    _emit(_job(state), "podcast_generator", "started", "Generating AI Podcast Audio via Gemini...")
    logger.info("--- 🎙️ PODCAST STATION (GEMINI) ---")
    
    # Setup
    blog_folder = state.get("blog_folder")
    if blog_folder:
        podcast_dir = Path(blog_folder) / "audio"
    else:
        podcast_dir = Path("generated_podcasts")
    podcast_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_path = podcast_dir / f"podcast_{timestamp}.wav"
    
    # Generate Audio
    logger.info(f"   ✍️ Synthesizing Podcast Audio...")
    success = generate_podcast_audio(state, str(final_path))
    
    if success:
        logger.info(f"   ✅ Podcast saved to {final_path}")
        _emit(_job(state), "podcast_generator", "completed", "Podcast audio generated successfully.")
        return {"podcast_audio_path": str(final_path)}
    else:
        logger.error(f"   ❌ Podcast generation failed.")
        _emit(_job(state), "podcast_generator", "error", "Failed to generate podcast audio.")
        return {"podcast_audio_path": None}