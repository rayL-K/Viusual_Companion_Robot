import os
import time
import multiprocessing as mp

# ==============================================================================
# 核心算力池分配说明 (硬件资源映射)
# - TTS引擎: 核心阵地 (CPU 大核 A76 x2) -> 确保语音合成实时率，实现流式秒回。
# - ASR引擎: 听觉阵地 (CPU 大核 A76 x1) -> 配合VAD实现毫秒级精准拾音。
# - UI与表现层: (GPU Mali-G610) -> PyQt强制开启OpenGL ES，接管Live2D物理与表情。
# - 视觉感知追踪: (NPU 6 TOPS) -> rknn_model_zoo + GStreamer，60FPS+。
# - 认知与大脑: (CPU 小核 A55) -> 逻辑调度与LangChain记忆交互。
# ==============================================================================

def vision_engine(vision_queue):
    """
    Process 1: Vision_Engine (感知层 - NPU)
    负责拉取 GStreamer 帧 -> RKNN 人脸检测 -> 卡尔曼滤波平滑坐标 -> 压入 Vision_Queue
    """
    print("[Vision_Engine] 启动: 准备驱动 NPU (GStreamer + RKNN_Model_Zoo)")
    while True:
        try:
            # 模拟 ~30/60FPS 视觉循环
            time.sleep(0.033)
            
            # 模拟获取到追踪到的头部坐标与状态
            dummy_head_data = {"x": 0.0, "y": 0.0, "z": 0.0}
            
            # 使用 put_nowait/full 防止视觉旧数据累积
            if not vision_queue.full():
                vision_queue.put(dummy_head_data)
        except KeyboardInterrupt:
            print("\n[Vision_Engine] 接收到退出指令，清理中...")
            break
        except Exception:
            pass

def asr_engine(text_queue):
    """
    Process 2: ASR_Engine (听觉层 - A76)
    负责麦克风拾音 -> VAD过滤 -> Sherpa-onnx转写 -> 压入 Text_Queue
    """
    print(f"[ASR_Engine] 启动 (PID: {os.getpid()}): 准备 VAD 端点检测与 Sherpa-onnx")
    while True:
        try:
            # 模拟环境拾音并转变为完整文本
            time.sleep(3.0)
            text_result = "环境音模拟转写文本"
            # print(f"[ASR_Engine] 听到并识别: {text_result}")
            
            # 压入文字队列供认知大脑处理
            text_queue.put(text_result)
        except KeyboardInterrupt:
            print("\n[ASR_Engine] 接收到退出指令，清理中...")
            break
        except Exception:
            pass

def cognitive_brain(text_queue, action_queue):
    """
    Process 3: Cognitive_Brain (认知层 - A55)
    负责读取 Text_Queue -> 查询 SQLite 记忆 -> LangChain 大模型调度 -> 强制 JSON 输出并压入 Action_Queue
    """
    print("[Cognitive_Brain] 启动: 准备 SQLite 记忆库与 LangChain 逻辑流")
    while True:
        try:
            # 从 ASR 队列获取文字
            user_text = text_queue.get()
            print(f"[Cognitive_Brain] 收到用户输入: '{user_text}'，思考中...")
            
            time.sleep(1.0) # 模拟大模型思考延迟
            
            # 模拟大模型严格输出 JSON 格式
            decision_json = {
                "text": "辛苦啦，喝杯水吧", 
                "emotion": "smile", 
                "action": "nod"
            }
            print(f"[Cognitive_Brain] 大模型决策生成: {decision_json}")
            
            # 分发到动作队列供 TTS 表达
            action_queue.put(decision_json)
        except KeyboardInterrupt:
            print("\n[Cognitive_Brain] 接收到退出指令，清理中...")
            break
        except Exception:
            pass

def tts_engine(action_queue, ui_queue):
    """
    Process 4: TTS_Engine (表达层 - A76 核心主战场)
    负责读取 Action_Queue -> 本地声学模型/声码器 -> 同步计算唇形RMS -> 打包音频流与指令压入 UI_Queue
    """
    print(f"[TTS_Engine] 启动 (PID: {os.getpid()}): 准备本地流式 TTS 模型加速")
    while True:
        try:
            # 从大脑获取指令
            action_data = action_queue.get()
            text_to_speak = action_data.get("text", "")
            emotion = action_data.get("emotion", "neutral")
            action = action_data.get("action", "idle")
            
            print(f"[TTS_Engine] 开始合成语音: '{text_to_speak}'")
            time.sleep(0.5) # 模拟 RTF < 1 流式秒回
            
            # 模拟生成的音频 buffer 和 唇形开合度计算
            audio_buffer = b"mock_audio_stream_data..."
            lip_feature = 0.85 # ParamMouthOpenY
            
            # 打包所有的组合动作并送往 UI
            ui_command = (audio_buffer, lip_feature, emotion, action)
            ui_queue.put(ui_command)
        except KeyboardInterrupt:
            print("\n[TTS_Engine] 接收到退出指令，清理中...")
            break
        except Exception:
            pass

def ui_live2d_main(vision_queue, ui_queue):
    """
    Process 5: UI_Live2D_Main (主进程表现层 - GPU)
    负责运行 PyQt 事件循环 -> OpenGL 硬件渲染 -> 处理视觉追踪 LookAt -> 播放音频与表情
    """
    print("[UI_Live2D_Main] 启动: 强制绑定 OpenGL ES 加速，驱动 Live2D 模型")
    while True:
        try:
            # 1. 极低延迟非阻塞读取视觉队列，实现视线跟随 (LookAt)
            if not vision_queue.empty():
                head_pos = vision_queue.get_nowait()
                # 更新坐标系统，驱动模型转头
            
            # 2. 监听并响应 TTS 传来的表现队列
            if not ui_queue.empty():
                audio_buffer, lip_feature, emotion, action = ui_queue.get_nowait()
                print(f"[UI_Live2D_Main] 接收到表现指令 >>> 准备播放音频，触发表情: {emotion}，嘴型: {lip_feature}，动作: {action}")
            
            # 模拟 UI 不断重绘的高帧率循环
            time.sleep(0.016) # ~60FPS 渲染循环
        except KeyboardInterrupt:
            print("\n[UI_Live2D_Main] 接收到退出指令，清理中...")
            break
        except Exception:
            pass

def main():
    print("=======================================================================")
    print("   虚拟陪伴机器人系统核心总线启动 (基于 RK3588 五进程流水线架构)")
    print("=======================================================================\n")

    # 兼容跨平台隐患，显式设置为 spawn 机制避免多余状态拷贝
    mp.set_start_method('spawn')

    """
    一、构建非阻塞流水线所需的 Queue (Producer-Consumer 模式)
    """
    # 视觉感知队列: maxsize=1，避免消费者读得慢导致旧帧堆积，只留最实时数据
    vision_queue = mp.Queue(maxsize=1) 
    text_queue = mp.Queue()
    action_queue = mp.Queue()
    ui_queue = mp.Queue()

    """
    二、装配 5 大核心独立进程
    """
    processes = []
    
    p_vision = mp.Process(target=vision_engine, args=(vision_queue,), name="Vision_Engine")
    p_asr = mp.Process(target=asr_engine, args=(text_queue,), name="ASR_Engine")
    p_brain = mp.Process(target=cognitive_brain, args=(text_queue, action_queue), name="Cognitive_Brain")
    p_tts = mp.Process(target=tts_engine, args=(action_queue, ui_queue), name="TTS_Engine")
    p_ui = mp.Process(target=ui_live2d_main, args=(vision_queue, ui_queue), name="UI_Live2D_Main")
    
    processes.extend([p_vision, p_asr, p_brain, p_tts, p_ui])

    for p in processes:
        p.start()
        
    print("\n>>> 底层 5 大进程已成功挂载...\n")

    """
    三、核心算力池分配 (硬件资源映射 - Linux 任务绑定)
    在此预留特定加速库与 taskset 绑定大核的代码。
    RK3588: (CPU 小核 A55: 0-3), (CPU 大核 A76: 4-7)
    """
    # 假设给 ASR 绑定大核 4
    # os.system(f'taskset -cp 4 {p_asr.pid}')
    print(f"[*] 算力切分动作 (预留): 已为 ASR_Engine(PID:{p_asr.pid}) 锁定 A76 大核 (core 4)。")

    # 假设给 TTS 绑定大核 5, 6
    # os.system(f'taskset -cp 5,6 {p_tts.pid}')
    print(f"[*] 算力切分动作 (预留): 已为 TTS_Engine(PID:{p_tts.pid}) 锁定 A76 大核双核 (core 5, 6)。\n")

    """
    四、优雅退出机制 (Graceful Shutdown)
    防止子进程卡死或产生僵尸进程 (Zombie Processes)
    """
    try:
        # 主总线保持守候
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[Sys_Main] 接收到系统中断信号 (KeyboardInterrupt)。正在启动退出清理序列...\n")
    finally:
        # 发送软终止信号
        print("[Sys_Main] 将终止各核心进程...")
        for p in processes:
            if p.is_alive():
                print(f" -> 正在申请终止进程: {p.name} (PID: {p.pid})...")
                p.terminate()
        
        # 强制接管超时子进程
        for p in processes:
            p.join(timeout=3)
            if p.is_alive():
                print(f" -> [警告] {p.name} 未响应软终止，执行系统强制 Kill (PID: {p.pid})...")
                p.kill()
        
        print("\n[Sys_Main] 释放系统管道内存块 (Queue 清空)...")
        # 清除管道残留数据，防止底层信号量死锁
        for q in [vision_queue, text_queue, action_queue, ui_queue]:
            try:
                while not q.empty():
                    q.get_nowait()
            except Exception:
                pass
            q.close()
            q.join_thread()
            
        print("\n>>> 虚拟陪伴机器人系统已安全退出！祝你生活愉快。 <<<")

if __name__ == '__main__':
    main()
