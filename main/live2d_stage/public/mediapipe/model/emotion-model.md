# 浏览器端情绪 ONNX 模型

当前模型来自 Hugging Face 仓库 `dwest1507/emotion-detection-model`：

```text
https://huggingface.co/dwest1507/emotion-detection-model
```

用途：在浏览器端通过 `onnxruntime-web` 对摄像头裁剪出的人脸做 FER-2013 七分类情绪识别。

当前文件：

```text
emotion.onnx
```

注意：原始 Hugging Face 文件由 `emotion_classifier.onnx` 和 `emotion_classifier.onnx.data` 组成。`onnxruntime-web` 在浏览器中不能稳定加载这个外部权重形态，所以项目内的 `emotion.onnx` 已经用 `onnx.save_model(..., save_as_external_data=False)` 合并为单文件模型。

当前前端适配参数：

```text
输入尺寸：1 x 3 x 224 x 224
颜色通道：RGB
归一化：ImageNet mean/std
标签顺序：angry, disgust, fear, happy, sad, surprise, neutral
```

如果后续替换为 48 x 48 灰度 Mini-Xception 或 RKNN/NPU 版本，需要同步修改 `src/emotion-onnx-client.js` 中的输入尺寸、通道数、归一化方式和标签顺序。
