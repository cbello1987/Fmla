import pytest
from unittest.mock import patch

@patch('openai.Audio')
def test_voice_transcription_success(mock_audio, sample_voice_events):
    mock_audio.transcribe.return_value = {'text': sample_voice_events[0]['transcription']}
    from app import process_voice_message
    url = sample_voice_events[0]['audio_url']
    result = process_voice_message(url, "+15551234567", "corrid-1")
    assert "soccer" in result.lower()

@patch('openai.Audio')
def test_voice_transcription_failure(mock_audio):
    mock_audio.transcribe.side_effect = Exception("API error")
    from app import process_voice_message
    result = process_voice_message("http://test/audio.mp3", "+15551234567", "corrid-2")
    assert "couldn't process" in result.lower() or "error" in result.lower()
