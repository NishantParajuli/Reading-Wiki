import React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TOC_ROW_HEIGHT, VolumeTOC, groupToc } from "./toc.jsx";

const volumes = [
  ...Array.from({ length: 3 }, (_, i) => ({ number: i + 1, title: `Shore ${i + 1}`, part_label: "Volume 1: The Shore", has_content: true })),
  ...Array.from({ length: 3 }, (_, i) => ({ number: i + 4, title: `Deep ${i + 4}`, part_label: "Volume 2: Undertow", has_content: true })),
];

describe("VolumeTOC", () => {
  it("groups consecutive part labels into volumes", () => {
    const nodes = groupToc(volumes);
    expect(nodes.map(n => n.type)).toEqual(["vol", "vol"]);
    expect(nodes[1].chapters.map(c => c.number)).toEqual([4, 5, 6]);
  });

  it("opens the current volume, marks your place and read state, and toggles others", () => {
    vi.useFakeTimers();
    render(<VolumeTOC toc={volumes} currentNumber={5} maxRead={4} onOpen={vi.fn()} virtualize={false} />);
    const heads = screen.getAllByRole("button", { expanded: false }).concat(screen.getAllByRole("button", { expanded: true }));
    expect(heads).toHaveLength(2);
    const current = screen.getByRole("button", { name: /Deep 5/ });
    expect(current).toHaveAttribute("aria-current", "location");
    expect(within(current).getByText("You are here")).toBeInTheDocument();
    expect(within(screen.getByRole("button", { name: /Deep 4/ })).getByRole("img", { name: "Read" })).toBeInTheDocument();
    expect(within(screen.getByRole("button", { name: /Deep 6/ })).getByRole("img", { name: "Unread" })).toBeInTheDocument();

    const shore = screen.getByRole("button", { name: /The Shore/ });
    expect(shore).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: /Shore 1/ })).not.toBeInTheDocument();
    fireEvent.click(shore);
    expect(shore).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("button", { name: /Shore 1/ })).toBeInTheDocument();
    fireEvent.click(shore);
    expect(shore).toHaveAttribute("aria-expanded", "false");
    act(() => { vi.advanceTimersByTime(600); });
    expect(screen.queryByRole("button", { name: /Shore 1/ })).not.toBeInTheDocument();
    vi.useRealTimers();
  });

  it("opens a chapter from its row", () => {
    const onOpen = vi.fn();
    render(<VolumeTOC toc={volumes} currentNumber={5} maxRead={4} onOpen={onOpen} virtualize={false} />);
    fireEvent.click(screen.getByRole("button", { name: /Deep 6/ }));
    expect(onOpen).toHaveBeenCalledWith(6);
  });

  it("windows long flat lists but renders every row when virtualization is off", () => {
    const flat = Array.from({ length: 450 }, (_, i) => ({ number: i + 1, title: `Chapter title ${i + 1}`, has_content: true }));
    const { unmount } = render(<VolumeTOC toc={flat} currentNumber={null} maxRead={null} onOpen={vi.fn()} />);
    const windowed = screen.getAllByRole("button");
    expect(windowed.length).toBeLessThan(100);
    expect(windowed[0]).toHaveStyle({ height: `${TOC_ROW_HEIGHT}px` });
    unmount();
    render(<VolumeTOC toc={flat} currentNumber={null} maxRead={null} onOpen={vi.fn()} virtualize={false} />);
    expect(screen.getAllByRole("button")).toHaveLength(450);
  });
});
