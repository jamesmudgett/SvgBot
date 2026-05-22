/** Same logic as CSS object-fit: contain within a box. */
export function fitContain(
  naturalWidth: number,
  naturalHeight: number,
  boxWidth: number,
  boxHeight: number
): { width: number; height: number } {
  if (naturalWidth <= 0 || naturalHeight <= 0 || boxWidth <= 0 || boxHeight <= 0) {
    return { width: 0, height: 0 };
  }
  const scale = Math.min(boxWidth / naturalWidth, boxHeight / naturalHeight, 1);
  return {
    width: Math.max(1, Math.round(naturalWidth * scale)),
    height: Math.max(1, Math.round(naturalHeight * scale)),
  };
}
