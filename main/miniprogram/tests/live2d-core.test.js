const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const Live2DCubismCore = require("../libs/live2dcubismcore.min");

test("Cubism Core 能读取草莓兔兔的 MocVersion 5 模型", () => {
  const modelPath = path.join(
    __dirname,
    "..",
    "..",
    "assets",
    "live2d",
    "Strawberry_Rabbit",
    "Strawberry_Rabbit.moc3",
  );
  const modelBuffer = fs.readFileSync(modelPath);
  const arrayBuffer = modelBuffer.buffer.slice(
    modelBuffer.byteOffset,
    modelBuffer.byteOffset + modelBuffer.byteLength,
  );

  assert.ok(Live2DCubismCore.Version.csmGetLatestMocVersion() >= 5);
  const moc = Live2DCubismCore.Moc.fromArrayBuffer(arrayBuffer);
  assert.ok(moc, "Cubism Core 必须能解析当前 moc3 文件");
  moc._release();
});
