# VoxCPM2 参考音频样本

这些 MP3 来自本机解压包：

```text
E:\jieya\yzylauncher-voxcpm2-tts\python\saved_voices
```

用途是给 VoxCPM 提供参考音色，同时用于检查浏览器音频播放是否正常。它们不是“按当前文本实时生成”的语音，也不再作为语音模型占位项展示。

来源项目为 OpenBMB/VoxCPM，整合包根目录声明 Apache-2.0 许可证。后续正式演示仍应使用自建 VoxCPM2 或其他授权 TTS 服务实时生成音频。

## 已复制样本与文本

- `clear_young_girl.mp3`：清脆少女。文本：你是否会停下脚步，在结束忙碌的一天后，认真感受身边的世界？
- `soft_girl.mp3`：软软女孩。文本：很高兴认识你哦，我刚刚买了杯珍珠奶茶，我们一起去公园长椅上坐坐吧。
- `sweet_female.mp3`：甜美女声。文本：有时候我的心里会有很多话想说，可是到了嘴边就变得笨拙了，好像总也说不好。
- `warm_young_girl.mp3`：温暖少女。文本：或许今天的你并不完美，或许你还在寻找那个属于自己的方向，但不要急，再给自己一点时间吧。
- `gentle_senior_girl.mp3`：温柔学姐。文本：只要心中有坚定的目标，我相信前方的路总会越来越明朗的。

对应结构化元数据见 `metadata.json`。

这些文本由本地 ASR 转写得到，适合开发期作为 `prompt_text` 或样本说明使用。正式训练、微调或作品展示前，应对照原始音频人工校对。

## 与 VoxCPM 的关系

这些样本可以作为 VoxCPM 推理时的参考音频和参考文本使用：

```text
reference = main/assets/tts/voxcpm_samples/<sample>.mp3
prompt_text = 对应文本
```

但它们不是 VoxCPM 的模型权重，也不能替代正式训练数据。若后续要做训练或微调，应单独建立合法授权、人工校对、说话人一致的数据集。
