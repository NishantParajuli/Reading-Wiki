import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { narrationApi } from "../narration/api.js";
import { AudioPlayer } from "./ReaderParts.jsx";
import { pollNarrationJob } from "./narrationPolling.js";

vi.mock("../narration/api.js", () => ({
  narrationApi: {
    ttsVoices: vi.fn(),
    chapterAudioStatus: vi.fn(),
    chapterAudioUrl: vi.fn((id, number, voice) => (
      `/api/novels/${id}/chapter/${number}/audio.opus?voice_id=${voice}`
    )),
    ttsJob: vi.fn(),
    generateChapterAudio: vi.fn(),
  },
}));

vi.mock("../narration/index.js", () => ({
  readTtsPrefs: () => ({ voice: "v1", speed: 1, autoplay: false }),
  VoicePicker: () => <span>Voice picker</span>,
}));

vi.mock("./narrationPolling.js", () => ({
  pollNarrationJob: vi.fn(() => vi.fn()),
}));

describe("AudioPlayer regeneration recovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    narrationApi.ttsVoices.mockResolvedValue({
      default: "v1",
      voices: [{ id: "v1", name: "Narrator", ready: true }],
    });
    narrationApi.chapterAudioStatus.mockResolvedValue({
      cached: true,
      voice_id: "v1",
      available_voices: ["v1"],
      timing: null,
      job_id: 33,
      job_status: "generating",
    });
  });

  it("keeps cached audio playable and follows an active regeneration after reload", async () => {
    render(
      <AudioPlayer
        novelId={41}
        number={320}
        ch={{}}
        user={{ prefs: {} }}
        narrationChunks={[]}
      />,
    );

    await waitFor(() => expect(pollNarrationJob).toHaveBeenCalledTimes(1));

    expect(document.querySelector("audio")).toHaveAttribute(
      "src",
      "/api/novels/41/chapter/320/audio.opus?voice_id=v1",
    );
    expect(screen.getByText("Updating…")).toBeInTheDocument();
    expect(pollNarrationJob).toHaveBeenCalledWith(expect.objectContaining({
      jobId: 33,
      loadJob: expect.any(Function),
      onRetry: expect.any(Function),
      onTerminal: expect.any(Function),
    }));

    const { onTerminal } = pollNarrationJob.mock.calls[0][0];
    await act(async () => onTerminal({
      id: 33,
      status: "done",
      readyAudio: {
        cached: true,
        available_voices: ["v1"],
        timing: { version: 1, duration_ms: 1000, paragraphs: [] },
      },
    }));

    expect(document.querySelector("audio").getAttribute("src")).toMatch(
      /^\/api\/novels\/41\/chapter\/320\/audio\.opus\?voice_id=v1&t=\d+$/,
    );
    expect(screen.queryByText("Updating…")).not.toBeInTheDocument();
  });
});
