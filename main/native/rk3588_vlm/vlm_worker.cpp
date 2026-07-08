// 持久化 RK3588 VLM 工作进程：模型只加载一次，逐行接收 JPEG 路径。
#include "RK35llm.h"

#include <cstdint>
#include <iostream>
#include <string>

namespace {

constexpr char kPrompt[] =
    "<image>严格只输出一行简体中文，总共不超过45个汉字。格式：人物：外观和表情；动作：可见动作；"
    "环境：背景；物体：关键物体。先确认是否有人，无人写人物：无；看不清写不确定。"
    "只写清晰可见事实，禁止猜测年龄、身份、地点或画外内容，不要使用Markdown。";

std::string Base64Encode(const std::string& input) {
    static constexpr char alphabet[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string output;
    output.reserve((input.size() + 2) / 3 * 4);
    std::uint32_t value = 0;
    int bits = -6;
    for (const unsigned char byte : input) {
        value = (value << 8U) + byte;
        bits += 8;
        while (bits >= 0) {
            output.push_back(alphabet[(value >> bits) & 0x3FU]);
            bits -= 6;
        }
    }
    if (bits > -6) {
        output.push_back(alphabet[((value << 8U) >> (bits + 8)) & 0x3FU]);
    }
    while (output.size() % 4 != 0) output.push_back('=');
    return output;
}

void Emit(const char* marker, const std::string& value) {
    std::cout << marker << Base64Encode(value) << std::endl;
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::cerr << "usage: vlm_worker VISION_MODEL RKLLM_MODEL [MAX_NEW_TOKENS] [CONTEXT]" << std::endl;
        return 2;
    }

    const int max_new_tokens = argc > 3 ? std::stoi(argv[3]) : 96;
    const int context_length = argc > 4 ? std::stoi(argv[4]) : 1024;
    RK35llm model;
    model.SetInfo(false);
    model.SetSilence(true);
    if (!model.LoadModel(argv[1], argv[2], max_new_tokens, context_length)) {
        std::cerr << "VCR_FATAL:model initialization failed" << std::endl;
        return 3;
    }
    model.SetHistory(false);
    std::cout << "VCR_READY" << std::endl;

    std::string image_path;
    while (std::getline(std::cin, image_path)) {
        if (image_path == "VCR_EXIT") break;
        const cv::Mat image = cv::imread(image_path, cv::IMREAD_COLOR);
        if (image.empty()) {
            Emit("VCR_ERROR_BASE64:", "图片读取失败");
            continue;
        }
        model.LoadImage(image);
        const std::string response = model.Ask(kPrompt);
        if (response.empty()) Emit("VCR_ERROR_BASE64:", "模型返回空描述");
        else Emit("VCR_RESULT_BASE64:", response);
    }
    return 0;
}
