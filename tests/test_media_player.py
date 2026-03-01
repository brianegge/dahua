"""Tests for media_player platform."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from homeassistant.components.media_player import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
)

from custom_components.dahua.media_player import (
    DahuaSpeaker,
    _convert_to_g711a,
    _fetch_and_convert_audio,
    async_setup_entry,
)


class TestAsyncSetupEntry:
    @pytest.mark.asyncio
    async def test_speaker_added_for_siren_model(
        self, hass, mock_coordinator, mock_config_entry
    ):
        """Speaker entity added for cameras with sirens."""
        mock_coordinator.model = "IPC-HDW3849HP-AS-PV"
        mock_config_entry.runtime_data = mock_coordinator
        added = []

        await async_setup_entry(hass, mock_config_entry, added.append)

        assert len(added) == 1
        assert isinstance(added[0][0], DahuaSpeaker)

    @pytest.mark.asyncio
    async def test_speaker_added_for_doorbell(
        self, hass, mock_coordinator, mock_config_entry
    ):
        """Speaker entity added for doorbells."""
        mock_coordinator.model = "VTO2111D-WP"
        mock_config_entry.runtime_data = mock_coordinator
        added = []

        await async_setup_entry(hass, mock_config_entry, added.append)

        assert len(added) == 1
        assert isinstance(added[0][0], DahuaSpeaker)

    @pytest.mark.asyncio
    async def test_speaker_added_for_amcrest_doorbell(
        self, hass, mock_coordinator, mock_config_entry
    ):
        """Speaker entity added for Amcrest doorbells."""
        mock_coordinator.model = "AD410"
        mock_config_entry.runtime_data = mock_coordinator
        added = []

        await async_setup_entry(hass, mock_config_entry, added.append)

        assert len(added) == 1

    @pytest.mark.asyncio
    async def test_speaker_not_added_for_basic_camera(
        self, hass, mock_coordinator, mock_config_entry
    ):
        """Speaker entity NOT added for basic cameras without siren/doorbell."""
        mock_coordinator.model = "IPC-HDW5831R-ZE"
        mock_config_entry.runtime_data = mock_coordinator
        added = []

        await async_setup_entry(hass, mock_config_entry, added.append)

        assert len(added) == 0


class TestDahuaSpeaker:
    def test_unique_id(self, mock_coordinator, mock_config_entry):
        speaker = DahuaSpeaker(mock_coordinator, mock_config_entry)
        assert speaker.unique_id == "SERIAL123_speaker"

    def test_translation_key(self, mock_coordinator, mock_config_entry):
        speaker = DahuaSpeaker(mock_coordinator, mock_config_entry)
        assert speaker._attr_translation_key == "speaker"

    def test_initial_state(self, mock_coordinator, mock_config_entry):
        speaker = DahuaSpeaker(mock_coordinator, mock_config_entry)
        assert speaker.state == MediaPlayerState.IDLE

    def test_supported_features(self, mock_coordinator, mock_config_entry):
        speaker = DahuaSpeaker(mock_coordinator, mock_config_entry)
        assert speaker.supported_features == MediaPlayerEntityFeature.PLAY_MEDIA

    @pytest.mark.asyncio
    async def test_play_media(self, hass, mock_coordinator, mock_config_entry):
        """async_play_media fetches, converts, and posts audio."""
        mock_coordinator.client.async_post_audio = AsyncMock()
        speaker = DahuaSpeaker(mock_coordinator, mock_config_entry)
        speaker.hass = hass
        speaker.async_write_ha_state = MagicMock()

        fake_g711a = b"\x00\x01\x02"
        with patch(
            "custom_components.dahua.media_player._fetch_and_convert_audio",
            return_value=fake_g711a,
        ) as mock_fetch:
            await speaker.async_play_media("music", "http://example.com/audio.wav")

            mock_fetch.assert_called_once_with(hass, "http://example.com/audio.wav")
            mock_coordinator.client.async_post_audio.assert_called_once_with(
                fake_g711a, 1
            )

        # State should be back to IDLE
        assert speaker._attr_state == MediaPlayerState.IDLE

    @pytest.mark.asyncio
    async def test_play_media_state_transitions(
        self, hass, mock_coordinator, mock_config_entry
    ):
        """State transitions: IDLE -> PLAYING -> IDLE."""
        mock_coordinator.client.async_post_audio = AsyncMock()
        speaker = DahuaSpeaker(mock_coordinator, mock_config_entry)
        speaker.hass = hass

        states = []
        speaker.async_write_ha_state = lambda: states.append(speaker._attr_state)

        with patch(
            "custom_components.dahua.media_player._fetch_and_convert_audio",
            return_value=b"\x00",
        ):
            await speaker.async_play_media("music", "http://example.com/audio.wav")

        assert states == [MediaPlayerState.PLAYING, MediaPlayerState.IDLE]

    @pytest.mark.asyncio
    async def test_play_media_error_resets_state(
        self, hass, mock_coordinator, mock_config_entry
    ):
        """On error, state resets to IDLE."""
        speaker = DahuaSpeaker(mock_coordinator, mock_config_entry)
        speaker.hass = hass
        speaker.async_write_ha_state = MagicMock()

        with (
            patch(
                "custom_components.dahua.media_player._fetch_and_convert_audio",
                side_effect=aiohttp.ClientError("fetch failed"),
            ),
            pytest.raises(Exception),
        ):
            await speaker.async_play_media("music", "http://example.com/audio.wav")

        assert speaker._attr_state == MediaPlayerState.IDLE


class TestFetchAndConvertAudio:
    @pytest.mark.asyncio
    async def test_fetches_url_and_converts(self, hass):
        """Fetches audio from URL via aiohttp and runs ffmpeg conversion."""
        mock_response = AsyncMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.read = AsyncMock(return_value=b"\x00\x01\x02")
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get = MagicMock(return_value=mock_response)

        converted = b"\xd5\xd5"
        with (
            patch(
                "custom_components.dahua.media_player.async_get_clientsession",
                return_value=mock_session,
            ),
            patch(
                "custom_components.dahua.media_player._convert_to_g711a",
                return_value=converted,
            ),
        ):
            result = await _fetch_and_convert_audio(hass, "http://example.com/tts.wav")

        assert result == converted
        mock_session.get.assert_called_once_with("http://example.com/tts.wav")


class TestConvertToG711a:
    def test_ffmpeg_called_with_correct_args(self):
        """ffmpeg is invoked with correct arguments."""
        fake_output = b"\xd5\xd5\xd5"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = fake_output

        with patch(
            "custom_components.dahua.media_player.subprocess.run",
            return_value=mock_result,
        ) as mock_run:
            result = _convert_to_g711a(b"\x00\x01\x02")

            mock_run.assert_called_once_with(
                [
                    "ffmpeg",
                    "-i",
                    "pipe:0",
                    "-f",
                    "alaw",
                    "-ar",
                    "8000",
                    "-ac",
                    "1",
                    "pipe:1",
                ],
                input=b"\x00\x01\x02",
                capture_output=True,
            )
            assert result == fake_output

    def test_ffmpeg_failure_raises_runtime_error(self):
        """Failed ffmpeg raises RuntimeError."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = b"some error"

        with (
            patch(
                "custom_components.dahua.media_player.subprocess.run",
                return_value=mock_result,
            ),
            pytest.raises(RuntimeError, match="ffmpeg failed"),
        ):
            _convert_to_g711a(b"\x00\x01\x02")
