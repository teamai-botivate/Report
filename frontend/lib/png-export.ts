import { toPng } from "html-to-image";

// Client-side render-to-PNG of the actual report DOM node — deliberately not
// a server call / image-generation model (see CLAUDE.md's PNG export note).
export async function exportNodeToPng(node: HTMLElement, filename: string): Promise<void> {
  const bg = getComputedBackgroundColor(node);
  const dataUrl = await toPng(node, { pixelRatio: 2, backgroundColor: bg });
  const a = document.createElement("a");
  a.href = dataUrl;
  a.download = filename.endsWith(".png") ? filename : `${filename}.png`;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function getComputedBackgroundColor(el: HTMLElement): string {
  const bg = getComputedStyle(el).backgroundColor;
  if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") return bg;
  return getComputedStyle(document.body).backgroundColor || "#ffffff";
}

export function slugify(text: string): string {
  return (
    text
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/(^-|-$)/g, "") || "report"
  );
}
