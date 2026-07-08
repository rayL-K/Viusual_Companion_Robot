const STAGE_WIDTH = 750;

function createGameLayout(stageHeight, insets = {}) {
  const side = 24;
  const gap = 14;
  const contentWidth = STAGE_WIDTH - side * 2;
  const halfWidth = (contentWidth - gap) / 2;
  const safeTop = Math.max(0, Number(insets.top) || 0);
  const safeBottom = Math.max(26, Number(insets.bottom) || 0);
  const buttonHeight = 64;
  const secondaryY = stageHeight - safeBottom - buttonHeight;
  const primaryY = secondaryY - gap - buttonHeight;
  const inputY = primaryY - 82;
  const bubbleHeight = 148;
  const bubbleY = inputY - 18 - bubbleHeight;

  return {
    width: STAGE_WIDTH,
    height: stageHeight,
    side,
    gap,
    contentWidth,
    halfWidth,
    header: { x: side, y: safeTop + 14, width: contentWidth, height: 64 },
    bubble: { x: side, y: bubbleY, width: contentWidth, height: bubbleHeight },
    input: { x: side, y: inputY, width: contentWidth, height: 64 },
    primaryButtons: [
      { x: side, y: primaryY, width: halfWidth, height: buttonHeight },
      { x: side + halfWidth + gap, y: primaryY, width: halfWidth, height: buttonHeight },
    ],
    secondaryButtons: [
      { x: side, y: secondaryY, width: halfWidth, height: buttonHeight },
      { x: side + halfWidth + gap, y: secondaryY, width: halfWidth, height: buttonHeight },
    ],
    panel: {
      x: 16,
      y: safeTop + 94,
      width: STAGE_WIDTH - 32,
      height: stageHeight - safeTop - safeBottom - 104,
    },
  };
}

function containsPoint(rect, x, y) {
  return x >= rect.x && x <= rect.x + rect.width && y >= rect.y && y <= rect.y + rect.height;
}

function paginate(items, page, pageSize) {
  const pageCount = Math.max(1, Math.ceil(items.length / pageSize));
  const safePage = Math.max(0, Math.min(pageCount - 1, Number(page) || 0));
  return {
    page: safePage,
    pageCount,
    items: items.slice(safePage * pageSize, (safePage + 1) * pageSize),
  };
}

module.exports = { STAGE_WIDTH, containsPoint, createGameLayout, paginate };
