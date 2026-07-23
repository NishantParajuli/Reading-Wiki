import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { acquisitionApi } from "./api.js";
import { PlanEditor, UploadDrop } from "./ImportParts.jsx";


describe("ImportParts", () => {
  beforeEach(() => {
    vi.spyOn(acquisitionApi, "importFile").mockReset();
  });

  it("queues every selected volume instead of discarding all but the first", async () => {
    const onUploaded = vi.fn();
    acquisitionApi.importFile
      .mockResolvedValueOnce({ id: 41, duplicate_of: [] })
      .mockResolvedValueOnce({ id: 42, duplicate_of: [] });
    const user = userEvent.setup();
    const { container } = render(<UploadDrop onUploaded={onUploaded} />);
    const input = container.querySelector('input[type="file"]');
    const files = [
      new File(["volume one"], "series_01.pdf", { type: "application/pdf" }),
      new File(["volume two"], "series_02.pdf", { type: "application/pdf" }),
    ];

    await user.upload(input, files);

    await waitFor(() => expect(acquisitionApi.importFile).toHaveBeenCalledTimes(2));
    expect(acquisitionApi.importFile.mock.calls.map(call => call[0].name)).toEqual([
      "series_01.pdf", "series_02.pdf",
    ]);
    expect(onUploaded).toHaveBeenNthCalledWith(1, 41, []);
    expect(onUploaded).toHaveBeenNthCalledWith(2, 42, []);
  });

  it("auto-selects a matching series and commits the next PDF as a volume", async () => {
    const onCommit = vi.fn();
    const job = {
      id: 7,
      detected_meta: {
        series: "Starbound Tales",
        series_index: 2,
        volume_label: "Volume 2",
        language: "en",
      },
      options: {},
      _novels: [
        { id: 11, title: "Starbound Tales", can_edit: true },
        { id: 12, title: "Another Book", can_edit: true },
      ],
    };
    const plan = {
      version: 1,
      segments: [{
        id: "s1", title: "Chapter 1", kind: "chapter", number: 1,
        include: true, block_range: [0, 1], word_count: 20,
      }],
    };
    const user = userEvent.setup();
    render(
      <PlanEditor
        job={job}
        plan={plan}
        setPlan={vi.fn()}
        metadata={{
          title: "Starbound Tales — Volume 2",
          author: "",
          description: "",
          language: "en",
          series: "Starbound Tales",
          series_index: "2",
          volume_label: "Volume 2",
        }}
        setMetadata={vi.fn()}
        onSave={vi.fn()}
        onCommit={onCommit}
        busy={false}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Starbound Tales" }).selected).toBe(true);
    });
    await user.click(screen.getByRole("button", { name: "Commit" }));

    expect(onCommit).toHaveBeenCalledWith({
      mode: "append",
      novel_id: 11,
      offset: 0,
      is_raw: false,
      as_volume: true,
    });
  });

  it("lets a bare volume filename be replaced with authoritative user metadata", async () => {
    const onSave = vi.fn();
    const onCommit = vi.fn();
    const plan = {
      version: 1,
      segments: [{
        id: "s1", title: "Chapter 1", kind: "chapter", number: 1,
        include: true, block_range: [0, 1], word_count: 20,
      }],
    };
    const job = {
      id: 8,
      detected_meta: { title: "Vol 2", series_index: 2, volume_label: "Volume 2" },
      options: {},
      _novels: [{ id: 21, title: "Mushoku Tensei", can_edit: true }],
    };
    function Harness() {
      const [metadata, setMetadata] = React.useState({
        title: "Vol 2",
        author: "",
        description: "",
        language: "en",
        series: "",
        series_index: "2",
        volume_label: "Volume 2",
      });
      return (
        <PlanEditor
          job={job}
          plan={plan}
          setPlan={vi.fn()}
          metadata={metadata}
          setMetadata={setMetadata}
          onSave={() => onSave(metadata)}
          onCommit={onCommit}
          busy={false}
        />
      );
    }
    const user = userEvent.setup();
    render(<Harness />);

    await user.clear(screen.getByRole("textbox", { name: "Book title" }));
    await user.type(screen.getByRole("textbox", { name: "Book title" }), "Mushoku Tensei Vol. 2");
    await user.type(screen.getByRole("textbox", { name: "Author" }), "Rifujin na Magonote");
    await user.type(screen.getByRole("textbox", { name: "Series / novel name" }), "Mushoku Tensei");
    await user.clear(screen.getByRole("textbox", { name: "Volume/group label" }));
    await user.type(screen.getByRole("textbox", { name: "Volume/group label" }), "Volume II");
    await user.click(screen.getByRole("button", { name: "Save review" }));

    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({
      title: "Mushoku Tensei Vol. 2",
      author: "Rifujin na Magonote",
      series: "Mushoku Tensei",
      series_index: "2",
      volume_label: "Volume II",
    }));
    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Mushoku Tensei" }).selected).toBe(true);
    });
    await user.click(screen.getByRole("button", { name: "Commit" }));
    expect(onCommit).toHaveBeenCalledWith(expect.objectContaining({
      mode: "append",
      novel_id: 21,
      as_volume: true,
    }));
  });
});
