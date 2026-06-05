export const USE_VIRTUAL_LIST = true;
export const VIRTUAL_LIST_THRESHOLD = 30;
export const VIRTUAL_ROW_ESTIMATE_PX = 72;
export const VIRTUAL_CARD_ESTIMATE_PX = 120;

export function shouldUseVirtualList(count) {
  return USE_VIRTUAL_LIST && count >= VIRTUAL_LIST_THRESHOLD;
}
