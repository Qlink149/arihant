export const USE_VIRTUAL_LIST = true;
export const VIRTUAL_LIST_THRESHOLD = 15;
export const VIRTUAL_ROW_ESTIMATE_PX = 72;
export const VIRTUAL_ROW_ESTIMATE_PX_COMPACT = 48;
export const VIRTUAL_CARD_ESTIMATE_PX = 88;
export const TABLE_DENSITY_STORAGE_KEY = 'table-density';

export function getVirtualRowEstimate(density = 'comfortable') {
  return density === 'compact' ? VIRTUAL_ROW_ESTIMATE_PX_COMPACT : VIRTUAL_ROW_ESTIMATE_PX;
}

export function shouldUseVirtualList(count) {
  return USE_VIRTUAL_LIST && count >= VIRTUAL_LIST_THRESHOLD;
}
