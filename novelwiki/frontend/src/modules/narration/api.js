import { API_BASE, getJSON, postJSON } from "../../shared/api/http.js";
const novel = (id) => `${API_BASE}/novels/${id}`;
export const narrationApi = {
  ttsVoices: () => getJSON(`${API_BASE}/tts/voices`),
  generateChapterAudio: (id, number, voiceId, force) => postJSON(
    `${novel(id)}/chapter/${number}/audio`, { voice_id: voiceId, force: !!force },
  ),
  chapterAudioStatus: (id, number, voiceId) => getJSON(
    `${novel(id)}/chapter/${number}/audio/status?voice_id=${encodeURIComponent(voiceId)}`,
  ),
  generateBookAudio: (id, voiceId, start, end) => postJSON(
    `${novel(id)}/audiobook`, { voice_id: voiceId, start: start ?? null, end: end ?? null },
  ),
  bookAudioStatus: (id, voiceId) => getJSON(`${novel(id)}/audiobook/status?voice_id=${encodeURIComponent(voiceId)}`),
  ttsJob: (id) => getJSON(`${API_BASE}/tts/jobs/${id}`),
  cancelTtsJob: (id) => postJSON(`${API_BASE}/tts/jobs/${id}/cancel`, {}),
  audioCoverage: (id) => getJSON(`${novel(id)}/audio/coverage`),
  chapterAudioUrl: (id, number, voiceId) => `${novel(id)}/chapter/${number}/audio.opus?voice_id=${encodeURIComponent(voiceId)}`,
};
