# RK3588 语义视觉工作进程

`vlm_worker.cpp` 是项目自己的薄适配层。它在同一进程内常驻加载视觉编码器和 RKLLM，
随后从标准输入逐行接收 JPEG 文件路径，避免视频语义刷新时反复加载模型。

构建时使用固定提交 `3aa2c11b8a1f3db15a6d4145e4f93840a9a02cb4` 的
[`Qengineering/Qwen3-VL-2B-NPU`](https://github.com/Qengineering/Qwen3-VL-2B-NPU)
提供的 `RK35llm.cpp/.h` 与 Rockchip 运行库。第三方代码继续遵循其 BSD-3-Clause 许可证，
不会被复制进本项目源码；板端安装脚本会固定提交并隔离运行库路径，避免覆盖现有 YOLO 的
`librknnrt.so 2.1.0`。
