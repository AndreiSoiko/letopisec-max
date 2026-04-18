from bot.services.audio import get_audio_duration, convert_to_ogg, extract_audio_from_video, split_into_chunks
from bot.services.yandex_stt import transcribe_chunk
from bot.services.correction import correct_transcription
from bot.services.theses import extract_theses
from bot.services.protocol import extract_protocol
from bot.services.docx_builder import build_docx
